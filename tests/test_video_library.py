"""Phase V — how chapter videos reach students and reviewers."""
from __future__ import annotations

import pytest

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, VideoRender, VideoStoryboard
from app.services import video_library as vl


@pytest.fixture(autouse=True)
def _fake_signing(monkeypatch):
    """Playback URLs are minted from GCS; tests must not need a bucket."""
    monkeypatch.setattr(vl.media_storage, "playback_url", lambda key, **kw: f"https://signed/{key}")


def _seed(db, *, chapters, lesson_status="published"):
    event = Event(slug="ecology", name="Ecology", division="C", season=2026)
    db.add(event); db.flush()
    lesson = Lesson(event_id=event.id, slug="energy", title="Energy Flow", status=lesson_status)
    db.add(lesson); db.flush()
    board = VideoStoryboard(
        lesson_id=lesson.id, lesson_version=1, event_id=event.id, version=1,
        title="Energy Flow", status="approved",
        scenes=[{"chapter": c["title"], "narration": "n"} for c in chapters],
    )
    db.add(board); db.flush()
    for c in chapters:
        db.add(VideoRender(
            storyboard_id=board.id, version=c.get("version", 1), chapter=c["key"],
            status=c.get("status", "succeeded"), qa_status=c.get("qa", vl.QA_PENDING),
            duration_seconds=c.get("duration", 30.0),
            video_key=f"video/{c['key']}-v{c.get('version',1)}.mp4",
            provenance={"chapter_title": c["title"], "scenes": 3},
        ))
    db.commit()
    return lesson.id, board.id


def test_students_only_see_qa_approved_chapters():
    with SessionLocal() as db:
        lesson_id, _ = _seed(db, chapters=[
            {"key": "foundations", "title": "Foundations", "qa": vl.QA_APPROVED},
            {"key": "efficiency", "title": "Efficiency", "qa": vl.QA_PENDING},
            {"key": "rejected-one", "title": "Rejected", "qa": vl.QA_REJECTED},
        ])
        student_view = vl.lesson_chapters(db, lesson_id)
        staff_view = vl.lesson_chapters(db, lesson_id, include_pending=True)

    assert [c["chapter"] for c in student_view] == ["foundations"]
    assert len(staff_view) == 3, "staff can see pending work in context"
    assert student_view[0]["playback_url"].startswith("https://")


def test_only_the_newest_render_of_a_chapter_is_shown():
    with SessionLocal() as db:
        lesson_id, _ = _seed(db, chapters=[
            {"key": "foundations", "title": "Foundations", "qa": vl.QA_APPROVED, "version": 1},
            {"key": "foundations", "title": "Foundations", "qa": vl.QA_APPROVED, "version": 3},
        ])
        chapters = vl.lesson_chapters(db, lesson_id)
    assert len(chapters) == 1
    assert chapters[0]["version"] == 3, "a re-render supersedes the older one for viewers"


def test_failed_renders_are_never_watchable():
    with SessionLocal() as db:
        lesson_id, _ = _seed(db, chapters=[
            {"key": "broken", "title": "Broken", "qa": vl.QA_APPROVED, "status": "failed"},
        ])
        assert vl.lesson_chapters(db, lesson_id, include_pending=True) == []


def test_chapters_follow_storyboard_order_not_database_order():
    with SessionLocal() as db:
        lesson_id, _ = _seed(db, chapters=[
            {"key": "a", "title": "Foundations", "qa": vl.QA_APPROVED},
            {"key": "b", "title": "Efficiency", "qa": vl.QA_APPROVED},
            {"key": "c", "title": "Consequences", "qa": vl.QA_APPROVED},
        ])
        titles = [c["title"] for c in vl.lesson_chapters(db, lesson_id)]
    assert titles == ["Foundations", "Efficiency", "Consequences"]


def test_lesson_without_a_storyboard_returns_nothing():
    with SessionLocal() as db:
        event = Event(slug="e", name="E", division="C", season=2026)
        db.add(event); db.flush()
        lesson = Lesson(event_id=event.id, slug="l", title="L", status="published")
        db.add(lesson); db.commit()
        assert vl.lesson_chapters(db, lesson.id) == []


# ---------------------------------------------------------------- QA

def test_review_queue_lists_pending_renders_with_context():
    with SessionLocal() as db:
        _seed(db, chapters=[{"key": "foundations", "title": "Foundations"}])
        queue = vl.review_queue(db)
    assert len(queue) == 1
    assert queue[0]["lesson_title"] == "Energy Flow"
    assert queue[0]["playback_url"].startswith("https://")


def test_approving_makes_a_chapter_watchable():
    with SessionLocal() as db:
        lesson_id, _ = _seed(db, chapters=[{"key": "foundations", "title": "Foundations"}])
        assert vl.lesson_chapters(db, lesson_id) == []
        render_id = db.scalars(vl.select(VideoRender)).first().id
        vl.record_qa(db, render_id, vl.QA_APPROVED, [], user_id=1)
        db.commit()
        assert len(vl.lesson_chapters(db, lesson_id)) == 1


def test_rejection_requires_a_note_explaining_what_to_fix():
    with SessionLocal() as db:
        _seed(db, chapters=[{"key": "foundations", "title": "Foundations"}])
        render_id = db.scalars(vl.select(VideoRender)).first().id
        with pytest.raises(vl.VideoLibraryError, match="requires at least one note"):
            vl.record_qa(db, render_id, vl.QA_REJECTED, [], user_id=1)

        render = vl.record_qa(db, render_id, vl.QA_REJECTED,
                              [{"scene": 2, "at_seconds": 12.5, "note": "caption drifts"}], user_id=7)
        db.commit()
        assert render.qa_status == vl.QA_REJECTED
        assert render.qa_notes[0]["at_seconds"] == 12.5
        assert render.qa_notes[0]["by_user_id"] == 7


def test_invalid_decision_and_unreviewable_render_are_refused():
    with SessionLocal() as db:
        _seed(db, chapters=[{"key": "c", "title": "C", "status": "failed"}])
        render_id = db.scalars(vl.select(VideoRender)).first().id
        with pytest.raises(vl.VideoLibraryError, match="decision must be"):
            vl.record_qa(db, render_id, "maybe", [], user_id=1)
        with pytest.raises(vl.VideoLibraryError, match="cannot review"):
            vl.record_qa(db, render_id, vl.QA_APPROVED, [], user_id=1)


# ---------------------------------------------------------------- API

def test_video_endpoints_enforce_roles(client, student_token, admin_token, monkeypatch):
    monkeypatch.setattr(
        "app.services.video_library.media_storage.playback_url", lambda key, **kw: f"https://signed/{key}"
    )
    with SessionLocal() as db:
        lesson_id, _ = _seed(db, chapters=[{"key": "foundations", "title": "Foundations"}])

    # a student cannot reach the review queue
    assert client.get("/api/content/video-renders",
                      headers={"Authorization": f"Bearer {student_token}"}).status_code == 403
    # ...and sees no chapters until QA approves one
    body = client.get(f"/api/lessons/{lesson_id}/videos",
                      headers={"Authorization": f"Bearer {student_token}"}).json()
    assert body["chapters"] == []

    queue = client.get("/api/content/video-renders",
                       headers={"Authorization": f"Bearer {admin_token}"}).json()
    render_id = queue["renders"][0]["render_id"]
    approved = client.post(f"/api/content/video-renders/{render_id}/qa",
                           json={"decision": "approved", "notes": []},
                           headers={"Authorization": f"Bearer {admin_token}"})
    assert approved.status_code == 200 and approved.json()["qa_status"] == "approved"

    body = client.get(f"/api/lessons/{lesson_id}/videos",
                      headers={"Authorization": f"Bearer {student_token}"}).json()
    assert len(body["chapters"]) == 1 and body["available"] is True


def test_unchaptered_render_is_labelled_full_lesson():
    """Renders made before chaptering have no chapter key; they must not show a blank title."""
    with SessionLocal() as db:
        lesson_id, board_id = _seed(db, chapters=[{"key": "", "title": "", "qa": vl.QA_APPROVED}])
        render = db.scalars(vl.select(VideoRender)).first()
        render.provenance = {}
        db.commit()
        chapters = vl.lesson_chapters(db, lesson_id)
    assert chapters[0]["title"] == "Full lesson"
