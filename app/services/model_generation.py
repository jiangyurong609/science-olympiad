from __future__ import annotations
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import Concept, Event, GenerationRun, Question, QuestionStatus, ScientificClaim, Source, User
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider
from app.services.rights import can_use_for_generation
from app.services.validation import build_similarity_report, validate_candidate

PROMPT_VERSION = "competition-item-v1"


def _grounding_context(db: Session, concept: Concept | None) -> tuple[Source, list[ScientificClaim]]:
    stmt = select(ScientificClaim).where(
        ScientificClaim.approved.is_(True), ScientificClaim.source_snapshot_id.is_not(None)
    )
    if concept:
        stmt = stmt.where((ScientificClaim.concept_id == concept.id) | (ScientificClaim.concept_id.is_(None)))
    claims = db.scalars(stmt.limit(8)).all()
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
    source, claims = _grounding_context(db, concept)
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise ModelProviderError("External model provider is not configured")
    claim_text = "\n".join(f"- [{c.id}] {c.claim_text}" for c in claims)
    system = (
        "You create original Science Olympiad-style practice items. Use only the approved claims. "
        "Do not copy known competition wording. Return strict JSON with an items array. Each item must "
        "contain stem, four choices, correct_index, explanation, claim_ids, estimated_seconds, and "
        "distractor_error_types keyed by choice index."
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
            # Independent verifier pass; failure keeps the item in draft.
            verify_payload = provider.generate_json(
                "Act as an independent scientific and assessment verifier. Return JSON with passed, errors, and warnings.",
                json.dumps({
                    "claims": [{"id": c.id, "text": c.claim_text} for c in claims if c.id in claim_ids],
                    "item": raw,
                    "checks": ["factual support", "single unambiguous answer", "answer consistency", "age appropriateness"],
                }),
            ).payload
            verifier_passed = bool(verify_payload.get("passed"))
            report["independent_verifier"] = verify_payload
            report["passed"] = bool(report["passed"] and verifier_passed)
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
                similarity_report=build_similarity_report(db, str(raw.get("stem", "")), choices),
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
