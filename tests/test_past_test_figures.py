"""Phase 7a — figure recovery must change what import produces, not just what it logs.

The measurable claim is that an item which needs a diagram, and whose diagram is now
recoverable and unambiguously its own, stops being dropped. The equally important claim is
the negative one: when the figure cannot be pinned to that item, nothing changes, because a
question paired with the wrong figure is worse than a question that was never imported.
"""
from __future__ import annotations

import itertools

import pytest

from app.core.database import SessionLocal
from app.models.entities import Event, Source, SourceSnapshot
from app.services import past_test_import
from app.services.past_test_import import attach_source_figures, build_questions
from app.services.pdf_figures import Figure

_UNIQUE = itertools.count(1)

TEXT = """[Page 1]
1. Identify the mineral in the photograph above.

[Page 2]
2. Which of these is a silicate?
3. What does the diagram on this page show?
"""


def _event(db):
    event = Event(slug=f"ev-fig-{next(_UNIQUE)}", name="Rocks", division="B", season=2026)
    db.add(event); db.flush()
    return event


def _source(db, *, artifact_key=""):
    source = Source(url=f"https://example.org/test-{next(_UNIQUE)}.pdf", title="Past test",
                    rights_status="public_domain", approved=True,
                    metadata_json={"artifact_key": artifact_key} if artifact_key else {})
    db.add(source); db.flush()
    snapshot = SourceSnapshot(source_id=source.id, final_url=source.url,
                              content_hash="h", extracted_text=TEXT)
    db.add(snapshot); db.flush()
    return source, snapshot


def _figure(page, digest="a" * 64):
    return Figure(page=page, sequence=1, content=b"bytes", content_type="image/png",
                  width=400, height=300, sha256=digest, storage_key=f"figures/p{page}")


# ---------------------------------------------------------------- the behaviour change

def test_an_image_dependent_item_with_its_own_figure_is_no_longer_dropped():
    with SessionLocal() as db:
        event = _event(db)
        source, _ = _source(db)
        items = [{"label": "1", "stem": "Identify the mineral in the photograph above.",
                  "question_type": "short_answer", "reference_answer": "quartz",
                  "image_dependent": True, "figures": [_figure(1).descriptor],
                  "figure_match": "label_matched"}]
        questions = build_questions(db, event, source, None, items)
    assert len(questions) == 1, "the figure is present and unambiguous, so it is answerable"
    assert questions[0].assets and questions[0].assets[0]["page"] == 1
    assert questions[0].generation_provenance["figure_resolved"] is True


def test_an_ambiguous_figure_does_not_rescue_the_item():
    """Two questions shared the page with the figure; pairing them would be a guess."""
    with SessionLocal() as db:
        event = _event(db)
        source, _ = _source(db)
        items = [{"label": "3", "stem": "What does the diagram on this page show?",
                  "question_type": "short_answer", "reference_answer": "a delta",
                  "image_dependent": True, "figures": [_figure(2).descriptor],
                  "figure_match": "ambiguous"}]
        questions = build_questions(db, event, source, None, items)
    assert questions == [], "an ambiguous attachment must not make an item look answerable"


def test_a_text_only_item_is_unaffected_by_figure_recovery():
    with SessionLocal() as db:
        event = _event(db)
        source, _ = _source(db)
        items = [{"label": "2", "stem": "Which of these is a silicate?",
                  "question_type": "single_choice", "choices": ["Quartz", "Halite"],
                  "correct_index": 0, "image_dependent": False}]
        questions = build_questions(db, event, source, None, items)
    assert len(questions) == 1
    assert questions[0].assets == []


def test_include_image_dependent_still_overrides_as_before():
    with SessionLocal() as db:
        event = _event(db)
        source, _ = _source(db)
        items = [{"label": "1", "stem": "Identify the mineral in the photograph above.",
                  "question_type": "short_answer", "reference_answer": "quartz",
                  "image_dependent": True, "figure_match": "none"}]
        questions = build_questions(db, event, source, None, items,
                                    include_image_dependent=True)
    assert len(questions) == 1, "the explicit override must keep working"


# ---------------------------------------------------------------- failing soft

def test_a_source_without_retained_bytes_degrades_to_text_only():
    with SessionLocal() as db:
        event = _event(db)
        source, snapshot = _source(db)          # no artifact_key
        items = [{"label": "1", "stem": "Identify the mineral in the photograph above.",
                  "image_dependent": True}]
        stats = attach_source_figures(db, source, snapshot, items)
    assert stats["status"] == "no_bytes"
    assert items[0]["figures"] == []
    assert items[0]["figure_match"] == "no_source_bytes"


def test_an_unreadable_pdf_does_not_fail_the_import(monkeypatch):
    with SessionLocal() as db:
        event = _event(db)
        source, snapshot = _source(db, artifact_key="uploads/broken.pdf")
        monkeypatch.setattr(past_test_import, "_retained_bytes",
                            lambda *a, **k: b"this is not a pdf")
        items = [{"label": "1", "stem": "Identify the mineral in the photograph above.",
                  "image_dependent": True}]
        stats = attach_source_figures(db, source, snapshot, items)
    assert stats["status"].startswith("extraction_failed")
    assert items[0]["figure_match"] == "extraction_failed"


def test_figures_are_attached_by_page_through_the_real_path(monkeypatch):
    """End to end within the service: bytes in, per-item attachment out."""
    class _Report:
        figures = [_figure(1), _figure(2, digest="b" * 64)]
        rejected = {}

    with SessionLocal() as db:
        event = _event(db)
        source, snapshot = _source(db, artifact_key="uploads/test.pdf")
        monkeypatch.setattr(past_test_import, "_retained_bytes", lambda *a, **k: b"%PDF-")
        monkeypatch.setattr(past_test_import, "extract_figures", lambda raw: _Report())
        monkeypatch.setattr(past_test_import, "_store_figure",
                            lambda s, sn, fig: f"stored/{fig.page}")
        items = [
            {"label": "1", "stem": "Identify the mineral in the photograph above.",
             "image_dependent": True},
            {"label": "2", "stem": "Which of these is a silicate?"},
            {"label": "3", "stem": "What does the diagram on this page show?",
             "image_dependent": True},
        ]
        stats = attach_source_figures(db, source, snapshot, items)

    assert stats["status"] == "ok"
    assert stats["figures_found"] == 2
    # page 1 holds one question and one figure; page 2 holds two questions and one figure
    assert items[0]["figure_match"] == "sole_on_page"   # alone with its figure
    assert items[1]["figure_match"] == "no_figure_reference"  # never mentions one
    assert items[2]["figure_match"] == "ambiguous"      # shares its page
    assert stats["image_dependent_resolved"] == 1      # only the pairing we can defend


# ---------------------------------------------------------------- reaching the student

def test_a_recovered_figure_is_given_a_url_when_it_is_served(monkeypatch):
    """The descriptor stores a key, never a URL — a signed URL would expire in place."""
    from app.api import routes
    monkeypatch.setattr("app.services.media_storage.playback_url",
                        lambda key, **kw: f"https://signed.example/{key}")
    resolved = routes._resolve_asset_urls([{"kind": "figure", "storage_key": "figures/p1"}])
    assert resolved[0]["url"] == "https://signed.example/figures/p1"


def test_an_unsignable_key_yields_no_url_rather_than_a_broken_image(monkeypatch):
    from app.api import routes

    def _boom(key, **kw):
        raise RuntimeError("bucket unavailable")

    monkeypatch.setattr("app.services.media_storage.playback_url", _boom)
    resolved = routes._resolve_asset_urls([{"kind": "figure", "storage_key": "figures/p1"}])
    assert "url" not in resolved[0]


def test_an_asset_that_already_has_a_url_is_left_alone():
    from app.api import routes
    asset = {"kind": "specimen", "url": "/static/specimens/quartz.jpg"}
    assert routes._resolve_asset_urls([asset]) == [asset]


def test_attaching_a_figure_makes_a_previously_ungradeable_item_servable():
    """This is the whole point of Phase 7a: the item was excluded from scoring because the
    figure it names was absent, and now it is not."""
    from app.services.scoring import is_figure_missing, is_servable
    stem = "Identify the mineral shown in the diagram above."
    spec = {"answer": "quartz", "accepted": [], "points": 1}
    assert is_figure_missing(stem, []) is True
    assert is_servable("short_answer", spec, stem, []) is False

    figure = [_figure(1).descriptor]
    assert is_figure_missing(stem, figure) is False
    assert is_servable("short_answer", spec, stem, figure) is True


# ------------------------------------------ ambiguity must not reach the student (review find)

def test_an_ambiguous_figure_is_never_written_to_served_assets():
    """`Question.assets` is what the exam snapshot serves.

    Ambiguous candidates were copied there for every located item on the page — including
    plain text items the model never flagged as image-dependent — so a question could be
    served its neighbour's figure. Candidates now live in provenance, visible to review only.
    """
    with SessionLocal() as db:
        event = _event(db)
        source, _ = _source(db)
        items = [{"label": "2", "stem": "Which of these is a silicate?",
                  "question_type": "single_choice", "choices": ["Quartz", "Halite"],
                  "correct_index": 0, "image_dependent": False,
                  "figures": [_figure(2).descriptor], "figure_match": "ambiguous"}]
        questions = build_questions(db, event, source, None, items)

    question = questions[0]
    assert question.assets == [], "an unverified figure must not be served"
    assert question.generation_provenance["figure_candidates"], \
        "but it is kept where a reviewer can see it"


def test_only_a_resolving_match_is_served():
    with SessionLocal() as db:
        event = _event(db)
        source, _ = _source(db)
        items = [{"label": "1", "stem": "Identify the mineral in the photograph above.",
                  "question_type": "short_answer", "reference_answer": "quartz",
                  "image_dependent": True, "figures": [_figure(1).descriptor],
                  "figure_match": "label_matched"}]
        questions = build_questions(db, event, source, None, items)
    assert len(questions[0].assets) == 1
    assert questions[0].generation_provenance["figure_candidates"] == []
