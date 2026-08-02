"""Linking a lesson to a mastery concept must not become a way to invent pedagogy.

The script exists because 450 of production's 474 published lessons had no `concept_id`, and
mastery is keyed on one — so finishing them recorded nothing. The risk in fixing that is the
opposite failure: filing lessons under ideas nobody decided they belong to. These pin the line.
"""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Course, CourseUnit, Event, Lesson, LessonSkill, Skill)
from scripts.link_lessons_to_concepts import MARKER, run


def _event(db, slug: str) -> Event:
    event = Event(slug=slug, name=slug, division="B", season=2026)
    db.add(event)
    db.flush()
    return event


def _lesson(db, event, slug: str, title: str) -> Lesson:
    lesson = Lesson(event_id=event.id, slug=slug, title=title, status="published",
                    disposition="unreviewed_practice", current_version=1, sequence=1)
    db.add(lesson)
    db.flush()
    return lesson


def test_an_event_with_authored_concepts_is_left_for_a_human():
    """`ecology` has four real concepts and no lesson title matches any of them.

    Adding a fifth named after a lesson asserts that lesson belongs to none of the four, which
    is a pedagogical claim. Refusing is the whole point.
    """
    with SessionLocal() as db:
        event = _event(db, "ecology-authored")
        db.add(Concept(event_id=event.id, name="Energy flow", description="Real pedagogy"))
        db.flush()
        _lesson(db, event, "foundations", "Foundations of Ecosystems")
        db.commit()

    result = run(apply=True)
    assert result["stats"]["needs_human_mapping"] >= 1
    with SessionLocal() as db:
        lesson = db.scalar(select(Lesson).where(Lesson.slug == "foundations"))
        assert lesson.concept_id is None, "no concept may be assigned by guessing"
        assert db.scalar(select(Concept).where(Concept.name == "Foundations of Ecosystems")) is None


def test_an_event_with_no_concepts_gets_one_per_lesson():
    """Creating a concept where none exists groups nothing and asserts nothing."""
    with SessionLocal() as db:
        event = _event(db, "bare-event")
        for i in range(3):
            _lesson(db, event, f"l{i}", f"Lesson {i}")
        db.commit()
        event_id = event.id

    run(apply=True)
    with SessionLocal() as db:
        lessons = db.scalars(select(Lesson).where(Lesson.event_id == event_id)).all()
        assert all(l.concept_id for l in lessons), (
            "every lesson of a concept-less event must be linked, not just the first — "
            "the script's own creations must not read as pre-existing pedagogy"
        )
        assert len({l.concept_id for l in lessons}) == 3


def test_an_existing_skill_concept_is_followed_rather_than_duplicated():
    with SessionLocal() as db:
        event = _event(db, "linked-event")
        concept = Concept(event_id=event.id, name="Rock cycle", description="Authored")
        db.add(concept)
        db.flush()
        course = Course(event_id=event.id, slug="linked-course", title="Linked", status="draft")
        db.add(course); db.flush()
        unit = CourseUnit(course_id=course.id, slug="u1", title="Unit 1", sequence=1)
        db.add(unit); db.flush()
        skill = Skill(course_id=course.id, unit_id=unit.id, slug="cycle", name="Rock cycle",
                      concept_id=concept.id)
        db.add(skill)
        db.flush()
        lesson = _lesson(db, event, "cycles", "Reading the Rock Cycle")
        db.add(LessonSkill(lesson_id=lesson.id, skill_id=skill.id))
        db.commit()
        concept_id, lesson_id = concept.id, lesson.id

    result = run(apply=True)
    assert result["stats"]["inherit"] >= 1
    with SessionLocal() as db:
        assert db.get(Lesson, lesson_id).concept_id == concept_id


def test_running_twice_changes_nothing_the_second_time():
    """A concept the script created must not make the next run defer to a human."""
    with SessionLocal() as db:
        event = _event(db, "twice-event")
        for i in range(2):
            _lesson(db, event, f"t{i}", f"Twice {i}")
        db.commit()

    run(apply=True)
    with SessionLocal() as db:
        before = len([c for c in db.scalars(select(Concept)).all()
                      if MARKER in (c.description or "")])
    second = run(apply=True)
    with SessionLocal() as db:
        after = len([c for c in db.scalars(select(Concept)).all()
                     if MARKER in (c.description or "")])
    assert before == after, "a re-run must not create a second concept for the same lesson"
    assert second["stats"]["linked"] == 0
