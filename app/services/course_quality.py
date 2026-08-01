"""Machine-checkable course release audit.

Passing structural checks never substitutes for human rights, editor, SME, or
calibration decisions; those are separate blockers in the returned report.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    AssessmentBlueprint, ContentGap, ContentRelease, Course, CourseSourceCoverage,
    CourseUnit, EventSourceMap, Lesson, LessonSkill, LessonVersion, Question,
    QuestionCalibration, QuestionReview, ReviewDecision, ScientificClaim, Skill,
    SourcePassage,
)


TEACHING_TYPES = {"property_cards", "steps", "worked_example", "image_gallery", "video"}

# A student holds the lesson, never the source packet it was written from. A checkpoint asking
# "which statement best follows from the source packet?" or "in the source's 1500 C example…"
# cannot be answered from anything the student has been given — the same defect as a question
# referring to a figure that was never imported. Normal pedagogical voice ("this lesson shows")
# is not this, and is deliberately excluded.
UNAVAILABLE_SOURCE = re.compile(
    r"\b(the source packet|the source's|from the source|according to the source|"
    r"in the source|the provided (?:stations|packet)|the source station)\b", re.I)


def block_text(block: dict) -> str:
    """Every string a block presents, including those nested in lists."""
    parts: list[str] = []

    def walk(node) -> None:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            for key, value in node.items():
                # `superseded` archives the block's previous version so review can diff it.
                # Searching it would keep reporting a defect that has already been repaired,
                # sending a reviewer after a false alarm.
                if key not in {"type", "claim_ids", "passage_ids", "id", "generated_by",
                               "superseded", "repaired_by"}:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(block)
    return " ".join(parts)


def blocks_citing_an_unavailable_source(content: list) -> list[dict]:
    """Blocks that send the student to material they were never given."""
    found = []
    for index, block in enumerate(content or []):
        match = UNAVAILABLE_SOURCE.search(block_text(block))
        if match:
            found.append({
                "position": index + 1,
                "type": block.get("type", ""),
                "heading": block.get("heading") or block.get("title") or "",
                "phrase": match.group(0),
                "assessed": block.get("type") == "checkpoint",
            })
    return found


def audit_course(db: Session, course_id: int) -> dict:
    course = db.get(Course, course_id)
    if not course:
        raise ValueError("course not found")
    units = db.scalars(select(CourseUnit).where(
        CourseUnit.course_id == course.id,
        CourseUnit.status != "withdrawn",
    ).order_by(CourseUnit.sequence)).all()
    skills = db.scalars(select(Skill).where(
        Skill.course_id == course.id,
        Skill.status != "withdrawn",
    ).order_by(Skill.sequence)).all()
    skill_ids = [skill.id for skill in skills]
    links = db.scalars(select(LessonSkill).where(
        LessonSkill.skill_id.in_(skill_ids)
    )).all() if skill_ids else []
    links_by_skill = defaultdict(list)
    for link in links:
        links_by_skill[link.skill_id].append(link)
    lesson_ids = sorted({link.lesson_id for link in links})
    lessons = {
        lesson.id: lesson for lesson in db.scalars(select(Lesson).where(
            Lesson.id.in_(lesson_ids)
        )).all()
    } if lesson_ids else {}
    versions = {}
    if lesson_ids:
        for version in db.scalars(select(LessonVersion).where(
            LessonVersion.lesson_id.in_(lesson_ids)
        )).all():
            lesson = lessons.get(version.lesson_id)
            if lesson and version.version == lesson.current_version:
                versions[lesson.id] = version
    lesson_decisions = db.scalars(select(ReviewDecision).where(
        ReviewDecision.entity_type == "lesson",
        ReviewDecision.entity_id.in_(lesson_ids),
    )).all() if lesson_ids else []
    decisions_by_lesson = defaultdict(set)
    for decision in lesson_decisions:
        lesson = lessons.get(decision.entity_id)
        if (
            lesson and decision.entity_version == lesson.current_version
            and decision.decision == "approved"
        ):
            decisions_by_lesson[decision.entity_id].add(decision.stage)

    concept_ids = [skill.concept_id for skill in skills if skill.concept_id]
    questions = db.scalars(select(Question).where(
        Question.event_id == course.event_id,
        Question.concept_id.in_(concept_ids),
    )).all() if concept_ids else []
    questions_by_concept = defaultdict(list)
    for question in questions:
        questions_by_concept[question.concept_id].append(question)
    question_ids = [question.id for question in questions]
    reviews = db.scalars(select(QuestionReview).where(
        QuestionReview.question_id.in_(question_ids)
    )).all() if question_ids else []
    calibrations = db.scalars(select(QuestionCalibration).where(
        QuestionCalibration.question_id.in_(question_ids)
    )).all() if question_ids else []
    reviews_by_question = defaultdict(set)
    for review in reviews:
        question = next(
            (row for row in questions if row.id == review.question_id), None
        )
        if (
            question and review.question_version == question.version
            and review.decision == "approved"
        ):
            reviews_by_question[review.question_id].add(review.stage)
    calibration_by_question = {
        row.question_id: row for row in calibrations
        if (
            row.decision == "approved"
            and next(
                (
                    question.version for question in questions
                    if question.id == row.question_id
                ),
                None,
            ) == row.question_version
        )
    }
    claims = db.scalars(select(ScientificClaim).where(
        ScientificClaim.skill_id.in_(skill_ids)
    )).all() if skill_ids else []
    passage_ids = {claim.source_passage_id for claim in claims if claim.source_passage_id}
    existing_passage_ids = set(db.scalars(select(SourcePassage.id).where(
        SourcePassage.id.in_(passage_ids)
    )).all()) if passage_ids else set()
    coverage = db.scalars(select(CourseSourceCoverage).where(
        CourseSourceCoverage.course_id == course.id
    )).all()
    expected_source_ids = set(db.scalars(select(EventSourceMap.source_id).where(
        EventSourceMap.event_id == course.event_id
    )).all())
    covered_source_ids = {row.source_id for row in coverage}
    gaps = db.scalars(select(ContentGap).where(
        ContentGap.course_id == course.id
    )).all()
    blueprints = db.scalars(select(AssessmentBlueprint).where(
        AssessmentBlueprint.course_id == course.id
    )).all()
    releases = db.scalars(select(ContentRelease).where(
        ContentRelease.course_id == course.id,
        ContentRelease.status == "published",
    )).all()

    blockers = []

    def block(code: str, entity_type: str, entity_id, detail: str):
        blockers.append({
            "code": code, "entity_type": entity_type,
            "entity_id": entity_id, "detail": detail,
        })

    if not units:
        block("no_units", "course", course.id, "Course has no active units.")
    for unit in units:
        unit_skills = [skill for skill in skills if skill.unit_id == unit.id]
        if not 2 <= len(unit_skills) <= 3:
            block(
                "unit_skill_volume", "unit", unit.id,
                f"Expected 2–3 skills; found {len(unit_skills)}.",
            )
        unit_quizzes = [
            row for row in blueprints
            if row.unit_id == unit.id and row.assessment_type == "unit_quiz"
        ]
        if not unit_quizzes:
            block("unit_quiz_missing", "unit", unit.id, "No unit quiz blueprint.")
        elif not any(row.status == "published" for row in unit_quizzes):
            block("unit_quiz_unpublished", "unit", unit.id, "Unit quiz remains in review.")

    for skill in skills:
        skill_lessons = [
            lessons[link.lesson_id] for link in links_by_skill[skill.id]
            if link.lesson_id in lessons
        ]
        if not skill_lessons:
            block("skill_lesson_missing", "skill", skill.id, "No linked teach lesson.")
        for lesson in skill_lessons:
            version = versions.get(lesson.id)
            if not version:
                block("lesson_version_missing", "lesson", lesson.id, "Current version is missing.")
                continue
            blocks = version.content or []
            checks = [row for row in blocks if row.get("type") == "checkpoint"]
            teaching = [row for row in blocks if row.get("type") in TEACHING_TYPES]
            if not 5 <= lesson.estimated_minutes <= 12:
                block("lesson_duration", "lesson", lesson.id, "Lesson must target 5–12 minutes.")
            if not blocks or blocks[0].get("type") != "opening" or blocks[-1].get("type") != "summary":
                block("lesson_rhythm", "lesson", lesson.id, "Opening or summary is missing.")
            if len(teaching) < 3:
                block("lesson_interactions", "lesson", lesson.id, "Needs at least three teaching interactions.")
            if len(checks) < 3:
                block("lesson_checks", "lesson", lesson.id, "Needs at least three checks.")
            if not any(row.get("cognitive_level") in {"application", "transfer"} for row in checks):
                block("lesson_transfer", "lesson", lesson.id, "Needs an application or transfer check.")
            cited_ids = {
                passage_id for row in blocks for passage_id in row.get("passage_ids", [])
            }
            version_cited_ids = {
                row.get("source_passage_id") for row in (version.citations or [])
                if row.get("source_passage_id")
            }
            if not cited_ids or not cited_ids.issubset(version_cited_ids):
                block("lesson_citations", "lesson", lesson.id, "Block citations are incomplete.")
            if lesson.status != "published":
                block("lesson_unpublished", "lesson", lesson.id, "Lesson remains a draft.")
            if not {"editor", "sme"}.issubset(decisions_by_lesson[lesson.id]):
                block("lesson_review", "lesson", lesson.id, "Editor and SME approvals are required.")

        skill_questions = questions_by_concept[skill.concept_id]
        target = 8 if skill.weight > 1 else 6
        published_questions = [
            question for question in skill_questions if question.status == "published"
        ]
        if len(published_questions) < target:
            block(
                "question_volume", "skill", skill.id,
                f"Needs {target} published questions; found {len(published_questions)}.",
            )
        if not any(question.cognitive_level == "transfer" for question in published_questions):
            block("transfer_item_missing", "skill", skill.id, "No published transfer item.")
        for question in skill_questions:
            if not {"editor", "sme"}.issubset(reviews_by_question[question.id]):
                block("question_review", "question", question.id, "Editor and SME approvals are required.")
            if question.id not in calibration_by_question:
                block("question_calibration", "question", question.id, "Calibration approval is required.")

    for claim in claims:
        if not claim.approved:
            block("claim_unapproved", "claim", claim.id, "Claim has not been approved.")
        if not claim.source_passage_id or claim.source_passage_id not in existing_passage_ids:
            block("claim_passage_missing", "claim", claim.id, "Claim lacks a retained source passage.")
    for source_id in sorted(expected_source_ids - covered_source_ids):
        block("source_unreconciled", "source", source_id, "No course coverage disposition.")
    for row in coverage:
        if row.extraction_status != "extracted":
            block("source_extraction", "source", row.source_id, row.extraction_status)
        if row.review_status != "approved":
            block("source_review", "source", row.source_id, row.review_status)
        if (
            not row.student_destination and not row.withdrawal_reason
            and row.instructional_role not in {"reference_only", "assessment_validation"}
        ):
            block("source_destination", "source", row.source_id, "No student destination or withdrawal.")
    for gap in gaps:
        if gap.status != "resolved":
            block("content_gap", "content_gap", gap.id, f"{gap.gap_type}: {gap.status}")
    if not releases:
        block("release_missing", "course", course.id, "No published atomic content release.")

    return {
        "course_id": course.id,
        "release_ready": not blockers,
        "counts": {
            "units": len(units), "skills": len(skills), "lessons": len(lessons),
            "questions": len(questions), "published_questions": sum(
                row.status == "published" for row in questions
            ),
            "claims": len(claims), "approved_claims": sum(row.approved for row in claims),
            "sources": len(coverage), "open_gaps": sum(row.status != "resolved" for row in gaps),
            "blockers": len(blockers),
        },
        "blocker_counts": dict(Counter(row["code"] for row in blockers)),
        "blockers": blockers,
    }
