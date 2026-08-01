"""Phase 4 — a release must pin what shipped, and a rollback must restore it.

Before this, publishing flipped `course.status` and wrote an audit line. Nothing recorded the
membership, so `release_missing` could never clear and a rollback moved a version pointer over
content that had already changed underneath it.
"""
from __future__ import annotations

import itertools

import pytest

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Course, CourseUnit, Event, Lesson, LessonSkill, LessonVersion, Question, Skill, User,
)
from app.services.content_release import (
    ReleaseError, build_manifest, publish_release, release_drift, rollback_release,
)

_UNIQUE = itertools.count(1)


def _course(db, *, lessons=1):
    n = next(_UNIQUE)
    event = Event(slug=f"ev-{n}", name="Event", division="B", season=2026)
    db.add(event); db.flush()
    course = Course(event_id=event.id, slug=f"course-{n}", title="Course",
                    status="draft", current_version=1)
    db.add(course); db.flush()
    unit = CourseUnit(course_id=course.id, slug=f"u-{n}", title="Unit", sequence=1)
    db.add(unit); db.flush()
    concept = Concept(event_id=event.id, name=f"Concept {n}")
    db.add(concept); db.flush()
    skill = Skill(course_id=course.id, unit_id=unit.id, concept_id=concept.id,
                  slug=f"s-{n}", name="Skill", sequence=1)
    db.add(skill); db.flush()
    for index in range(lessons):
        lesson = Lesson(event_id=event.id, slug=f"l-{n}-{index}", title=f"Lesson {index}",
                        status="published", current_version=1, sequence=index)
        db.add(lesson); db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1,
                             content=[{"type": "opening"}, {"type": "summary"}]))
        db.add(LessonSkill(lesson_id=lesson.id, skill_id=skill.id))
    db.flush()
    actor = User(email=f"editor-{n}@example.com", full_name="Editor",
                 password_hash="x", role="editor")
    db.add(actor); db.flush()
    return course, actor, skill, event


def test_a_release_pins_lesson_versions_not_just_ids():
    """An id alone does not pin content — the lesson can be edited afterwards."""
    with SessionLocal() as db:
        course, actor, _, _ = _course(db, lessons=2)
        manifest = build_manifest(db, course)
        assert manifest["counts"]["lessons"] == 2
        assert all("version" in row for row in manifest["lessons"])
        assert manifest["digest"]


def test_publishing_creates_the_release_audit_course_looks_for():
    with SessionLocal() as db:
        course, actor, _, _ = _course(db)
        release = publish_release(db, actor, course, notes="first")
        db.commit()
        assert release.status == "published"
        assert release.manifest["digest"]
        assert release.published_by_user_id == actor.id


def test_publishing_the_same_content_twice_is_idempotent():
    with SessionLocal() as db:
        course, actor, _, _ = _course(db)
        first = publish_release(db, actor, course)
        second = publish_release(db, actor, course)
        assert first.id == second.id, "an unchanged republish must not fork the release"


def test_republishing_changed_content_under_one_version_is_refused():
    """Membership is immutable; silently rewriting it would make the digest a lie."""
    with SessionLocal() as db:
        course, actor, skill, event = _course(db)
        publish_release(db, actor, course)
        extra = Lesson(event_id=event.id, slug="extra", title="Extra",
                       status="published", current_version=1, sequence=9)
        db.add(extra); db.flush()
        db.add(LessonVersion(lesson_id=extra.id, version=1, content=[{"type": "opening"}]))
        db.add(LessonSkill(lesson_id=extra.id, skill_id=skill.id))
        db.flush()
        with pytest.raises(ReleaseError, match="immutable"):
            publish_release(db, actor, course)


def test_only_one_release_is_active_at_a_time():
    with SessionLocal() as db:
        course, actor, _, _ = _course(db)
        first = publish_release(db, actor, course)
        course.current_version = 2
        second = publish_release(db, actor, course)
        db.flush()
        assert first.status == "superseded"
        assert second.status == "published"


def test_rollback_restores_the_previous_release_and_version():
    with SessionLocal() as db:
        course, actor, _, _ = _course(db)
        first = publish_release(db, actor, course)
        course.current_version = 2
        second = publish_release(db, actor, course)
        db.flush()

        restored = rollback_release(db, actor, course)
        assert restored.id == first.id
        assert course.current_version == first.version
        assert second.status == "rolled_back"
        assert restored.status == "published"


def test_rollback_without_history_is_refused_not_guessed():
    with SessionLocal() as db:
        course, actor, _, _ = _course(db)
        publish_release(db, actor, course)
        with pytest.raises(ReleaseError, match="no superseded release"):
            rollback_release(db, actor, course)


def test_drift_detects_content_edited_after_release():
    """A published release whose lessons have since changed means the catalog is serving
    something nobody approved under a version that says otherwise."""
    with SessionLocal() as db:
        course, actor, _, _ = _course(db)
        publish_release(db, actor, course)
        db.flush()
        assert release_drift(db, course)["drifted"] is False

        lesson = db.query(Lesson).filter(Lesson.slug.like("l-%")).first()
        db.add(LessonVersion(lesson_id=lesson.id, version=2, content=[{"type": "opening"}]))
        lesson.current_version = 2
        db.flush()

        drift = release_drift(db, course)
        assert drift["drifted"] is True
        assert any("lesson versions changed" in change for change in drift["changes"])


def test_an_empty_course_cannot_be_released():
    with SessionLocal() as db:
        course, actor, _, _ = _course(db, lessons=0)
        with pytest.raises(ReleaseError, match="at least one lesson"):
            publish_release(db, actor, course)


def test_a_lesson_missing_its_current_version_fails_the_release_loudly():
    with SessionLocal() as db:
        course, actor, _, _ = _course(db)
        lesson = db.query(Lesson).filter(Lesson.slug.like("l-%")).first()
        lesson.current_version = 99          # points at a row that does not exist
        db.flush()
        with pytest.raises(ReleaseError, match="no row for its current version"):
            build_manifest(db, course)


def test_renaming_a_lesson_changes_the_digest():
    """Caught by rehearsing on real content, not by these fixtures.

    The manifest pinned id, slug, version and status but not the title, so renaming a lesson
    left the digest identical: republishing was accepted and drift reported nothing, while
    what a student sees had changed. The earlier immutability test only ever *added* a lesson,
    which changes the count and would have passed either way.
    """
    with SessionLocal() as db:
        course, actor, _, _ = _course(db)
        publish_release(db, actor, course)
        before = release_drift(db, course)
        assert before["drifted"] is False

        lesson = db.query(Lesson).filter(Lesson.slug.like("l-%")).first()
        lesson.title = f"{lesson.title} — renamed"
        db.flush()

        assert release_drift(db, course)["drifted"] is True
        with pytest.raises(ReleaseError, match="immutable"):
            publish_release(db, actor, course)


def test_every_served_lesson_field_is_pinned():
    """A field the manifest omits is a change the release can never notice."""
    with SessionLocal() as db:
        course, actor, _, _ = _course(db)
        row = build_manifest(db, course)["lessons"][0]
    for field in ("id", "slug", "title", "version", "status", "estimated_minutes"):
        assert field in row, f"{field} is served but not pinned"


# --------------------------------------------- rollback must restore content, not a pointer

def _served_lesson_state(db, lesson_id):
    """What a student read resolves: lesson.current_version, not the manifest."""
    lesson = db.get(Lesson, lesson_id)
    return (lesson.current_version, lesson.title, lesson.status)


def test_rollback_restores_the_lesson_version_a_student_actually_reads():
    """The finding that made the Phase 4 gate false.

    Rollback moved `course.current_version` and marked a prior manifest active, and stopped.
    Student lesson reads resolve `lesson.current_version`, so a lesson edited to v2 kept being
    served after rolling back to release v1 — the audit record said one thing and the product
    served another.
    """
    with SessionLocal() as db:
        course, actor, _, _ = _course(db)
        lesson = db.query(Lesson).filter(Lesson.slug.like("l-%")).first()
        before = _served_lesson_state(db, lesson.id)
        publish_release(db, actor, course, notes="v1")

        # edit the lesson the way a content change really happens, and release again
        db.add(LessonVersion(lesson_id=lesson.id, version=2,
                             content=[{"type": "opening"}, {"type": "summary"}]))
        lesson.current_version = 2
        lesson.title = "Rewritten"
        db.flush()
        course.current_version = 2
        publish_release(db, actor, course, notes="v2")
        db.flush()
        assert _served_lesson_state(db, lesson.id) != before

        rollback_release(db, actor, course)
        db.flush()

        assert _served_lesson_state(db, lesson.id) == before, \
            "rollback must restore what is served, not only the course pointer"


def test_rollback_withdraws_items_published_after_the_release():
    """An item published after release v1 was never part of it."""
    with SessionLocal() as db:
        course, actor, skill, event = _course(db)
        publish_release(db, actor, course, notes="v1")

        later = Question(event_id=event.id, concept_id=skill.concept_id, stem="Added later",
                         question_type="single_choice", choices=["a", "b"],
                         answer_spec={"correct_index": 0}, status="published")
        db.add(later); db.flush()
        course.current_version = 2
        publish_release(db, actor, course, notes="v2")
        db.flush()

        rollback_release(db, actor, course)
        db.flush()
        assert db.get(Question, later.id).status != "published", \
            "an item that was not in the restored release must not stay published"


def test_rollback_reports_what_it_could_not_restore():
    """A lesson deleted since the release cannot be brought back by moving a pointer, and
    silently succeeding would recreate the false confidence this fix removes."""
    from app.services.content_release import restore_from_manifest
    with SessionLocal() as db:
        course, actor, _, _ = _course(db)
        manifest = build_manifest(db, course)
        manifest["lessons"].append({"id": 999_999, "slug": "gone", "title": "Gone",
                                    "version": 1, "status": "published"})
        result = restore_from_manifest(db, manifest)
    assert result["unrestorable"], "a missing lesson must be reported, not ignored"
    assert "999999" in result["unrestorable"][0]
