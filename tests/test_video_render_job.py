"""Phase V — slide rendering and the end-to-end render job."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.entities import (
    Event, Lesson, LessonVersion, ScientificClaim, Source, SourceSnapshot, User,
)
import app.services.video_storyboard as sb
from app.services.tts_deepgram import Narration
from app.services.video_render_job import (
    narrate_scenes, render_lesson, render_storyboard, spec_fingerprint,
)
from app.services.video_slides import archetype_for, render_scene_svg, render_storyboard as slides_for
from app.services.video_worker import RenderResult


# ------------------------------------------------------------------ slides

def test_every_archetype_emits_well_formed_xml():
    """Slides are consumed by a browser: malformed XML silently breaks the render."""
    import xml.dom.minidom as minidom
    for block in ("opening", "property_cards", "steps", "worked_example",
                  "image_gallery", "summary", "checkpoint"):
        svg = render_scene_svg({
            "index": 1, "block_type": block, "headline": "Energy & flow <in> ecosystems",
            "eyebrow": "Ecology", "subtitle": "sub", "figure_caption": "cap",
            "points": ["First point", "Second & <point>"],
        })
        minidom.parseString(svg)   # raises on malformed markup


def test_slide_is_valid_svg_with_headline_and_points():
    svg = render_scene_svg({
        "index": 1, "block_type": "property_cards", "headline": "Energy flows one way",
        "points": ["Producers capture sunlight", "Only ~10% moves up"],
    })
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert 'viewBox="0 0 1920 1080"' in svg
    assert "ENERGY FLOWS ONE WAY" in svg          # headlines are set in caps
    assert "Producers capture sunlight" in svg


def test_slide_escapes_markup_in_content():
    svg = render_scene_svg({"index": 1, "headline": "A < B & C", "points": ["<script>x</script>"]})
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg and "&amp;" in svg


def test_archetype_mapping_and_title_slide():
    assert archetype_for("opening") == "title"
    assert archetype_for("summary") == "recap"
    assert archetype_for("unknown-type") == "points"
    svg = render_scene_svg({"index": 1, "block_type": "opening", "headline": "Energy Flow",
                            "eyebrow": "Ecology", "subtitle": "Where the energy goes"})
    assert "ECOLOGY" in svg and "Where the energy goes" in svg


def test_accent_colour_is_selectable_per_scene():
    loss = render_scene_svg({"index": 2, "headline": "Heat lost", "accent": "loss"})
    production = render_scene_svg({"index": 2, "headline": "Made here", "accent": "production"})
    assert "#e0522c" in loss and "#34c98a" in production


def test_render_storyboard_returns_one_slide_per_scene():
    svgs = slides_for([{"headline": "A"}, {"headline": "B"}, {"headline": "C"}])
    assert len(svgs) == 3
    assert "01 ·" in svgs[0] and "03 ·" in svgs[2]


# ------------------------------------------------------------------ job

class _FakeNarrator:
    configured = True
    model = "aura-test"

    def __init__(self):
        self.calls = []

    def narrate(self, text):
        self.calls.append(text)
        return Narration(audio=b"mp3", model=self.model, words=[
            {"text": "energy", "startSeconds": 0.0, "endSeconds": 0.6},
            {"text": "flows", "startSeconds": 0.6, "endSeconds": 1.4},
        ])


@dataclass
class _Stored:
    key: str
    url: str


class _FakeStorage:
    def __init__(self):
        self.uploaded = []

    def upload_media(self, key, content, content_type, **kw):
        self.uploaded.append((key, content_type, len(content)))
        return _Stored(key=key, url=f"https://signed.example/{key}")

    def signed_upload_url(self, key, content_type="video/mp4", **kw):
        return _Stored(key=key, url=f"https://signed.example/put/{key}")

    @staticmethod
    def render_key(storyboard_id, version, name):
        return f"video/storyboard-{storyboard_id}/v{version}/{name}"


class _FakeClient:
    configured = True

    def __init__(self, fail=False):
        self.fail = fail
        self.spec = None

    def render(self, spec, upload_url=None):
        self.spec = spec
        self.upload_url = upload_url
        if self.fail:
            raise RuntimeError("worker exploded")
        return RenderResult(ok=True, bytes_written=2048)


def _approved_storyboard(db):
    user = User(email="ed@x.com", full_name="Ed", password_hash=hash_password("x"), role="editor")
    event = Event(slug="ecology", name="Ecology", division="C", season=2026)
    db.add_all([user, event]); db.flush()
    src = Source(url="https://s.gov/a", title="A", rights_status="public_domain", approved=True)
    db.add(src); db.flush()
    snap = SourceSnapshot(source_id=src.id, final_url=src.url, content_hash="h")
    db.add(snap); db.flush()
    claim = ScientificClaim(source_id=src.id, source_snapshot_id=snap.id,
                            claim_text="Energy flows one way.", approved=True)
    db.add(claim); db.flush()
    lesson = Lesson(event_id=event.id, slug="energy", title="Energy Flow", status="published")
    db.add(lesson); db.flush()
    db.add(LessonVersion(lesson_id=lesson.id, version=1, claim_ids=[claim.id], content=[
        {"type": "opening", "heading": "Start here"},
        {"type": "summary", "heading": "Recap"},
    ]))
    db.commit()
    draft = sb.draft_from_lesson(db, lesson.id)
    scenes = [{**s, "narration": "Energy flows one way.", "claim_ids": [claim.id]}
              for s in draft["scenes"]]
    board = sb.create_storyboard(db, lesson.id, scenes)
    sb.approve_storyboard(db, board.id, user.id)
    db.commit()
    return board.id


def test_render_job_produces_a_video_with_provenance():
    with SessionLocal() as db:
        board_id = _approved_storyboard(db)
        narrator, storage, client = _FakeNarrator(), _FakeStorage(), _FakeClient()
        render = render_storyboard(db, board_id, narrator=narrator, client=client, storage=storage)

        assert render.status == "succeeded"
        assert render.video_key.endswith("lesson.mp4")
        assert render.duration_seconds > 0
        assert len(render.audio_keys) == 2 and len(render.slide_keys) == 2
        assert render.provenance["scenes"] == 2
        assert render.provenance["tts_model"] == "aura-test"
        assert render.spec_hash and len(render.spec_hash) == 64

    # every scene narrated; slides and audio both uploaded
    assert len(narrator.calls) == 2
    kinds = {ct for _, ct, _ in storage.uploaded}
    assert kinds == {"audio/mpeg", "image/svg+xml"}
    # the worker got a spec whose sources are all signed https URLs
    for clip in client.spec["clips"]:
        assert clip["sourcePath"].startswith("https://")
    assert client.upload_url.startswith("https://")


def test_render_job_is_blocked_by_the_approval_gate():
    with SessionLocal() as db:
        board_id = _approved_storyboard(db)
        board = db.get(sb.VideoStoryboard, board_id)
        board.status = sb.DRAFT          # un-approve it
        db.commit()
        with pytest.raises(sb.StoryboardError, match="approve it before rendering"):
            render_storyboard(db, board_id, narrator=_FakeNarrator(),
                              client=_FakeClient(), storage=_FakeStorage())


def test_failed_render_is_recorded_not_silently_lost():
    with SessionLocal() as db:
        board_id = _approved_storyboard(db)
        with pytest.raises(RuntimeError, match="worker exploded"):
            render_storyboard(db, board_id, narrator=_FakeNarrator(),
                              client=_FakeClient(fail=True), storage=_FakeStorage())
        from app.models.entities import VideoRender
        render = db.query(VideoRender).order_by(VideoRender.id.desc()).first()
        assert render.status == "failed"
        assert "worker exploded" in render.error


def test_spec_fingerprint_is_stable_and_order_insensitive():
    a = {"version": 0, "clips": [{"id": "1"}]}
    b = {"clips": [{"id": "1"}], "version": 0}
    assert spec_fingerprint(a) == spec_fingerprint(b)
    assert spec_fingerprint(a) != spec_fingerprint({"version": 0, "clips": [{"id": "2"}]})


# ------------------------------------------------------------------ chapters + parallelism

def test_narration_runs_concurrently_and_preserves_order():
    import threading, time
    seen, lock = [], threading.Lock()

    class Slow:
        configured, model = True, "aura-test"

        def narrate(self, text):
            time.sleep(0.05)                     # simulate a network round trip
            with lock:
                seen.append(text)
            return Narration(audio=b"a", model=self.model,
                             words=[{"text": text, "startSeconds": 0, "endSeconds": 1}])

    scenes = [{"narration": f"scene {i}"} for i in range(6)]
    t0 = time.time()
    results = narrate_scenes(Slow(), scenes, workers=6)
    elapsed = time.time() - t0

    assert [r.words[0]["text"] for r in results] == [s["narration"] for s in scenes], "order preserved"
    assert elapsed < 0.05 * len(scenes), "narration must overlap, not run serially"


def test_render_lesson_produces_one_render_per_chapter():
    with SessionLocal() as db:
        board_id = _approved_storyboard(db)
        board = db.get(sb.VideoStoryboard, board_id)
        board.scenes = [
            {**board.scenes[0], "chapter": "Roles", "narration": "Roles narration here."},
            {**board.scenes[1], "chapter": "Recap", "narration": "Recap narration here."},
        ]
        db.commit()

        client = _FakeClient()
        renders = render_lesson(db, board_id, narrator=_FakeNarrator(),
                                client=client, storage=_FakeStorage())
        assert len(renders) == 2
        assert [r.chapter for r in renders] == ["roles", "recap"]
        assert all(r.status == "succeeded" for r in renders)
        # each chapter writes its own video, so one cannot overwrite another
        keys = [r.video_key for r in renders]
        assert len(set(keys)) == 2
        assert all(k.endswith("lesson.mp4") for k in keys)


def test_render_lesson_respects_the_approval_gate():
    with SessionLocal() as db:
        board_id = _approved_storyboard(db)
        db.get(sb.VideoStoryboard, board_id).status = sb.DRAFT
        db.commit()
        with pytest.raises(sb.StoryboardError, match="approve it before rendering"):
            render_lesson(db, board_id, narrator=_FakeNarrator(),
                          client=_FakeClient(), storage=_FakeStorage())
