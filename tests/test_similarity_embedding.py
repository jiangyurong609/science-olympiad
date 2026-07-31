"""Phase 1 — embedding-similarity wiring in build_similarity_report."""
from __future__ import annotations

from app.core.database import SessionLocal
from app.models.entities import Event, Question
from app.services.validation import build_similarity_report, _cosine


def _seed_two_stems(db, stem_a, stem_b):
    e = Event(slug="astronomy-c", name="Astronomy", division="C", season=2026)
    db.add(e)
    db.flush()
    q = Question(event_id=e.id, stem=stem_b, choices=["a", "b", "c", "d"],
                 answer_spec={"correct_index": 0}, status="published")
    db.add(q)
    db.commit()
    return e


def test_cosine_basic():
    assert _cosine([1, 0], [1, 0]) == 1.0
    assert _cosine([1, 0], [0, 1]) == 0.0
    assert round(_cosine([1, 1], [1, 0]), 4) == 0.7071


def test_embedding_check_not_configured_without_embedder():
    with SessionLocal() as db:
        _seed_two_stems(db, "new stem", "an existing stem about stars")
        report = build_similarity_report(db, "a fresh question about planets", ["a", "b", "c", "d"])
    assert report["embedding_check"] == "not_configured"


def test_embedding_check_blocks_on_high_cosine():
    # Stub embedder: identical unit vector for the query and the one stored stem => cosine 1.0.
    def embed(texts):
        return [[1.0, 0.0] for _ in texts]

    with SessionLocal() as db:
        _seed_two_stems(db, "query", "stored stem")
        report = build_similarity_report(db, "query stem", ["a", "b", "c", "d"], embed=embed)
    ec = report["embedding_check"]
    assert ec["outcome"] == "blocked"
    assert ec["max_cosine"] == 1.0
    assert ec["nearest_question_id"] is not None


def test_embedding_check_clear_on_orthogonal():
    # Query orthogonal to the stored stem => cosine 0 => clear.
    calls = {"n": 0}

    def embed(texts):
        # first vector (query) orthogonal to the rest
        out = []
        for i, _ in enumerate(texts):
            out.append([1.0, 0.0] if i == 0 else [0.0, 1.0])
        calls["n"] += 1
        return out

    with SessionLocal() as db:
        _seed_two_stems(db, "query", "unrelated stored stem")
        report = build_similarity_report(db, "totally different topic", ["a", "b", "c", "d"], embed=embed)
    assert report["embedding_check"]["outcome"] == "clear"
    assert calls["n"] == 1  # embedder invoked exactly once (batched)


def test_embedding_failure_is_non_fatal():
    def embed(texts):
        raise RuntimeError("provider down")

    with SessionLocal() as db:
        _seed_two_stems(db, "query", "stored stem")
        report = build_similarity_report(db, "query stem", ["a", "b", "c", "d"], embed=embed)
    assert report["embedding_check"]["outcome"] == "unavailable"
