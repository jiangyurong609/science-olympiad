import hashlib
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import (
    Attempt, AttemptStatus, AttemptSubmission, ExamItem, RemediationCase, Response,
    ResponseRevision,
)

_ARTICLE_RE = re.compile(r"^(the|a|an)\s+")

# An EXTERNAL figure the student must see (not merely the word "figure" — a
# historical figure, a codon chart they know — which would wrongly exclude
# answerable questions from scoring).
_EXTERNAL_FIG_RE = re.compile(
    r"\bimages?\s+\d"
    r"|\b(?:the|this|following|each|above|below)\s+"
    r"(?:figure|diagram|graph|chart|map|image|illustration|photo|photograph|picture)\b"
    r"|\b(?:figure|diagram|graph|chart|map|image|illustration)\s*\d"
    r"|\b(?:figure|diagram|graph|image|photo|picture)\s+(?:above|below|shown|to the)"
    r"|shown\s+(?:above|below|here|in the)"
    r"|\bpictured\b|\bdepicted (?:above|below|here|in)"
    r"|based on the (?:figure|image|graph|map|diagram|table|chart|data|picture)"
    r"|use the (?:figure|image|graph|map|diagram|table)", re.I)

# A specimen letter labelled at a station, e.g. "specimen A".
_SPECIMEN_REF_RE = re.compile(r"[Ss]pecimen\s+([A-Z])\b")
# A specimen DEFINED inline: "specimen A, basalt," or "Specimen A is shale and
# specimen B is conglomerate". Captures a 1-2 word name, stopping before a
# conjunction/verb so "A is shale and B..." doesn't swallow the rest.
_SPECIMEN_DEF_RE = re.compile(
    r"[Ss]pecimen\s+([A-Z])\s*(?:,|:|=|\s+is)\s+"
    r"([A-Za-z][a-z\-]{2,}(?:\s+(?!and\b|but\b|or\b|is\b|which\b|the\b|as\b|from\b|to\b|at\b|indicate\b|shows?\b)[a-z\-]{2,})?)")


def specimen_definitions(stem: str) -> dict[str, str]:
    """Letter -> specimen name for specimens the stem names inline."""
    return {m.group(1).upper(): m.group(2).strip().lower()
            for m in _SPECIMEN_DEF_RE.finditer(stem or "")}


def references_figure(stem: str) -> bool:
    """Whether a stem points at any figure or labelled specimen at all."""
    return bool(_EXTERNAL_FIG_RE.search(stem or "") or _SPECIMEN_REF_RE.search(stem or ""))


def is_figure_missing(stem: str, assets) -> bool:
    """Whether a question can't be answered because a figure it needs is absent.
    A question that NAMES its specimens inline ("Specimen A is shale") is
    answerable from the text and is NOT missing — even without the photo."""
    if assets:
        return False
    stem = stem or ""
    if _EXTERNAL_FIG_RE.search(stem):
        return True  # depends on a diagram/graph/image we don't have
    referenced = set(_SPECIMEN_REF_RE.findall(stem))
    if not referenced:
        return False
    return bool(referenced - set(specimen_definitions(stem)))  # any undefined specimen?


def is_servable(question_type: str, answer_spec: dict, stem: str, assets) -> bool:
    """A question is servable in a NEW exam only if it can be graded and isn't
    missing a figure it depends on."""
    return is_gradeable(question_type, answer_spec) and not is_figure_missing(stem, assets)


def normalize_answer(value) -> str:
    """Normalize a free-text answer for tolerant matching: lowercase, collapse
    whitespace, drop a leading article, and trim trailing punctuation."""
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return _ARTICLE_RE.sub("", text).strip(" .,;:!?")


def answer_key_set(answer_spec: dict) -> set[str]:
    """Normalized set of acceptable short-answer keys. Empty => no reference
    answer exists, so the item is UNGRADEABLE (cannot be scored either way)."""
    ref = normalize_answer(answer_spec.get("answer", ""))
    accepted = [normalize_answer(v) for v in (answer_spec.get("accepted") or [])]
    return {k for k in [ref, *accepted] if k}


def is_gradeable(question_type: str, answer_spec: dict) -> bool:
    """Whether an item can be auto-scored at all. Used by both the scorer and
    the mock-exam assembler so ungradeable items are never scored OR served."""
    answer_spec = answer_spec or {}
    if question_type == "single_choice":
        return isinstance(answer_spec.get("correct_index"), int)
    if question_type == "numeric":
        try:
            float(answer_spec.get("answer"))
            return True
        except (TypeError, ValueError):
            return False
    return bool(answer_key_set(answer_spec))


def score_response(question, answer: dict) -> tuple[bool, float, dict]:
    points = float(question.answer_spec.get("points", 1))
    if question.question_type == "single_choice":
        correct_index = question.answer_spec.get("correct_index")
        if not isinstance(correct_index, int):
            return False, 0.0, {"error_type": "ungradeable", "gradeable": False}
        selected = answer.get("selected_index")
        correct = selected == correct_index
        distractor_map = question.answer_spec.get("distractor_error_types", {})
        error_type = None if correct else distractor_map.get(str(selected), "knowledge_or_reasoning")
        return correct, points if correct else 0.0, {
            "error_type": error_type, "expected": correct_index, "selected": selected}
    if question.question_type == "numeric":
        try:
            expected = float(question.answer_spec.get("answer"))
        except (TypeError, ValueError):
            return False, 0.0, {"error_type": "ungradeable", "gradeable": False}
        tolerance = float(question.answer_spec.get("tolerance", 0))
        try:
            actual = float(answer.get("value"))
        except (TypeError, ValueError):
            return False, 0.0, {"error_type": "numeric_format", "expected": expected}
        correct = abs(actual - expected) <= tolerance
        return correct, points if correct else 0.0, {
            "error_type": None if correct else "calculation_or_unit",
            "expected": expected, "actual": actual, "tolerance": tolerance,
        }
    # short_answer / free text
    keys = answer_key_set(question.answer_spec)
    if not keys:  # no reference answer — cannot be graded either way
        return False, 0.0, {"error_type": "ungradeable", "gradeable": False}
    actual = normalize_answer(answer.get("text", ""))
    if not actual:  # a blank answer is NEVER correct, regardless of the key
        return False, 0.0, {"error_type": "blank",
                            "expected": question.answer_spec.get("answer", "")}
    # exact normalized match, or the answer is the key followed by qualifying
    # words ("extrusive rock" satisfies key "extrusive"). Anchored at the start
    # so a bare substring can't match — "not igneous" must NOT satisfy "igneous",
    # and "excellent" must NOT satisfy "cell".
    correct = actual in keys or any(len(k) >= 4 and actual.startswith(k + " ") for k in keys)
    return correct, points if correct else 0.0, {
        "error_type": None if correct else "response_mismatch",
        "expected": question.answer_spec.get("answer", ""),
    }


def _question_from_snapshot(item: ExamItem):
    snapshot = item.snapshot
    return SimpleNamespace(
        id=item.question_id,
        concept_id=snapshot.get("concept_id"),
        stem=snapshot["stem"],
        question_type=snapshot["question_type"],
        answer_spec=snapshot["answer_spec"],
        explanation=snapshot.get("explanation", ""),
        citations=snapshot.get("citations", []),
    )


def finalize_attempt(
    db: Session, attempt: Attempt, submission_kind: str = "system",
    overrides: dict | None = None,
) -> Attempt:
    items = db.scalars(
        select(ExamItem).where(ExamItem.exam_id == attempt.exam_id).order_by(ExamItem.position)
    ).all()
    responses = db.scalars(select(Response).where(Response.attempt_id == attempt.id)).all()
    submission = db.scalar(select(AttemptSubmission).where(
        AttemptSubmission.attempt_id == attempt.id
    ))
    if not submission:
        manifest = []
        for response in sorted(responses, key=lambda row: row.question_id):
            revision = db.scalar(select(ResponseRevision).where(
                ResponseRevision.response_id == response.id
            ).order_by(ResponseRevision.sequence_number.desc(), ResponseRevision.id.desc()))
            manifest.append({
                "question_id": response.question_id,
                "response_id": response.id,
                "revision_id": revision.id if revision else None,
                "sequence_number": response.sequence_number,
                "content_hash": revision.content_hash if revision else hashlib.sha256(json.dumps({
                    "answer": response.answer, "confidence": response.confidence,
                    "time_spent_seconds": response.time_spent_seconds,
                    "sequence_number": response.sequence_number,
                }, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            })
        manifest_hash = hashlib.sha256(json.dumps(
            manifest, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        db.add(AttemptSubmission(
            attempt_id=attempt.id, submission_kind=submission_kind,
            response_manifest=manifest, manifest_hash=manifest_hash,
        ))
        db.flush()
    response_by_q = {r.question_id: r for r in responses}
    score = 0.0
    max_score = 0.0
    incorrect = 0
    for item in items:
        q = _question_from_snapshot(item)
        response = response_by_q.get(q.id)
        if response is None:
            response = Response(attempt_id=attempt.id, question_id=q.id, answer={})
            db.add(response)
        if overrides and q.id in overrides:
            correct, points, diagnostic = overrides[q.id]
        else:
            correct, points, diagnostic = score_response(q, response.answer or {})
        # An ungradeable item (no reference answer / no correct option) OR one
        # that depends on a figure we couldn't reproduce is not counted for or
        # against the student and is never rendered as "wrong": it stays out of
        # the score, the max score, and the Error Notebook. Gradeability is read
        # from the question itself (NOT the diagnostic) so the LLM-override path
        # can't accidentally grade an item the deterministic path would exclude.
        figure_missing = bool((item.snapshot or {}).get("figure_missing"))
        if not is_gradeable(q.question_type, q.answer_spec) or figure_missing:
            response.is_correct = None
            response.points_awarded = 0.0
            response.diagnostic = {**diagnostic, "figure_missing": True} if figure_missing else diagnostic
            continue
        max_score += float(q.answer_spec.get("points", 1))
        response.is_correct = correct
        response.points_awarded = points
        response.diagnostic = diagnostic
        score += points
        if not correct:
            incorrect += 1
            # A blank/unanswered question is a skip, not a misconception to
            # remediate — don't flood the Error Notebook when a student submits
            # an exam with questions left empty.
            if not response.answer:
                continue
            existing = db.scalar(
                select(RemediationCase).where(
                    RemediationCase.attempt_id == attempt.id,
                    RemediationCase.question_id == q.id,
                )
            )
            if not existing:
                db.add(
                    RemediationCase(
                        attempt_id=attempt.id,
                        user_id=attempt.user_id,
                        question_id=q.id,
                        concept_id=q.concept_id,
                        source_type="exam",
                        source_ref=f"exam:{attempt.id}:{q.id}",
                        error_type=diagnostic.get("error_type") or "unknown",
                        diagnosis={
                            "question_stem": q.stem,
                            "student_answer": response.answer,
                            "correct_answer": q.answer_spec,
                            "confidence": response.confidence,
                            "evidence": diagnostic,
                        },
                        plan={
                            "steps": [
                                "Explain your original approach",
                                "Review the targeted concept explanation",
                                "Retry with guided hints",
                                "Complete a near-transfer question",
                                "Complete an unseen delayed-review question",
                            ],
                            "explanation": q.explanation,
                            "citations": q.citations,
                            "resolution_requires": "unseen_transfer_item",
                        },
                    )
                )
    now = datetime.now(timezone.utc)
    attempt.score = score
    attempt.max_score = max_score
    attempt.submitted_at = now
    attempt.time_spent_seconds = max(0, int((now - _aware(attempt.started_at)).total_seconds()))
    attempt.status = AttemptStatus.REMEDIATION_OPEN.value if incorrect else AttemptStatus.REMEDIATION_COMPLETE.value
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
