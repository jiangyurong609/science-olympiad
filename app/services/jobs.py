from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.models.entities import BackgroundJob, RemediationCase, Source
from app.services.claim_extraction import extract_claims
from app.services.crawler import check_source_metadata, crawl_source
from app.services.discovery import discover_sitemap
from app.services.crawl_schedule import mark_crawl_failure, schedule_due_sources
from app.services.notifications import deliver_notification_outbox


def enqueue_job(db: Session, job_type: str, payload: dict, actor_user_id: int | None = None, scheduled_at=None) -> BackgroundJob:
    job = BackgroundJob(
        job_type=job_type,
        payload=payload,
        created_by_user_id=actor_user_id,
        scheduled_at=scheduled_at or datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def run_next_job(db: Session) -> BackgroundJob | None:
    now = datetime.now(timezone.utc)
    job = db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.status == "queued", BackgroundJob.scheduled_at <= now)
        .order_by(BackgroundJob.scheduled_at, BackgroundJob.id)
        .with_for_update(skip_locked=True)
    )
    if not job:
        return None
    job.status = "running"
    job.started_at = now
    job.attempts += 1
    db.commit()
    source = None
    try:
        if job.job_type == "crawl_source":
            source = db.get(Source, int(job.payload["source_id"]))
            if not source:
                raise ValueError("Source not found")
            crawl_source(db, source)
            job.result = {"source_id": source.id, "content_hash": source.content_hash}
        elif job.job_type == "check_source_metadata":
            source = db.get(Source, int(job.payload["source_id"]))
            if not source:
                raise ValueError("Source not found")
            check = check_source_metadata(db, source)
            job.result = {
                "source_id": source.id,
                "metadata_check_id": check.id,
                "status_code": check.status_code,
                "body_stored": False,
            }
        elif job.job_type == "extract_claims":
            source = db.get(Source, int(job.payload["source_id"]))
            if not source:
                raise ValueError("Source not found")
            claims = extract_claims(db, source, concept_id=job.payload.get("concept_id"), limit=int(job.payload.get("limit", 10)))
            job.result = {"claim_ids": [c.id for c in claims]}
        elif job.job_type == "scan_delayed_reviews":
            cases = db.scalars(select(RemediationCase).where(RemediationCase.status == "delayed_review")).all()
            due_ids = []
            for case in cases:
                due = (case.plan or {}).get("next_review_at")
                if due:
                    parsed = datetime.fromisoformat(due)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    if parsed <= now:
                        due_ids.append(case.id)
            job.result = {"due_case_ids": due_ids, "count": len(due_ids)}
        elif job.job_type == "discover_sitemap":
            resources = discover_sitemap(
                db,
                str(job.payload["url"]),
                max_urls=int(job.payload.get("max_urls", 10_000)),
            )
            job.result = {
                "resource_ids": [resource.id for resource in resources],
                "count": len(resources),
            }
        elif job.job_type == "schedule_due_crawls":
            created = schedule_due_sources(db, now=now)
            next_run = now + timedelta(minutes=get_settings().crawl_scheduler_minutes)
            db.add(BackgroundJob(
                job_type="schedule_due_crawls",
                payload={"recurring": True},
                scheduled_at=next_run,
                created_by_user_id=job.created_by_user_id,
            ))
            job.result = {
                "crawl_job_ids": [created_job.id for created_job in created],
                "count": len(created),
                "next_run_at": next_run.isoformat(),
            }
        elif job.job_type == "deliver_notification_outbox":
            job.result = deliver_notification_outbox(db, limit=int(job.payload.get("limit", 50)))
        else:
            raise ValueError(f"Unsupported job type: {job.job_type}")
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.error = ""
    except Exception as exc:
        job.error = str(exc)
        job.status = "queued" if job.attempts < job.max_attempts else "dead_letter"
        if source is not None and job.job_type in {"crawl_source", "check_source_metadata"}:
            mark_crawl_failure(
                db,
                source,
                job.error,
                terminal=job.status == "dead_letter",
            )
        if job.status == "queued":
            delay_seconds = min(3600, 30 * (2 ** max(0, job.attempts - 1)))
            job.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        else:
            job.completed_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
