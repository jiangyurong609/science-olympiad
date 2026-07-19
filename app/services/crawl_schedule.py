from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import BackgroundJob, Source
from app.services.discovery import matching_domain_policy
from app.services.rights import can_fetch_full_text


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def source_recrawl_minutes(db: Session, source: Source) -> int:
    from urllib.parse import urlparse

    policy = matching_domain_policy(db, urlparse(source.url).hostname or "")
    return policy.recrawl_minutes if policy else 43_200


def mark_crawl_success(db: Session, source: Source, checked_at: datetime | None = None) -> None:
    now = checked_at or datetime.now(timezone.utc)
    source.fetched_at = now
    source.last_successful_crawl_at = now
    source.next_crawl_at = now + timedelta(minutes=source_recrawl_minutes(db, source))
    source.consecutive_crawl_failures = 0
    source.last_crawl_error = ""
    source.crawl_status = "healthy"
    db.add(source)


def mark_crawl_failure(
    db: Session,
    source: Source,
    error: str,
    *,
    terminal: bool,
) -> None:
    source.consecutive_crawl_failures += 1
    source.last_crawl_error = error[:4000]
    delay_minutes = min(
        source_recrawl_minutes(db, source),
        5 * (2 ** max(0, source.consecutive_crawl_failures - 1)),
    )
    source.next_crawl_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
    source.crawl_status = "failed" if terminal else "retrying"
    db.add(source)


def schedule_due_sources(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 250,
) -> list[BackgroundJob]:
    current = now or datetime.now(timezone.utc)
    sources = db.scalars(select(Source).where(
        Source.approved.is_(True),
        Source.crawl_status != "withdrawn",
    ).order_by(Source.next_crawl_at.asc().nulls_first(), Source.id).limit(limit * 2)).all()
    pending_jobs = db.scalars(select(BackgroundJob).where(
        BackgroundJob.job_type.in_(["crawl_source", "check_source_metadata"]),
        BackgroundJob.status.in_(["queued", "running"]),
    )).all()
    pending_source_ids = {
        int(job.payload["source_id"]) for job in pending_jobs if job.payload.get("source_id")
    }
    created = []
    for source in sources:
        due = source.next_crawl_at is None or _aware(source.next_crawl_at) <= current
        if not due or source.id in pending_source_ids:
            continue
        if can_fetch_full_text(source.rights_status):
            job_type = "crawl_source"
        elif source.rights_status in {"link_only", "metadata_only"}:
            job_type = "check_source_metadata"
        else:
            continue
        job = BackgroundJob(
            job_type=job_type,
            payload={"source_id": source.id, "scheduled_by": "freshness_scheduler"},
            scheduled_at=current,
        )
        db.add(job)
        source.crawl_status = "queued"
        created.append(job)
        if len(created) >= limit:
            break
    db.flush()
    return created
