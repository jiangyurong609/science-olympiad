"""A gap ledger that only grows records what was once missing, not what is missing.

`record_block_gaps` opened a ContentGap for any skill with unsupported blocks and never
revisited it: skills that had since been grounded were skipped by a `continue`, and existing
descriptions were never refreshed. On the pilot the records claimed 33 unsupported blocks
while 9 actually were, and `content_gap` could never clear however much grounding improved.
"""
from __future__ import annotations

import itertools

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, ContentGap, Course, CourseUnit, Event, Lesson, LessonSkill, LessonVersion,
    ScientificClaim, Skill, Source, SourceSnapshot,
)
from scripts.ground_event import record_block_gaps

_UNIQUE = itertools.count(1)


def _fixture(db, *, blocks):
    n = next(_UNIQUE)
    event = Event(slug=f"gap-ev-{n}", name="E", division="B", season=2026)
    db.add(event); db.flush()
    course = Course(event_id=event.id, slug=f"gap-course-{n}", title="C", status="draft")
    db.add(course); db.flush()
    unit = CourseUnit(course_id=course.id, slug=f"gu{n}", title="U", sequence=1)
    db.add(unit); db.flush()
    concept = Concept(event_id=event.id, name=f"C{n}")
    db.add(concept); db.flush()
    skill = Skill(course_id=course.id, unit_id=unit.id, concept_id=concept.id,
                  slug=f"gs{n}", name="S", sequence=1)
    db.add(skill); db.flush()
    lesson = Lesson(event_id=event.id, slug=f"gl{n}", title="Lesson",
                    status="draft", current_version=1)
    db.add(lesson); db.flush()
    db.add(LessonVersion(lesson_id=lesson.id, version=1, content=blocks))
    db.add(LessonSkill(lesson_id=lesson.id, skill_id=skill.id))
    db.flush()
    return event, course, skill, lesson


def _gaps(db, course):
    return db.query(ContentGap).filter(ContentGap.course_id == course.id).all()


def test_an_unsupported_block_opens_a_gap():
    with SessionLocal() as db:
        event, course, _, _ = _fixture(db, blocks=[{"type": "summary"}])
        record_block_gaps(db, event, apply=True)
        db.flush()
        gaps = _gaps(db, course)
    assert len(gaps) == 1
    assert gaps[0].status == "open"


def test_a_gap_is_resolved_once_its_blocks_cite_claims():
    """The defect: a skill that had been grounded was skipped, so its gap stayed open."""
    with SessionLocal() as db:
        event, course, _, lesson = _fixture(db, blocks=[{"type": "summary"}])
        record_block_gaps(db, event, apply=True)
        db.flush()
        assert _gaps(db, course)[0].status == "open"

        version = db.query(LessonVersion).filter(
            LessonVersion.lesson_id == lesson.id).first()
        version.content = [{"type": "summary", "claim_ids": [1]}]
        db.flush()
        record_block_gaps(db, event, apply=True)
        db.flush()
        gaps = _gaps(db, course)

    assert len(gaps) == 1, "resolving must not fork a second record"
    assert gaps[0].status == "resolved"


def test_a_resolved_gap_reopens_if_the_grounding_is_lost():
    with SessionLocal() as db:
        event, course, _, lesson = _fixture(
            db, blocks=[{"type": "summary", "claim_ids": [1]}])
        record_block_gaps(db, event, apply=True)
        db.flush()

        version = db.query(LessonVersion).filter(
            LessonVersion.lesson_id == lesson.id).first()
        version.content = [{"type": "summary"}]          # claim removed again
        db.flush()
        record_block_gaps(db, event, apply=True)
        db.flush()
        gaps = _gaps(db, course)

    assert len(gaps) == 1
    assert gaps[0].status == "open", "the ledger must track the present, not a past decision"


def test_the_description_reports_the_current_count_not_the_original():
    """The records said 33 unsupported blocks while 9 were; only `resolution_notes` was ever
    refreshed, and the audit and the operator both read `description`."""
    with SessionLocal() as db:
        event, course, _, lesson = _fixture(
            db, blocks=[{"type": "summary"}, {"type": "steps"}, {"type": "opening"}])
        record_block_gaps(db, event, apply=True)
        db.flush()
        assert _gaps(db, course)[0].description.startswith("3 teaching block")

        version = db.query(LessonVersion).filter(
            LessonVersion.lesson_id == lesson.id).first()
        version.content = [{"type": "summary", "claim_ids": [1]},
                           {"type": "steps", "claim_ids": [1]},
                           {"type": "opening"}]
        db.flush()
        record_block_gaps(db, event, apply=True)
        db.flush()
        description = _gaps(db, course)[0].description

    assert description.startswith("1 teaching block"), description


def test_a_dry_run_changes_nothing():
    with SessionLocal() as db:
        event, course, _, _ = _fixture(db, blocks=[{"type": "summary"}])
        record_block_gaps(db, event, apply=False)
        db.flush()
        assert _gaps(db, course) == []
