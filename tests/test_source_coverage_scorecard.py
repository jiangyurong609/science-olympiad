from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Event, EventSourceMap, ScientificClaim, Source, SourceMetadataCheck, SourceSnapshot,
)
from app.services.crawl_schedule import mark_crawl_success
from app.services.source_coverage import event_source_coverage


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_source_map():
    with SessionLocal() as db:
        event = Event(
            slug="coverage-event",
            name="Coverage Event",
            division="B",
            season=2026,
            season_status="current",
        )
        source = Source(
            url="https://science.nasa.gov/coverage",
            title="Required Science Source",
            publisher="NASA",
            rights_status="fact_grounding_allowed",
            approved=True,
        )
        db.add_all([event, source])
        db.flush()
        db.add(EventSourceMap(
            event_id=event.id,
            source_id=source.id,
            purpose="science_grounding",
            source_tier=1,
            required=True,
            required_artifact_types=["raw_snapshot", "parsed_text", "claims"],
            source_universe_version="2026.1",
            reviewed=True,
            coverage_owner="Science editor",
        ))
        db.commit()
        return event.id, source.id


def state_for(event_id):
    with SessionLocal() as db:
        return event_source_coverage(db, db.get(Event, event_id))


def test_coverage_advances_from_registered_to_monitored_and_regresses_when_stale():
    event_id, source_id = create_source_map()
    assert state_for(event_id)["sources"][0]["coverage_state"] == "registered"

    with SessionLocal() as db:
        db.add(SourceSnapshot(
            source_id=source_id,
            final_url="https://science.nasa.gov/coverage",
            content_hash="a" * 64,
            content_type="text/html",
            byte_count=100,
            extracted_text="",
        ))
        db.commit()
    assert state_for(event_id)["sources"][0]["coverage_state"] == "crawled"

    with SessionLocal() as db:
        snapshot = db.scalar(select(SourceSnapshot).where(SourceSnapshot.source_id == source_id))
        snapshot.extracted_text = "Reviewed scientific content."
        db.commit()
    parsed = state_for(event_id)
    assert parsed["sources"][0]["coverage_state"] == "parsed"
    assert parsed["sources"][0]["missing_artifact_types"] == ["claims"]

    with SessionLocal() as db:
        snapshot = db.scalar(select(SourceSnapshot).where(SourceSnapshot.source_id == source_id))
        db.add(ScientificClaim(
            source_id=source_id,
            source_snapshot_id=snapshot.id,
            claim_text="A reviewed factual claim grounded in the source snapshot.",
            evidence_excerpt="Reviewed scientific content.",
            locator="section 1",
            approved=True,
        ))
        db.commit()
    assert state_for(event_id)["sources"][0]["coverage_state"] == "grounded"

    with SessionLocal() as db:
        mark_crawl_success(db, db.get(Source, source_id))
        db.commit()
    monitored = state_for(event_id)
    assert monitored["sources"][0]["coverage_state"] == "monitored"
    assert monitored["summary"]["coverage_ratio"] == 1.0
    assert monitored["summary"]["competition_release_ready"] is True

    with SessionLocal() as db:
        source = db.get(Source, source_id)
        source.next_crawl_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    stale = state_for(event_id)
    assert stale["sources"][0]["coverage_state"] == "stale"
    assert stale["summary"]["competition_release_ready"] is False


def test_source_coverage_api_requires_content_staff(client, admin_token, student_token):
    event_id, _ = create_source_map()
    denied = client.get("/api/content/source-coverage", headers=auth(student_token))
    assert denied.status_code == 403
    scorecard = client.get(
        f"/api/content/source-coverage?event_id={event_id}", headers=auth(admin_token)
    )
    assert scorecard.status_code == 200
    assert scorecard.json()["scorecards"][0]["event"]["season_status"] == "current"
    assert scorecard.json()["scorecards"][0]["sources"][0]["coverage_owner"] == "Science editor"


def test_metadata_only_source_can_be_monitored_without_content_snapshot():
    with SessionLocal() as db:
        event = Event(
            slug="metadata-event", name="Metadata Event", division="C", season=2026
        )
        source = Source(
            url="https://www.soinc.org/event",
            title="Official Event Page",
            rights_status="metadata_only",
            approved=True,
        )
        db.add_all([event, source])
        db.flush()
        db.add(EventSourceMap(
            event_id=event.id,
            source_id=source.id,
            purpose="rules_control",
            source_tier=0,
            required=True,
            required_artifact_types=["metadata"],
            source_universe_version="2026.1",
            reviewed=True,
        ))
        db.add(SourceMetadataCheck(
            source_id=source.id,
            final_url=source.url,
            status_code=200,
            content_type="text/html",
            content_length=1234,
        ))
        mark_crawl_success(db, source)
        db.commit()
        event_id = event.id
    result = state_for(event_id)
    row = result["sources"][0]
    assert row["coverage_state"] == "monitored"
    assert row["metadata_check_count"] == 1
    assert row["snapshot_count"] == 0
    assert row["approved_claim_count"] == 0
