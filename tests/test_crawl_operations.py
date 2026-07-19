from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    BackgroundJob, Concept, Event, Question, ScientificClaim, Source,
)
def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_due_scheduler_routes_full_text_and_metadata_sources_separately(client, admin_token):
    with SessionLocal() as db:
        due = Source(
            url="https://science.nasa.gov/due",
            title="Due",
            rights_status="fact_grounding_allowed",
            approved=True,
            next_crawl_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        duplicate = Source(
            url="https://science.nasa.gov/duplicate",
            title="Duplicate",
            rights_status="fact_grounding_allowed",
            approved=True,
        )
        link_only = Source(
            url="https://www.soinc.org/link-only",
            title="Link only",
            rights_status="metadata_only",
            approved=True,
        )
        db.add_all([due, duplicate, link_only])
        db.flush()
        db.add(BackgroundJob(
            job_type="crawl_source",
            status="queued",
            payload={"source_id": duplicate.id},
        ))
        db.commit()

    scheduled = client.post("/api/discovery/schedule-due", headers=auth(admin_token))
    assert scheduled.status_code == 200
    assert scheduled.json()["count"] == 2
    again = client.post("/api/discovery/schedule-due", headers=auth(admin_token))
    assert again.json()["count"] == 0
    coverage = client.get("/api/discovery/coverage", headers=auth(admin_token))
    assert coverage.status_code == 200
    assert coverage.json()["sources"]["by_health"]["queued"] == 2
    with SessionLocal() as db:
        jobs = db.scalars(select(BackgroundJob).where(
            BackgroundJob.status == "queued"
        )).all()
        assert {job.job_type for job in jobs} == {"crawl_source", "check_source_metadata"}


def test_recurring_scheduler_creates_next_run_and_crawl_job(client, admin_token):
    with SessionLocal() as db:
        source = Source(
            url="https://science.nasa.gov/recurring",
            title="Recurring",
            rights_status="fact_grounding_allowed",
            approved=True,
        )
        db.add(source)
        db.flush()
        scheduler = BackgroundJob(
            job_type="schedule_due_crawls",
            payload={"recurring": True},
            scheduled_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        db.add(scheduler)
        db.commit()

    result = client.post("/api/jobs/run-next", headers=auth(admin_token))
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    assert result.json()["result"]["count"] == 1
    with SessionLocal() as db:
        schedulers = db.scalars(select(BackgroundJob).where(
            BackgroundJob.job_type == "schedule_due_crawls"
        )).all()
        crawl_jobs = db.scalars(select(BackgroundJob).where(
            BackgroundJob.job_type == "crawl_source"
        )).all()
        assert len(schedulers) == 2
        assert len(crawl_jobs) == 1


def test_crawl_failure_updates_source_health(client, admin_token, monkeypatch):
    def fail_crawl(*args, **kwargs):
        raise ValueError("network unavailable")

    monkeypatch.setattr("app.services.jobs.crawl_source", fail_crawl)
    with SessionLocal() as db:
        source = Source(
            url="https://science.nasa.gov/failure",
            title="Failure",
            rights_status="fact_grounding_allowed",
            approved=True,
        )
        db.add(source)
        db.flush()
        db.add(BackgroundJob(
            job_type="crawl_source",
            payload={"source_id": source.id},
            scheduled_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
        db.commit()
        source_id = source.id

    result = client.post("/api/jobs/run-next", headers=auth(admin_token))
    assert result.json()["status"] == "queued"
    with SessionLocal() as db:
        source = db.get(Source, source_id)
        assert source.crawl_status == "retrying"
        assert source.consecutive_crawl_failures == 1
        assert "network unavailable" in source.last_crawl_error
        assert source.next_crawl_at is not None


def test_source_withdrawal_quarantines_dependencies(client, admin_token, coach_token):
    with SessionLocal() as db:
        source = Source(
            url="https://science.nasa.gov/withdraw",
            title="Withdraw",
            rights_status="fact_grounding_allowed",
            approved=True,
        )
        event = Event(slug="withdraw", name="Withdraw", division="B", season=2026)
        db.add_all([source, event])
        db.flush()
        concept = Concept(event_id=event.id, name="Concept")
        db.add(concept)
        db.flush()
        claim = ScientificClaim(
            source_id=source.id,
            concept_id=concept.id,
            claim_text="A claim that will be withdrawn.",
            approved=True,
        )
        db.add(claim)
        db.flush()
        db.add(Question(
            event_id=event.id,
            concept_id=concept.id,
            source_id=source.id,
            status="published",
            stem="Which answer follows the withdrawn claim?",
            choices=["A", "B"],
            answer_spec={"correct_index": 0},
            generation_provenance={"claim_ids": [claim.id]},
        ))
        db.commit()
        source_id = source.id

    denied = client.post(
        f"/api/sources/{source_id}/withdraw",
        headers=auth(coach_token),
        json={"reason": "The publisher withdrew permission for continued use."},
    )
    assert denied.status_code == 403
    withdrawn = client.post(
        f"/api/sources/{source_id}/withdraw",
        headers=auth(admin_token),
        json={"reason": "The publisher withdrew permission for continued use."},
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["impact"]["questions_quarantined"] == 1
    with SessionLocal() as db:
        source = db.get(Source, source_id)
        assert source.approved is False
        assert source.rights_status == "quarantined"
        assert source.crawl_status == "withdrawn"
        assert db.scalar(select(Question)).status == "quarantined"
