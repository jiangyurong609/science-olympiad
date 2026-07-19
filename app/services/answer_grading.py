"""LLM-based grading for short-answer responses.

Multiple-choice / numeric questions stay on the deterministic scorer
(scoring.score_response). Short-answer questions have rubric-style keys
("accept >= 5 solar masses", synonyms, equivalent phrasings) that exact-match
grades poorly, so we grade them with the configured model — batched into few
calls, and always with a deterministic fallback if the model is unavailable.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Attempt, ExamItem, Response
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider
from app.services.scoring import is_gradeable, score_response

BATCH_SIZE = 25

_SYSTEM = (
    "You are a strict but fair Science Olympiad grader. For each item, decide whether "
    "the student's answer is correct given the reference answer and any acceptance "
    "rubric. Award full credit (credit=1.0, verdict='correct') for correct synonyms, "
    "equivalent phrasings, correct scientific names, or numeric values within a stated "
    "acceptable range. Use verdict='partial' with 0<credit<1 only when the item's rubric "
    "clearly allows partial credit. Blank or off-topic answers are 'incorrect' (credit=0). "
    "Do not reward answers that merely restate the question. Return STRICT JSON: "
    "{\"grades\":[{\"id\":<int>,\"verdict\":\"correct\"|\"partial\"|\"incorrect\",\"credit\":<0..1>,"
    "\"rationale\":\"<one short sentence>\"}]}"
)


def grade_batch(items: list[dict]) -> dict[int, dict]:
    """items: [{id, question, reference_answer, accepted, rubric, student_answer}].
    Returns {id: {verdict, credit, rationale}}. Raises ModelProviderError if no model."""
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise ModelProviderError("No external model provider is configured")
    graded: dict[int, dict] = {}
    for start in range(0, len(items), BATCH_SIZE):
        chunk = items[start:start + BATCH_SIZE]
        payload = provider.generate_json(_SYSTEM, json.dumps({"items": chunk})).payload
        grades = payload.get("grades", []) if isinstance(payload, dict) else payload
        for grade in (grades if isinstance(grades, list) else []):
            try:
                graded[int(grade["id"])] = grade
            except (KeyError, TypeError, ValueError):
                continue
    return graded


def _override_from_grade(grade: dict, reference: str, max_points: float) -> tuple[bool, float, dict]:
    verdict = grade.get("verdict", "incorrect")
    try:
        credit = max(0.0, min(1.0, float(grade.get("credit", 1.0 if verdict == "correct" else 0.0))))
    except (TypeError, ValueError):
        credit = 1.0 if verdict == "correct" else 0.0
    correct = verdict == "correct"
    diagnostic = {
        "error_type": None if correct else "response_mismatch",
        "grader": "llm",
        "verdict": verdict,
        "rationale": str(grade.get("rationale", ""))[:500],
        "expected": reference,
    }
    return correct, round(credit * max_points, 3), diagnostic


def _short_answer_items(db: Session, attempt: Attempt) -> list[dict]:
    """One row per short-answer question, tagged with a POSITIONAL id (0..N-1) so
    grading does not depend on the model echoing raw DB question_ids."""
    items = db.scalars(select(ExamItem).where(
        ExamItem.exam_id == attempt.exam_id
    ).order_by(ExamItem.position)).all()
    responses = {r.question_id: r for r in db.scalars(select(Response).where(
        Response.attempt_id == attempt.id
    )).all()}
    rows = []
    for item in items:
        snapshot = item.snapshot
        if snapshot.get("question_type") != "short_answer":
            continue
        spec = snapshot.get("answer_spec", {}) or {}
        if not is_gradeable("short_answer", spec):
            continue  # no reference answer — finalize excludes it; don't waste an LLM call
        response = responses.get(item.question_id)
        student = (response.answer or {}).get("text", "") if response else ""
        reference = str(spec.get("answer", ""))
        rows.append({
            "question_id": item.question_id,
            "max_points": float(spec.get("points", 1)),
            "reference": reference,
            "payload": {
                "id": len(rows),
                "question": str(snapshot.get("stem", ""))[:600],
                "reference_answer": reference,
                "accepted": spec.get("accepted", []),
                "rubric": spec.get("rubric", ""),
                "student_answer": str(student)[:600],
            },
        })
    return rows


def grade_attempt_overrides(db: Session, attempt: Attempt) -> dict[int, tuple[bool, float, dict]]:
    """Grade every short-answer response in an attempt with the LLM and return
    {question_id: (correct, points, diagnostic)} to feed finalize_attempt(overrides=...).
    Raises ModelProviderError if the model is unavailable — caller falls back to
    deterministic scoring."""
    rows = _short_answer_items(db, attempt)
    if not rows:
        return {}
    graded = grade_batch([row["payload"] for row in rows])
    overrides: dict[int, tuple[bool, float, dict]] = {}
    for position, row in enumerate(rows):
        grade = graded.get(position)
        if grade:
            overrides[row["question_id"]] = _override_from_grade(
                grade, row["reference"], row["max_points"],
            )
    return overrides


def grade_single(item_snapshot: dict, student_answer: dict) -> tuple[bool, float, dict]:
    """Grade one saved answer. LLM for short_answer (deterministic fallback);
    deterministic for everything else."""
    if item_snapshot.get("question_type") != "short_answer":
        question = _question_from_snapshot_like(item_snapshot)
        return score_response(question, student_answer or {})
    spec = item_snapshot.get("answer_spec", {}) or {}
    max_points = float(spec.get("points", 1))
    reference = str(spec.get("answer", ""))
    payload = {
        "id": 0,
        "question": str(item_snapshot.get("stem", ""))[:600],
        "reference_answer": reference,
        "accepted": spec.get("accepted", []),
        "rubric": spec.get("rubric", ""),
        "student_answer": str((student_answer or {}).get("text", ""))[:600],
    }
    try:
        graded = grade_batch([payload])
        grade = graded.get(0)
        if grade:
            return _override_from_grade(grade, reference, max_points)
    except ModelProviderError:
        pass
    question = _question_from_snapshot_like(item_snapshot)
    return score_response(question, student_answer or {})


def _question_from_snapshot_like(snapshot: dict):
    from types import SimpleNamespace
    return SimpleNamespace(
        question_type=snapshot.get("question_type"),
        answer_spec=snapshot.get("answer_spec", {}),
    )
