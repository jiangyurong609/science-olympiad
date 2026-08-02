"""A course in preview must not make unreviewed lessons readable.

Phase 0's invariant is that unreviewed content is not servable. The lesson list honoured it
only when the course was *not* in `student_preview`; in preview it widened from "published"
to "every non-withdrawn lesson", drafts included. Moving the pilot into preview to fix an
unrelated inconsistency put 24 unreviewed lessons in front of students.
"""
from __future__ import annotations

import itertools

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Course, Event, Lesson, LessonVersion, ReviewDecision, User,
)

_UNIQUE = itertools.count(1)


def _course_with_lessons(db, course_status):
    n = next(_UNIQUE)
    event = Event(slug=f"vis-ev-{n}", name="E", division="B", season=2026)
    db.add(event); db.flush()
    course = Course(event_id=event.id, slug=f"vis-course-{n}", title="C",
                    status=course_status)
    db.add(course); db.flush()
    reviewer = db.scalar(select(User).where(User.role.in_(("editor", "admin"))))
    if reviewer is None:
        reviewer = User(email=f"vis-reviewer-{n}@example.com", full_name="Reviewer",
                        password_hash="x", role="editor")
        db.add(reviewer); db.flush()
    for status in ("published", "draft"):
        lesson = Lesson(event_id=event.id, slug=f"vis-{status}-{n}",
                        title=f"{status.title()} lesson {n}", status=status,
                        current_version=1)
        db.add(lesson); db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1, content=[]))
        if status == "published":
            # a published lesson is only student-visible once review evidence exists; the
            # gate fails closed, which is the behaviour worth preserving
            for stage in ("editor", "sme"):
                db.add(ReviewDecision(
                    entity_type="lesson", entity_id=lesson.id, entity_version=1,
                    stage=stage, decision="approved",
                    reviewer_user_id=reviewer.id))
    db.commit()
    return event.id, n


@pytest.mark.parametrize("course_status", ["student_preview", "published", "draft"])
def test_a_student_never_sees_a_draft_lesson(client, student_token, course_status):
    with SessionLocal() as db:
        event_id, n = _course_with_lessons(db, course_status)
    rows = client.get(f"/api/events/{event_id}/lessons",
                      headers={"Authorization": f"Bearer {student_token}"}).json()
    titles = {r["title"] for r in (rows if isinstance(rows, list) else rows.get("lessons", []))}
    assert f"Published lesson {n}" in titles
    assert f"Draft lesson {n}" not in titles, \
        f"a draft lesson leaked to a student with course status {course_status!r}"


def test_a_published_lesson_without_review_evidence_stays_hidden(client, student_token):
    """The gate fails closed: publication alone is not evidence of review."""
    with SessionLocal() as db:
        n = next(_UNIQUE)
        event = Event(slug=f"vis-noreview-{n}", name="E", division="B", season=2026)
        db.add(event); db.flush()
        db.add(Course(event_id=event.id, slug=f"vis-nr-{n}", title="C",
                      status="student_preview"))
        db.flush()
        lesson = Lesson(event_id=event.id, slug=f"vis-nr-lesson-{n}",
                        title=f"Unreviewed but published {n}", status="published",
                        current_version=1)
        db.add(lesson); db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1, content=[]))
        db.commit()
        event_id = event.id

    rows = client.get(f"/api/events/{event_id}/lessons",
                      headers={"Authorization": f"Bearer {student_token}"}).json()
    titles = {r["title"] for r in (rows if isinstance(rows, list) else rows.get("lessons", []))}
    assert f"Unreviewed but published {n}" not in titles


def test_staff_still_see_drafts(client, admin_token):
    with SessionLocal() as db:
        event_id, n = _course_with_lessons(db, "student_preview")
    rows = client.get(f"/api/events/{event_id}/lessons",
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    titles = {r["title"] for r in (rows if isinstance(rows, list) else rows.get("lessons", []))}
    assert f"Draft lesson {n}" in titles, "review is impossible if staff cannot see drafts"


def test_video_is_gated_the_same_way_the_lesson_text_is(client, student_token):
    """Video was gated on `lesson.status` alone while the text required review evidence —
    a weaker rule for the same content, so a lesson refused as text could be watched."""
    with SessionLocal() as db:
        n = next(_UNIQUE)
        event = Event(slug=f"vid-ev-{n}", name="E", division="B", season=2026)
        db.add(event); db.flush()
        db.add(Course(event_id=event.id, slug=f"vid-c-{n}", title="C", status="published"))
        lesson = Lesson(event_id=event.id, slug=f"vid-l-{n}", title="Unreviewed",
                        status="published", current_version=1)
        db.add(lesson); db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1, content=[]))
        db.commit()
        lesson_id = lesson.id

    headers = {"Authorization": f"Bearer {student_token}"}
    assert client.get(f"/api/lessons/{lesson_id}/videos", headers=headers).status_code == 404


def test_staff_can_still_fetch_video_for_an_unreviewed_lesson(client, admin_token):
    """Reviewing a render in context requires being able to load it."""
    with SessionLocal() as db:
        n = next(_UNIQUE)
        event = Event(slug=f"vid-staff-{n}", name="E", division="B", season=2026)
        db.add(event); db.flush()
        db.add(Course(event_id=event.id, slug=f"vid-sc-{n}", title="C", status="draft"))
        lesson = Lesson(event_id=event.id, slug=f"vid-sl-{n}", title="Draft",
                        status="draft", current_version=1)
        db.add(lesson); db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1, content=[]))
        db.commit()
        lesson_id = lesson.id

    response = client.get(f"/api/lessons/{lesson_id}/videos",
                          headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200


def test_a_grandfather_does_not_survive_a_content_rewrite():
    """`unreviewed_practice` records that someone decided to expose *this* lesson. Eight pilot
    lessons kept theirs through a split that cut them to "Part 1 of N" and left model-written
    blocks behind, so students were served rewritten content under an exemption nobody granted
    for it."""
    from app.models.entities import User as U
    from app.services import student_visibility as sv

    with SessionLocal() as db:
        n = next(_UNIQUE)
        event = Event(slug=f"gf-ev-{n}", name="E", division="B", season=2026)
        db.add(event); db.flush()
        lesson = Lesson(event_id=event.id, slug=f"gf-l-{n}", title="Legacy",
                        status="published", current_version=1,
                        disposition="unreviewed_practice", disposition_version=1)
        db.add(lesson); db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1, content=[]))
        db.flush()
        student = U(id=-1, email="p@x", full_name="P", role="student")
        assert sv.lesson_is_student_visible(db, student, lesson) is True

        # the lesson is rewritten; the decision was not made about this content
        db.add(LessonVersion(lesson_id=lesson.id, version=2, content=[]))
        lesson.current_version = 2
        db.flush()
        assert sv.lesson_is_student_visible(db, student, lesson) is False


def test_a_legacy_disposition_with_no_recorded_version_still_applies():
    """Rows predating the column were granted about the content as it stood; withdrawing them
    would hide legitimately grandfathered lessons without anyone deciding to."""
    from app.models.entities import User as U
    from app.services import student_visibility as sv

    with SessionLocal() as db:
        n = next(_UNIQUE)
        event = Event(slug=f"gf-old-{n}", name="E", division="B", season=2026)
        db.add(event); db.flush()
        lesson = Lesson(event_id=event.id, slug=f"gf-ol-{n}", title="Legacy",
                        status="published", current_version=3,
                        disposition="unreviewed_practice", disposition_version=None)
        db.add(lesson); db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=3, content=[]))
        db.flush()
        student = U(id=-1, email="p@x", full_name="P", role="student")
        assert sv.lesson_is_student_visible(db, student, lesson) is True
