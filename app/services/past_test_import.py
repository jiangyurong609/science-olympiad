"""Parse a downloaded past test (a Source's extracted PDF text) into structured
Question rows, then assemble them into a takeable mock Exam.

The heavy lifting — segmenting the raw PDF text into items, aligning an answer
key, classifying question type, flagging items that need an image we don't have —
is done by the configured LLM (OpenAICompatibleProvider). Imported questions are
DRAFT/practice, clearly marked in generation_provenance as import_kind="past_test".
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Event, Exam, ExamItem, Question, QuestionStatus, Source, SourceSnapshot,
)
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

MAX_TEXT_CHARS = 30_000
PROMPT_VERSION = "past-test-parse-v1"

FEEDBACK_MODES = {"after_submit", "per_question"}

_SYSTEM = (
    "You parse Science Olympiad practice tests into structured assessment items. "
    "You are given the raw extracted text of a test, and optionally its answer key. "
    "Return STRICT JSON of the form {\"items\": [ ... ]}. Each item is one smallest "
    "answerable unit and has fields: "
    "section (string|null, e.g. 'Station A' or 'Section A'), "
    "label (string, the item's number/letter as printed, e.g. '1' or '2b'), "
    "stem (string, the full cleaned question text; expand it so it is answerable on "
    "its own), "
    "question_type (one of 'single_choice','short_answer','numeric'), "
    "choices (array of strings; [] unless it is genuinely multiple choice), "
    "correct_index (integer index into choices, or null), "
    "reference_answer (string; the official answer from the key or clearly stated in "
    "the text; '' if unknown), "
    "accepted (array of acceptable answer strings/synonyms; may be []), "
    "acceptance_notes (string; rubric guidance like 'accept >= 5 solar masses'; '' if "
    "none), "
    "points (number; default 1), "
    "image_dependent (boolean; true if the item cannot be answered without a specific "
    "image, specimen, illustration, or figure that is not reproduced in the text). "
    "Rules: never invent answers you cannot support from the provided text/key; "
    "preserve the printed numbering; do not copy long verbatim passages beyond the "
    "question wording; output only the JSON object."
)


def _normalize(text: str) -> str:
    # pypdf frequently doubles inter-word spaces; collapse runs of whitespace.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _latest_snapshot(db: Session, source_id: int) -> SourceSnapshot | None:
    return db.scalar(select(SourceSnapshot).where(
        SourceSnapshot.source_id == source_id
    ).order_by(SourceSnapshot.created_at.desc(), SourceSnapshot.id.desc()))


def parse_items(exam_text: str, key_text: str, event: Event) -> list[dict]:
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise ModelProviderError("External model provider is not configured")
    user = json.dumps({
        "event": event.name,
        "division": event.division,
        "test_text": _normalize(exam_text)[:MAX_TEXT_CHARS],
        "answer_key_text": _normalize(key_text)[:MAX_TEXT_CHARS] if key_text else "",
    })
    result = provider.generate_json(_SYSTEM, user)
    items = result.payload.get("items", [])
    if not isinstance(items, list) or not items:
        raise ModelProviderError("Model returned no items")
    return items


def _safe_points(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0


def _answer_spec(item: dict) -> tuple[str, list, dict]:
    """Return (question_type, choices, answer_spec) compatible with scoring.score_response."""
    points = _safe_points(item.get("points"))
    choices = [str(c) for c in (item.get("choices") or [])]
    qtype = item.get("question_type") or "short_answer"
    correct_index = item.get("correct_index")
    if qtype == "single_choice" and choices and isinstance(correct_index, int):
        return "single_choice", choices, {
            "correct_index": correct_index, "points": points, "distractor_error_types": {},
        }
    reference = str(item.get("reference_answer") or "").strip()
    accepted = [str(a).strip() for a in (item.get("accepted") or []) if str(a).strip()]
    if qtype == "numeric":
        try:
            value = float(reference)
            return "numeric", [], {
                "answer": value, "tolerance": max(abs(value) * 0.01, 1e-6), "points": points,
            }
        except (TypeError, ValueError):
            pass  # fall through to short_answer when the reference is not a clean number
    return "short_answer", [], {
        "answer": reference, "accepted": accepted, "points": points,
        "rubric": str(item.get("acceptance_notes") or ""),
    }


def build_questions(
    db: Session, event: Event, exam_source: Source, key_source: Source | None,
    items: list[dict], include_image_dependent: bool = False,
) -> list[Question]:
    questions: list[Question] = []
    for item in items:
        image_dependent = bool(item.get("image_dependent"))
        if image_dependent and not include_image_dependent:
            continue
        stem = str(item.get("stem") or "").strip()
        if not stem:
            continue
        qtype, choices, answer_spec = _answer_spec(item)
        question = Question(
            event_id=event.id,
            source_id=exam_source.id,
            status=QuestionStatus.DRAFT.value,
            question_type=qtype,
            stem=stem,
            choices=choices,
            answer_spec=answer_spec,
            explanation=str(item.get("acceptance_notes") or item.get("reference_answer") or ""),
            citations=[{"source_id": exam_source.id}],
            difficulty=0.5,
            cognitive_level="application",
            estimated_seconds=int(_safe_points(item.get("points"))) * 60,
            generation_provenance={
                "import_kind": "past_test",
                "prompt_version": PROMPT_VERSION,
                "exam_source_id": exam_source.id,
                "key_source_id": key_source.id if key_source else None,
                "section": item.get("section"),
                "label": item.get("label"),
                "image_dependent": image_dependent,
                "unverified_auto_import": True,
            },
        )
        db.add(question)
        db.flush()
        questions.append(question)
    return questions


def _snapshot(question: Question) -> dict:
    return {
        "stem": question.stem,
        "choices": question.choices,
        "assets": question.assets,
        "question_type": question.question_type,
        "answer_spec": question.answer_spec,
        "explanation": question.explanation,
        "citations": question.citations,
        "concept_id": question.concept_id,
        "estimated_seconds": question.estimated_seconds,
    }


def build_exam(
    db: Session, event: Event, exam_source: Source, questions: list[Question],
    feedback_mode: str, title: str | None = None, duration_minutes: int = 50,
) -> Exam:
    if feedback_mode not in FEEDBACK_MODES:
        raise ValueError(f"feedback_mode must be one of {sorted(FEEDBACK_MODES)}")
    exam = Exam(
        event_id=event.id,
        title=title or f"{event.name} — Past Test: {exam_source.title}",
        duration_minutes=duration_minutes,
        question_ids=[q.id for q in questions],
        published=True,
        release_class="past_test",
        blueprint={
            "import_kind": "past_test",
            "feedback_mode": feedback_mode,
            "exam_source_id": exam_source.id,
            "question_count": len(questions),
            "snapshot_schema": 1,
        },
    )
    db.add(exam)
    db.flush()
    for position, question in enumerate(questions):
        db.add(ExamItem(
            exam_id=exam.id, question_id=question.id, question_version=question.version,
            position=position, snapshot=_snapshot(question),
        ))
    return exam


def import_past_test(
    db: Session, event: Event, exam_source: Source, key_source: Source | None = None,
    feedback_mode: str = "after_submit", include_image_dependent: bool = False,
    build: bool = True, commit: bool = True, min_questions: int = 1,
) -> dict:
    """Parse a past-test Source into Questions and (optionally) assemble a mock Exam."""
    exam_snapshot = _latest_snapshot(db, exam_source.id)
    if not exam_snapshot or not (exam_snapshot.extracted_text or "").strip():
        raise ValueError(f"Source {exam_source.id} has no retained text to parse")
    key_snapshot = _latest_snapshot(db, key_source.id) if key_source else None
    key_text = (key_snapshot.extracted_text if key_snapshot else "") or ""

    items = parse_items(exam_snapshot.extracted_text, key_text, event)
    image_dependent = sum(1 for i in items if i.get("image_dependent"))

    questions = build_questions(
        db, event, exam_source, key_source, items, include_image_dependent,
    )
    if len(questions) < min_questions:
        db.rollback()
        return {
            "parsed_items": len(items), "image_dependent_items": image_dependent,
            "questions_created": 0, "exam_id": None, "skipped": True, "items": items,
        }
    exam = build_exam(db, event, exam_source, questions, feedback_mode) if (build and questions) else None
    if commit:
        db.commit()
        if exam:
            db.refresh(exam)
    else:
        db.rollback()
    return {
        "parsed_items": len(items),
        "image_dependent_items": image_dependent,
        "questions_created": len(questions),
        "exam_id": exam.id if exam else None,
        "items": items,
    }
