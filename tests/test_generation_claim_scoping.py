"""An item may only be grounded in its own event's evidence.

Every gate on generated items asks whether the item is *supported* — the solver reproduces the
key, the verifier finds no error, the claims exist and are approved. None asks whether it is
*on topic*. So a claim admitted from the wrong event produces an item that passes everything
and is still wrong for the exam it lands in: production held a Chemistry Lab question about
which mineral effervesces in acid, and a Meteorology question asking for the definition of a
mineral. Both were grounded, verified, solver-agreed, and nonsense in context.

The cause was a single `OR concept_id IS NULL` in the claim query.
"""
import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, ScientificClaim, Source, SourceSnapshot,
)
from app.services.model_generation import _grounding_context


def seed():
    """Two events. One holds an unattached claim; the other must never see it."""
    with SessionLocal() as db:
        source = Source(title="USGS", url="https://usgs.gov/x", rights_status="public_domain",
                        approved=True)
        db.add(source); db.flush()
        snapshot = SourceSnapshot(source_id=source.id, final_url="https://usgs.gov/x",
                                  extracted_text="text", content_hash="h")
        db.add(snapshot); db.flush()

        rocks = Event(slug="scope-rocks", name="Rocks", division="B", season=2026)
        weather = Event(slug="scope-weather", name="Meteorology", division="B", season=2026)
        db.add_all([rocks, weather]); db.flush()

        rock_concept = Concept(event_id=rocks.id, name="Minerals", description="x")
        weather_concept = Concept(event_id=weather.id, name="Fronts", description="x")
        db.add_all([rock_concept, weather_concept]); db.flush()

        # the shape that leaked: approved, snapshotted, and attached to no concept at all
        db.add(ScientificClaim(source_id=source.id, source_snapshot_id=snapshot.id,
                               concept_id=None, claim_text="Calcite effervesces in acid.",
                               approved=True))
        # the weather event's own evidence
        db.add(ScientificClaim(source_id=source.id, source_snapshot_id=snapshot.id,
                               concept_id=weather_concept.id,
                               claim_text="A cold front lifts warmer air abruptly.",
                               approved=True))
        db.commit()
        return rocks.id, weather.id, weather_concept.id


def test_an_unattached_claim_cannot_ground_another_events_item():
    _, weather_id, weather_concept_id = seed()
    with SessionLocal() as db:
        event = db.get(Event, weather_id)
        concept = db.get(Concept, weather_concept_id)
        _, claims = _grounding_context(db, concept, event)
        texts = " ".join(c.claim_text for c in claims)
        assert "Calcite" not in texts, (
            "a claim belonging to no concept belongs to no event and must not ground this item"
        )
        assert "cold front" in texts


def test_generation_refuses_rather_than_reaching_outside_the_event():
    """An event with no evidence of its own gets a refusal, not someone else's claims."""
    with SessionLocal() as db:
        source = Source(title="USGS", url="https://usgs.gov/y", rights_status="public_domain",
                        approved=True)
        db.add(source); db.flush()
        snapshot = SourceSnapshot(source_id=source.id, final_url="https://usgs.gov/y",
                                  extracted_text="t", content_hash="h2")
        db.add(snapshot); db.flush()
        other = Event(slug="scope-other", name="Other", division="B", season=2026)
        bare = Event(slug="scope-bare", name="Bare", division="B", season=2026)
        db.add_all([other, bare]); db.flush()
        other_concept = Concept(event_id=other.id, name="Something", description="x")
        bare_concept = Concept(event_id=bare.id, name="Nothing", description="x")
        db.add_all([other_concept, bare_concept]); db.flush()
        db.add(ScientificClaim(source_id=source.id, source_snapshot_id=snapshot.id,
                               concept_id=other_concept.id, claim_text="Other event fact.",
                               approved=True))
        db.commit()
        bare_id, bare_concept_id = bare.id, bare_concept.id

    with SessionLocal() as db:
        event = db.get(Event, bare_id)
        concept = db.get(Concept, bare_concept_id)
        with pytest.raises(ValueError):
            _grounding_context(db, concept, event)
