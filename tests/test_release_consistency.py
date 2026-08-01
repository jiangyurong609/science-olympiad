"""A course must not claim to be published while serving nothing.

Moving the pilot's lessons to draft for review left the course still marked `published`, so a
student navigating to it would have been shown an empty course — which reads as a broken
product rather than an honest "in review". Nothing detected that, because publication status
and lesson status were never compared.
"""
from __future__ import annotations

import itertools

from app.core.database import SessionLocal
from app.models.entities import (
    ContentRelease, Course, CourseUnit, Event, Lesson, LessonSkill, LessonVersion, Skill,
)
from scripts.audit_release_consistency import rows

_UNIQUE = itertools.count(1)


def _course(db, *, course_status="published", lesson_status="published", lessons=1,
            with_release=False):
    n = next(_UNIQUE)
    event = Event(slug=f"ev-rc-{n}", name="E", division="B", season=2026)
    db.add(event); db.flush()
    course = Course(event_id=event.id, slug=f"course-rc-{n}", title="C",
                    status=course_status, current_version=1)
    db.add(course); db.flush()
    unit = CourseUnit(course_id=course.id, slug=f"u{n}", title="U", sequence=1)
    db.add(unit); db.flush()
    skill = Skill(course_id=course.id, unit_id=unit.id, slug=f"s{n}", name="S", sequence=1)
    db.add(skill); db.flush()
    for index in range(lessons):
        lesson = Lesson(event_id=event.id, slug=f"l{n}-{index}", title="L",
                        status=lesson_status, current_version=1)
        db.add(lesson); db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1, content=[]))
        db.add(LessonSkill(lesson_id=lesson.id, skill_id=skill.id))
    if with_release:
        db.add(ContentRelease(course_id=course.id, version=1, status="published",
                              manifest={"digest": "d"}))
    db.flush()
    return course


def _row_for(db, course):
    return next(r for r in rows(db) if r["slug"] == course.slug)


def test_a_published_course_with_only_draft_lessons_is_flagged():
    with SessionLocal() as db:
        course = _course(db, course_status="published", lesson_status="draft")
        assert "published_but_serves_nothing" in _row_for(db, course)["problems"]


def test_a_published_course_with_a_published_lesson_is_not_flagged_for_emptiness():
    with SessionLocal() as db:
        course = _course(db, course_status="published", lesson_status="published",
                         with_release=True)
        assert _row_for(db, course)["problems"] == []


def test_a_draft_course_with_draft_lessons_is_consistent():
    """A course that does not claim to be published is not lying about anything."""
    with SessionLocal() as db:
        course = _course(db, course_status="draft", lesson_status="draft")
        assert _row_for(db, course)["problems"] == []


def test_a_published_course_without_a_release_is_flagged_separately():
    with SessionLocal() as db:
        course = _course(db, course_status="published", lesson_status="published",
                         with_release=False)
        problems = _row_for(db, course)["problems"]
        assert problems == ["published_without_a_release"], \
            "it serves lessons, so only the missing release is wrong"


def test_the_two_problems_are_reported_independently():
    with SessionLocal() as db:
        course = _course(db, course_status="published", lesson_status="draft",
                         with_release=False)
        problems = set(_row_for(db, course)["problems"])
        assert problems == {"published_but_serves_nothing", "published_without_a_release"}
