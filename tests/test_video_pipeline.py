"""Phase V — storyboard gate, EditSpec builder, Deepgram narration, render adapter."""
from __future__ import annotations

import httpx
import pytest

from app.core.database import SessionLocal
from app.models.entities import (
    Event, Lesson, LessonVersion, ScientificClaim, Source, SourceSnapshot, User, VideoRender,
)
from app.core.security import hash_password
import app.services.video_storyboard as sb
from app.services.video_editspec import (
    EditSpecError, build_edit_spec, scene_duration, total_duration, validate_edit_spec,
)
from app.services.tts_deepgram import DeepgramNarrator, DeepgramError, parse_word_timings
from app.services.video_worker import RemotionRenderClient, RenderWorkerError

SLIDE = "https://storage.googleapis.com/bucket/slide-1.png"
VOICE = "https://storage.googleapis.com/bucket/scene-1.mp3"


# ---------------------------------------------------------------- EditSpec

def _scene(**over):
    base = {
        "slide_url": SLIDE, "audio_url": VOICE, "headline": "Energy flows one way",
        "words": [{"text": "Energy", "startSeconds": 0.0, "endSeconds": 0.5},
                  {"text": "flows", "startSeconds": 0.5, "endSeconds": 1.0}],
    }
    base.update(over)
    return base


def test_slide_headline_is_not_duplicated_as_an_overlay():
    """The slide image already shows the headline; an overlay would double it and cover
    the design. Overlays must be opt-in."""
    spec = build_edit_spec([_scene()])
    assert spec["overlays"] == []
    opted_in = build_edit_spec([_scene(overlay=True)])
    assert len(opted_in["overlays"]) == 1


def test_build_edit_spec_shapes_a_valid_document():
    spec = build_edit_spec([_scene(), _scene(headline="Matter cycles")])
    assert spec["version"] == 0
    assert len(spec["clips"]) == 2
    assert spec["clips"][0]["sourceKind"] == "image"
    # second clip gets a transition, first does not
    assert "transitionIn" not in spec["clips"][0]
    assert spec["clips"][1]["transitionIn"]["type"] == "fade"
    assert len(spec["audio"]["voiceover"]) == 2
    assert spec["captions"]["segments"], "captions must be populated from word timings"


def test_scene_duration_follows_narration_length():
    words = [{"text": "a", "startSeconds": 0, "endSeconds": 7.4}]
    assert scene_duration(words) == pytest.approx(8.0, abs=0.01)
    # a scene never collapses below the readable minimum
    assert scene_duration([]) == 2.0


def test_captions_and_voiceover_are_offset_onto_the_timeline():
    spec = build_edit_spec([_scene(), _scene()])
    first_len = spec["clips"][0]["outSeconds"]
    assert spec["audio"]["voiceover"][1]["startSeconds"] == pytest.approx(first_len)
    # second scene's captions start after the first scene, not at zero
    second = [s for s in spec["captions"]["segments"] if s["startSeconds"] >= first_len]
    assert second, "second scene captions must be shifted onto the timeline"
    assert total_duration(spec) == pytest.approx(sum(c["outSeconds"] for c in spec["clips"]))


@pytest.mark.parametrize("bad,msg", [
    ({"slide_url": "/static/slide.png"}, "http"),      # worker cannot read local paths
    ({"slide_url": None}, "http"),
])
def test_non_fetchable_slide_is_rejected(bad, msg):
    with pytest.raises(EditSpecError) as exc:
        build_edit_spec([_scene(**bad)])
    assert msg in str(exc.value)


def test_local_voiceover_path_is_rejected():
    with pytest.raises(EditSpecError):
        build_edit_spec([_scene(audio_url="file:///tmp/a.mp3")])


def test_validate_rejects_empty_clips_and_bad_aspect():
    with pytest.raises(EditSpecError):
        validate_edit_spec({"version": 0, "format": {"aspect": "16:9", "width": 1920, "height": 1080, "fps": 30}, "clips": []})
    with pytest.raises(EditSpecError):
        build_edit_spec([_scene()], fmt={"aspect": "4:3"})


# ---------------------------------------------------------------- Deepgram

def test_parse_word_timings_prefers_punctuated_words():
    payload = {"results": {"channels": [{"alternatives": [{"words": [
        {"word": "energy", "punctuated_word": "Energy,", "start": 0.1, "end": 0.6},
        {"word": "flows", "start": 0.6, "end": 1.0},
    ]}]}]}}
    words = parse_word_timings(payload)
    assert [w["text"] for w in words] == ["Energy,", "flows"]
    assert words[0]["startSeconds"] == 0.1


def test_parse_word_timings_survives_malformed_payload():
    assert parse_word_timings({}) == []
    assert parse_word_timings({"results": {"channels": []}}) == []


def test_narrate_synthesizes_then_aligns(monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        req = httpx.Request("POST", url)
        if "speak" in url:
            return httpx.Response(200, content=b"ID3-audio", request=req)
        return httpx.Response(200, request=req, json={"results": {"channels": [{"alternatives": [
            {"words": [{"word": "hi", "start": 0.0, "end": 0.4}]}]}]}})

    monkeypatch.setattr(httpx, "post", fake_post)
    narrator = DeepgramNarrator(api_key="k")
    result = narrator.narrate("Hello there")
    assert result.audio == b"ID3-audio"
    assert result.words[0]["text"] == "hi"
    assert result.duration == 0.4
    assert any("speak" in c for c in calls) and any("listen" in c for c in calls)


def test_narration_survives_alignment_failure(monkeypatch):
    def fake_post(url, **kw):
        req = httpx.Request("POST", url)
        if "speak" in url:
            return httpx.Response(200, content=b"audio", request=req)
        return httpx.Response(500, text="alignment down", request=req)

    monkeypatch.setattr(httpx, "post", fake_post)
    result = DeepgramNarrator(api_key="k").narrate("Hello")
    assert result.audio == b"audio"
    assert result.words == []  # captions degrade; narration still renders


def test_unconfigured_deepgram_refuses():
    # Clear the key explicitly: constructing with api_key=None falls back to settings, which
    # in a configured environment would make this test hit the real API.
    narrator = DeepgramNarrator(api_key="placeholder")
    narrator.api_key = None
    with pytest.raises(DeepgramError):
        narrator.synthesize("x")
    with pytest.raises(DeepgramError):
        narrator.align(b"audio")


# ---------------------------------------------------------------- render worker

def test_render_posts_spec_with_oidc_and_reads_upload_result(monkeypatch):
    seen = {}

    def fake_post(url, **kw):
        seen["url"] = url
        seen["auth"] = kw["headers"]["Authorization"]
        seen["body"] = kw["json"]
        return httpx.Response(200, request=httpx.Request("POST", url), json={"ok": True, "bytes": 4096})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = RemotionRenderClient(worker_url="https://worker.example.run.app", token="tok")
    spec = build_edit_spec([_scene()])
    result = client.render(spec, upload_url="https://storage.googleapis.com/put-here")
    assert result.ok and result.bytes_written == 4096
    assert seen["url"].endswith("/render/edit-spec")
    assert seen["auth"] == "Bearer tok"
    assert seen["body"]["uploadUrl"].startswith("https://")


def test_render_returns_bytes_when_no_upload_url(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(
        200, content=b"\x00mp4", headers={"content-type": "video/mp4"},
        request=httpx.Request("POST", url)))
    client = RemotionRenderClient(worker_url="https://w.example", token="t")
    result = client.render(build_edit_spec([_scene()]))
    assert result.video == b"\x00mp4"


def test_render_surfaces_worker_errors_and_timeouts(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(403, text="Forbidden", request=httpx.Request("POST", url)))
    client = RemotionRenderClient(worker_url="https://w.example", token="t")
    with pytest.raises(RenderWorkerError, match="403"):
        client.render(build_edit_spec([_scene()]))

    def timeout(url, **kw):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(RenderWorkerError, match="timed out"):
        client.render(build_edit_spec([_scene()]))


def test_render_refuses_invalid_spec_before_spending(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    client = RemotionRenderClient(worker_url="https://w.example", token="t")
    with pytest.raises(EditSpecError):
        client.render({"version": 0, "format": {"aspect": "16:9", "width": 1, "height": 1, "fps": 1}, "clips": []})
    assert called["n"] == 0, "must not call the worker with a spec it would reject"


# ---------------------------------------------------------------- storyboard gate

def _seed_lesson(db, *, approved_claim=True):
    user = User(email="ed@x.com", full_name="Ed", password_hash=hash_password("x"), role="editor")
    event = Event(slug="ecology", name="Ecology", division="C", season=2026)
    db.add_all([user, event])
    db.flush()
    src = Source(url="https://sci.gov/e", title="E", rights_status="public_domain", approved=True)
    db.add(src); db.flush()
    snap = SourceSnapshot(source_id=src.id, final_url=src.url, content_hash="h")
    db.add(snap); db.flush()
    claim = ScientificClaim(source_id=src.id, source_snapshot_id=snap.id,
                            claim_text="Energy flows one way.", approved=approved_claim)
    db.add(claim); db.flush()
    lesson = Lesson(event_id=event.id, slug="energy-flow", title="Energy Flow", status="published")
    db.add(lesson); db.flush()
    db.add(LessonVersion(lesson_id=lesson.id, version=1, content=[
        {"type": "opening", "heading": "Start here"},
        {"type": "property_cards", "heading": "Trophic levels"},
        {"type": "checkpoint", "heading": "not teachable"},
        {"type": "summary", "heading": "Recap"},
    ], claim_ids=[claim.id]))
    db.commit()
    return user.id, lesson.id, claim.id


def test_draft_skips_non_teachable_blocks():
    with SessionLocal() as db:
        _, lesson_id, _ = _seed_lesson(db)
        draft = sb.draft_from_lesson(db, lesson_id)
    kinds = [s["block_type"] for s in draft["scenes"]]
    assert "checkpoint" not in kinds
    assert kinds == ["opening", "property_cards", "summary"]


def test_approval_requires_narration_and_grounding():
    with SessionLocal() as db:
        user_id, lesson_id, claim_id = _seed_lesson(db)
        draft = sb.draft_from_lesson(db, lesson_id)
        board = sb.create_storyboard(db, lesson_id, draft["scenes"])
        db.commit()
        # narration is still empty -> refused
        with pytest.raises(sb.StoryboardError, match="narration is empty"):
            sb.approve_storyboard(db, board.id, user_id)

        board.scenes = [
            {**scene, "narration": "Energy flows one way through the system.",
             "claim_ids": [claim_id]}
            for scene in board.scenes
        ]
        db.commit()
        approved = sb.approve_storyboard(db, board.id, user_id)
        assert approved.status == sb.APPROVED and approved.approved_by_user_id == user_id


def test_ungrounded_narration_blocks_approval():
    with SessionLocal() as db:
        user_id, lesson_id, _ = _seed_lesson(db)
        draft = sb.draft_from_lesson(db, lesson_id)
        for scene in draft["scenes"]:
            scene["narration"] = "An invented fact."
            scene["claim_ids"] = [98765]  # not an approved claim
        board = sb.create_storyboard(db, lesson_id, draft["scenes"])
        db.commit()
        with pytest.raises(sb.StoryboardError, match="unapproved claim"):
            sb.approve_storyboard(db, board.id, user_id)


def test_render_is_blocked_until_storyboard_is_approved():
    with SessionLocal() as db:
        user_id, lesson_id, claim_id = _seed_lesson(db)
        draft = sb.draft_from_lesson(db, lesson_id)
        board = sb.create_storyboard(db, lesson_id, draft["scenes"])
        db.commit()
        with pytest.raises(sb.StoryboardError, match="approve it before rendering"):
            sb.start_render(db, board.id)

        board.scenes = [
            {**scene, "narration": "Energy flows one way.", "claim_ids": [claim_id]}
            for scene in board.scenes
        ]
        db.flush()
        sb.approve_storyboard(db, board.id, user_id)
        render = sb.start_render(db, board.id, spec_hash="abc")
        db.commit()
        assert render.status == "queued" and render.version == 1


def test_regeneration_is_versioned_and_never_overwrites():
    with SessionLocal() as db:
        user_id, lesson_id, claim_id = _seed_lesson(db)
        draft = sb.draft_from_lesson(db, lesson_id)
        for scene in draft["scenes"]:
            scene["narration"] = "Energy flows one way."
            scene["claim_ids"] = [claim_id]
        board = sb.create_storyboard(db, lesson_id, draft["scenes"])
        sb.approve_storyboard(db, board.id, user_id)
        first = sb.start_render(db, board.id, spec_hash="v1")
        second = sb.start_render(db, board.id, spec_hash="v2")
        db.commit()
        assert (first.version, second.version) == (1, 2)
        kept = db.query(VideoRender).filter(VideoRender.storyboard_id == board.id).count()
        assert kept == 2, "prior render must be retained, not replaced"
