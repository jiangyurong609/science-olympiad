from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Exam, ExamItem, Lesson, LessonVersion, PracticeSet, PracticeSetVersion, Question,
    ScientificClaim, Source,
)


HIGH_IMPACT_TERMS = re.compile(
    r"\b(rule|correction|clarification|required|prohibited|formula|unit|safety|deadline|season)\b",
    re.IGNORECASE,
)


def _normalized(value: str) -> str:
    return " ".join(value.split())


def classify_source_change(previous_text: str, current_text: str) -> tuple[str, dict]:
    previous = _normalized(previous_text)
    current = _normalized(current_text)
    if previous == current:
        return "cosmetic", {
            "similarity": 1.0,
            "previous_characters": len(previous),
            "current_characters": len(current),
            "high_impact_terms": [],
        }
    similarity = SequenceMatcher(None, previous, current).ratio()
    terms = sorted({match.group(0).lower() for match in HIGH_IMPACT_TERMS.finditer(current)})
    return "material", {
        "similarity": round(similarity, 4),
        "previous_characters": len(previous),
        "current_characters": len(current),
        "character_delta": len(current) - len(previous),
        "high_impact_terms": terms,
    }


def quarantine_source_dependents(db: Session, source: Source) -> dict:
    claims = db.scalars(select(ScientificClaim).where(
        ScientificClaim.source_id == source.id
    )).all()
    claim_ids = {claim.id for claim in claims}
    for claim in claims:
        claim.approved = False

    questions = db.scalars(select(Question)).all()
    affected_questions = []
    for question in questions:
        provenance_claims = set((question.generation_provenance or {}).get("claim_ids", []))
        if question.source_id == source.id or claim_ids.intersection(provenance_claims):
            if question.status not in {"withdrawn", "quarantined"}:
                question.status = "quarantined"
            affected_questions.append(question)

    lesson_versions = db.scalars(select(LessonVersion)).all()
    affected_lesson_ids = {
        version.lesson_id for version in lesson_versions
        if claim_ids.intersection(set(version.claim_ids or []))
    }
    lessons = db.scalars(select(Lesson).where(Lesson.id.in_(affected_lesson_ids))).all() \
        if affected_lesson_ids else []
    for lesson in lessons:
        lesson.status = "review_required"

    practice_versions = db.scalars(select(PracticeSetVersion)).all()
    affected_practice_set_ids = {
        version.practice_set_id for version in practice_versions
        if claim_ids.intersection(set(version.claim_ids or []))
    }
    practice_sets = db.scalars(select(PracticeSet).where(
        PracticeSet.id.in_(affected_practice_set_ids)
    )).all() if affected_practice_set_ids else []
    for practice_set in practice_sets:
        practice_set.status = "review_required"

    question_ids = {question.id for question in affected_questions}
    exam_items = db.scalars(select(ExamItem).where(
        ExamItem.question_id.in_(question_ids)
    )).all() if question_ids else []
    exam_ids = {item.exam_id for item in exam_items}
    exams = db.scalars(select(Exam).where(Exam.id.in_(exam_ids))).all() if exam_ids else []
    for exam in exams:
        exam.published = False

    source.metadata_json = {
        **(source.metadata_json or {}),
        "impact_review_pending": True,
    }
    db.flush()
    return {
        "claim_ids": sorted(claim_ids),
        "question_ids": sorted(question_ids),
        "lesson_ids": sorted(affected_lesson_ids),
        "practice_set_ids": sorted(affected_practice_set_ids),
        "exam_ids": sorted(exam_ids),
        "claims_quarantined": len(claim_ids),
        "questions_quarantined": len(question_ids),
        "lessons_quarantined": len(affected_lesson_ids),
        "practice_sets_quarantined": len(affected_practice_set_ids),
        "exams_unpublished": len(exam_ids),
    }
