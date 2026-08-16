from __future__ import annotations
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import Concept, Event, GenerationRun, Question, QuestionStatus, ScientificClaim, Source, User
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider
from app.services.rights import can_use_for_generation
from app.services.validation import build_similarity_report, validate_candidate

PROMPT_VERSION = "competition-item-v2-difficulty-calibrated"

_SOLVER_SYSTEM = (
    "You are an INDEPENDENT solver. You receive ONLY a question stem and its answer choices — "
    "never the intended answer or any explanation. Solve it yourself from first principles. "
    'Return strict JSON: {"chosen_index": int, "confidence": number 0..1, '
    '"ambiguous": boolean, "insufficient": boolean}. Set "ambiguous" if more than one choice is '
    'defensibly correct; set "insufficient" if the stem lacks the information needed to answer.'
)


def _independent_solve(provider, stem: str, choices: list) -> dict:
    """Blind solve: the solver never sees the proposed correct answer."""
    return provider.generate_json(
        _SOLVER_SYSTEM,
        json.dumps({"stem": stem, "choices": [str(c) for c in choices]}),
    ).payload


def _solver_verdict(solver: dict, correct_index) -> tuple[bool, str]:
    """A candidate only survives if the blind solver independently reproduces the key."""
    if solver.get("insufficient"):
        return False, "solver_insufficient_information"
    if solver.get("ambiguous"):
        return False, "solver_reports_ambiguous"
    chosen = solver.get("chosen_index")
    if not isinstance(chosen, int) or chosen != correct_index:
        return False, "solver_disagrees_with_key"
    return True, "solver_agrees"


def _grounding_context(db: Session, concept: Concept | None,
                       event: Event | None = None) -> tuple[Source, list[ScientificClaim]]:
    """Claims that may ground an item for this concept — and only this event.

    This used to admit `concept_id IS NULL` alongside the concept's own claims, on the
    reasoning that an unattached claim is generally useful. It is not: an unattached claim
    belongs to whichever event harvested it, and nothing recorded which. So mineral claims
    harvested for Rocks & Minerals grounded items for **Meteorology** and **Chemistry Lab** —
    a chemistry exam asking which mineral effervesces in acid, and a meteorology item asking
    for the definition of a mineral. 229 of 292 generated items shared no vocabulary with
    their own event, and every one of them passed the solver, the verifier and the grounding
    gate, because each of those asks whether the item is *supported*, never whether it is
    *on topic*.

    Scoping is now explicit and fails closed: the concept's own claims first, then other
    claims of the same event, and never a claim whose event cannot be established.
    """
    base = select(ScientificClaim).where(
        ScientificClaim.approved.is_(True), ScientificClaim.source_snapshot_id.is_not(None)
    )
    claims: list[ScientificClaim] = []
    if concept is not None:
        claims = db.scalars(base.where(
            ScientificClaim.concept_id == concept.id).limit(8)).all()
    if not claims:
        target_event = event.id if event is not None else (
            concept.event_id if concept is not None else None)
        if target_event is None:
            raise ValueError(
                "cannot select grounding claims without an event to scope them to")
        sibling_ids = db.scalars(select(Concept.id).where(
            Concept.event_id == target_event)).all()
        if not sibling_ids:
            raise ValueError(
                "this event has no concepts, so no approved claims can ground its items")
        claims = db.scalars(base.where(
            ScientificClaim.concept_id.in_(sibling_ids)).limit(8)).all()
    for claim in claims:
        source = db.get(Source, claim.source_id)
        if source and can_use_for_generation(source.rights_status, source.approved):
            authorized = [c for c in claims if c.source_id == source.id]
            return source, authorized
    raise ValueError("No approved source-grounded claims are available")


def generate_model_questions(
    db: Session,
    actor: User,
    event: Event,
    concept: Concept | None,
    count: int,
    difficulty: float,
    cognitive_level: str,
) -> list[Question]:
    source, claims = _grounding_context(db, concept, event)
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise ModelProviderError("External model provider is not configured")
    claim_text = "\n".join(f"- [{c.id}] {c.claim_text}" for c in claims)
    # Difficulty used to be passed only as a bare number in the user payload, with nothing
    # saying what it should mean — and the model defaulted to single-fact recall items.
    # Reviewer feedback was blunt: too simple, too easy for the eighth-graders using them.
    # The audience calibration therefore lives in the system prompt, not the knob.
    system = (
        "You create original Science Olympiad-style practice items. Use only the approved claims. "
        "Do not copy known competition wording. Return strict JSON with an items array. Each item must "
        "contain stem, four choices, correct_index, explanation, claim_ids, estimated_seconds, and "
        "distractor_error_types keyed by choice index.\n"
        "AUDIENCE: Science Olympiad competitors — the strongest science students in their school, "
        "preparing for tournaments. An item a prepared competitor answers instantly from one "
        "remembered fact is a wasted item.\n"
        "DIFFICULTY: the difficulty field runs 0 (open-book warm-up) to 1 (national tiebreaker). "
        "At 0.5 and above, an item must take at least two reasoning steps before the answer is "
        "determined: combining claims, interpreting a described scenario or data, ranking or "
        "classifying close cases, or quantitative estimation.\n"
        "COGNITIVE LEVEL is a contract: only 'recall' items may be answerable from a single fact; "
        "'application', 'analysis', and 'transfer' items must be unanswerable by recall alone.\n"
        "STEMS: prefer scenario, data, and 'which would…' constructions over 'what is' definitions.\n"
        "DISTRACTORS: each wrong choice must be the precise endpoint of one plausible misconception "
        "or missed step — close enough that a student who half-knows the material hesitates. Never "
        "pad with obviously wrong options, and never let the correct choice be the longest or most "
        "hedged one."
    )
    user_prompt = json.dumps({
        "event": event.name,
        "division": event.division,
        "season": event.season,
        "concept": concept.name if concept else None,
        "count": count,
        "difficulty": difficulty,
        "cognitive_level": cognitive_level,
        "approved_claims": claim_text,
    })
    run = GenerationRun(
        actor_user_id=actor.id,
        event_id=event.id,
        concept_id=concept.id if concept else None,
        provider="openai-compatible",
        model=provider.model,
        prompt_version=PROMPT_VERSION,
        request_json={"event_id": event.id, "concept_id": concept.id if concept else None, "count": count},
        status="running",
    )
    db.add(run)
    db.flush()
    try:
        generated = provider.generate_json(system, user_prompt)
        items = generated.payload.get("items", [])
        if not isinstance(items, list) or not items:
            raise ModelProviderError("Model returned no items")
        results: list[Question] = []
        approved_ids = {c.id for c in claims}
        for raw in items[:count]:
            choices = raw.get("choices", [])
            claim_ids = [int(cid) for cid in raw.get("claim_ids", []) if int(cid) in approved_ids]
            answer_spec = {
                "correct_index": raw.get("correct_index"),
                "points": 1,
                "distractor_error_types": raw.get("distractor_error_types", {}),
            }
            report = validate_candidate(
                db,
                stem=str(raw.get("stem", "")),
                choices=[str(c) for c in choices],
                answer_spec=answer_spec,
                claim_ids=claim_ids,
                source_id=source.id,
            )
            # Independent SOLVER pass: re-derive the answer blind (no key shown). A candidate
            # only survives if the solver reproduces the key and finds it unambiguous.
            solver_payload = _independent_solve(provider, str(raw.get("stem", "")), choices)
            solver_ok, solver_reason = _solver_verdict(solver_payload, answer_spec["correct_index"])
            report["independent_solver"] = {**solver_payload, "verdict": solver_reason, "passed": solver_ok}
            if not solver_ok:
                report.setdefault("errors", []).append(solver_reason)

            # Independent verifier pass; failure keeps the item in draft.
            verify_payload = provider.generate_json(
                "Act as an independent scientific and assessment verifier. Return JSON with passed, errors, and warnings.",
                json.dumps({
                    "claims": [{"id": c.id, "text": c.claim_text} for c in claims if c.id in claim_ids],
                    "item": raw,
                    "checks": ["factual support", "single unambiguous answer", "answer consistency", "age appropriateness"],
                }),
            ).payload
            # `passed` comes back in whatever shape the model chose — sometimes a bool,
            # sometimes a list of per-check results — and a non-empty list is truthy even when
            # `errors` is simultaneously full of real objections. Recording that as a pass
            # writes "verifier approved" beside the verifier's own complaint, which is the
            # weak-report failure `item_clears_every_gate` exists to refuse. Require both.
            verifier_passed = bool(verify_payload.get("passed")) and not verify_payload.get("errors")
            report["independent_verifier"] = verify_payload

            # Semantic leakage check: block if an embedding near-duplicate exists (when an
            # embedding model is configured; otherwise the report records "not_configured").
            embedder = provider.embed if getattr(provider, "embeddings_configured", False) else None
            similarity_report = build_similarity_report(
                db, str(raw.get("stem", "")), choices, embed=embedder
            )
            emb = similarity_report.get("embedding_check")
            embedding_blocked = isinstance(emb, dict) and emb.get("outcome") == "blocked"
            if embedding_blocked:
                report.setdefault("errors", []).append("embedding_near_duplicate")

            report["passed"] = bool(
                report["passed"] and solver_ok and verifier_passed and not embedding_blocked
            )
            question = Question(
                event_id=event.id,
                concept_id=concept.id if concept else None,
                source_id=source.id,
                status=QuestionStatus.MACHINE_VALIDATED.value if report["passed"] else QuestionStatus.DRAFT.value,
                question_type="single_choice",
                stem=str(raw.get("stem", "")),
                choices=choices,
                answer_spec=answer_spec,
                explanation=str(raw.get("explanation", "")),
                citations=[{"source_id": source.id, "claim_id": cid} for cid in claim_ids],
                difficulty=difficulty,
                cognitive_level=cognitive_level,
                estimated_seconds=int(raw.get("estimated_seconds", 90)),
                validation_report=report,
                similarity_report=similarity_report,
                generation_provenance={
                    "provider": generated.provider,
                    "model": generated.model,
                    "prompt_version": PROMPT_VERSION,
                    "generation_run_id": run.id,
                    "claim_ids": claim_ids,
                },
            )
            db.add(question)
            db.flush()
            results.append(question)
        run.status = "completed"
        run.result_json = {"question_ids": [q.id for q in results], "count": len(results)}
        db.commit()
        for question in results:
            db.refresh(question)
        return results
    except Exception as exc:
        run.status = "failed"
        run.result_json = {"error": str(exc)}
        db.commit()
        raise
