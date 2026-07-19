"""Generate original practice questions grounded in a downloaded material.

Unlike past_test_import (which extracts questions that already exist in a sample
test), this creates NEW multiple-choice questions from a reference material's
extracted text (rules manual, handout, reference doc) using the configured model.
Generated questions are DRAFT/practice, flagged unverified_auto_import, and are
single_choice so they auto-score deterministically.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Event, Question, QuestionStatus, Source, SourceSnapshot
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

MAX_TEXT_CHARS = 20_000
PROMPT_VERSION = "material-mcq-v1"

_SYSTEM = (
    "You write original multiple-choice practice questions for a Science Olympiad event, "
    "grounded ONLY in the provided source text (a rules manual, handout, or reference). "
    "Return STRICT JSON {\"items\": [ {stem, choices, correct_index, explanation, difficulty, "
    "cognitive_level} ]}. Rules: exactly 4 choices; exactly one unambiguous correct option with "
    "plausible distractors; the question and answer must be supported by the source text; "
    "difficulty is 0..1; cognitive_level is one of 'recall','application','analysis'; do NOT "
    "copy long verbatim passages; do NOT say 'according to the passage'; cover different "
    "subtopics across the set. Output only the JSON object."
)


def _latest_snapshot(db: Session, source_id: int) -> SourceSnapshot | None:
    return db.scalar(select(SourceSnapshot).where(
        SourceSnapshot.source_id == source_id
    ).order_by(SourceSnapshot.created_at.desc(), SourceSnapshot.id.desc()))


def generate_from_material(
    db: Session, event: Event, source: Source, count: int = 15,
    max_chars: int = MAX_TEXT_CHARS, commit: bool = True,
) -> list[Question]:
    snapshot = _latest_snapshot(db, source.id)
    text = (snapshot.extracted_text if snapshot else "") or ""
    if len(text.strip()) < 500:
        raise ValueError(f"Source {source.id} has too little text to generate from")
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise ModelProviderError("External model provider is not configured")
    user = json.dumps({
        "event": event.name,
        "division": event.division,
        "count": count,
        "source_title": source.title,
        "source_text": text[:max_chars],
    })
    payload = provider.generate_json(_SYSTEM, user).payload
    items = payload.get("items", [])
    if not isinstance(items, list) or not items:
        raise ModelProviderError("Model returned no items")

    questions: list[Question] = []
    for item in items[:count]:
        choices = [str(c) for c in (item.get("choices") or [])]
        correct = item.get("correct_index")
        if len(choices) < 2 or not isinstance(correct, int) or not (0 <= correct < len(choices)):
            continue
        stem = str(item.get("stem") or "").strip()
        if not stem:
            continue
        try:
            difficulty = min(1.0, max(0.0, float(item.get("difficulty", 0.5))))
        except (TypeError, ValueError):
            difficulty = 0.5
        question = Question(
            event_id=event.id,
            source_id=source.id,
            status=QuestionStatus.DRAFT.value,
            question_type="single_choice",
            stem=stem,
            choices=choices,
            answer_spec={"correct_index": correct, "points": 1, "distractor_error_types": {}},
            explanation=str(item.get("explanation") or ""),
            citations=[{"source_id": source.id}],
            difficulty=difficulty,
            cognitive_level=str(item.get("cognitive_level") or "application"),
            estimated_seconds=75,
            generation_provenance={
                "import_kind": "generated_from_material",
                "prompt_version": PROMPT_VERSION,
                "source_id": source.id,
                "unverified_auto_import": True,
            },
        )
        db.add(question)
        db.flush()
        questions.append(question)
    if commit:
        db.commit()
        for question in questions:
            db.refresh(question)
    return questions
