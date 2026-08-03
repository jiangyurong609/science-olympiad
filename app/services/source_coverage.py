from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Event, EventSourceMap, ScientificClaim, Source, SourceMetadataCheck, SourceSnapshot,
    SpecimenAsset,
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _coverage_facts(db: Session, source_ids: set[int]) -> dict:
    """Batch every per-source lookup the scorecard needs.

    The obvious shape — five queries inside the mapping loop — was 233 seconds
    against production: not data volume (13 MB of snapshots) but ~4,000 request
    round-trips over the VPC connector. The whole dataset fits in a handful of
    set-based queries, and none of them needs extracted_text itself, only
    whether the latest snapshot has any.
    """
    facts = {
        "sources": {},
        "snapshot_counts": defaultdict(int),
        "latest_snapshot": {},          # source_id -> (created_at, has_text)
        "metadata_check_counts": defaultdict(int),
        "latest_metadata_check_at": {},
        "approved_claims": defaultdict(int),
        "approved_assets": defaultdict(int),
    }
    if not source_ids:
        return facts

    for source in db.scalars(select(Source).where(Source.id.in_(source_ids))):
        facts["sources"][source.id] = source

    snapshot_rows = db.execute(
        select(
            SourceSnapshot.source_id,
            SourceSnapshot.created_at,
            func.length(func.trim(SourceSnapshot.extracted_text)) > 0,
        ).where(SourceSnapshot.source_id.in_(source_ids))
        .order_by(SourceSnapshot.source_id, SourceSnapshot.created_at.desc())
    ).all()
    for source_id, created_at, has_text in snapshot_rows:
        facts["snapshot_counts"][source_id] += 1
        if source_id not in facts["latest_snapshot"]:
            facts["latest_snapshot"][source_id] = (created_at, bool(has_text))

    check_rows = db.execute(
        select(
            SourceMetadataCheck.source_id,
            SourceMetadataCheck.checked_at,
        ).where(SourceMetadataCheck.source_id.in_(source_ids))
        .order_by(
            SourceMetadataCheck.source_id,
            SourceMetadataCheck.checked_at.desc(),
            SourceMetadataCheck.id.desc(),
        )
    ).all()
    for source_id, checked_at in check_rows:
        facts["metadata_check_counts"][source_id] += 1
        if source_id not in facts["latest_metadata_check_at"]:
            facts["latest_metadata_check_at"][source_id] = checked_at

    claim_rows = db.execute(
        select(ScientificClaim.source_id, func.count(ScientificClaim.id))
        .where(
            ScientificClaim.source_id.in_(source_ids),
            ScientificClaim.approved.is_(True),
            ScientificClaim.source_snapshot_id.is_not(None),
        ).group_by(ScientificClaim.source_id)
    ).all()
    for source_id, count in claim_rows:
        facts["approved_claims"][source_id] = int(count)

    asset_rows = db.execute(
        select(SpecimenAsset.source_id, func.count(SpecimenAsset.id))
        .where(
            SpecimenAsset.source_id.in_(source_ids),
            SpecimenAsset.review_status == "approved",
            SpecimenAsset.taxon_verified.is_(True),
            SpecimenAsset.rights_status.in_([
                "public_domain", "approved_with_attribution", "derivative_generation_allowed",
            ]),
        ).group_by(SpecimenAsset.source_id)
    ).all()
    for source_id, count in asset_rows:
        facts["approved_assets"][source_id] = int(count)

    return facts


def _event_scorecard(event: Event, mappings: list[EventSourceMap], facts: dict, now: datetime) -> dict:
    rows = []
    for mapping in mappings:
        source = facts["sources"][mapping.source_id]
        snapshot_count = facts["snapshot_counts"][mapping.source_id]
        latest = facts["latest_snapshot"].get(mapping.source_id)
        latest_has_text = bool(latest and latest[1])
        metadata_check_at = facts["latest_metadata_check_at"].get(mapping.source_id)
        approved_claims = facts["approved_claims"][mapping.source_id]
        approved_assets = facts["approved_assets"][mapping.source_id]
        available = {"registry_record"}
        if metadata_check_at is not None:
            available.add("metadata")
        if latest:
            available.add("raw_snapshot")
        if latest_has_text:
            available.add("parsed_text")
        if approved_claims:
            available.add("claims")
        if approved_assets:
            available.add("image")
        missing = sorted(set(mapping.required_artifact_types or []) - available)
        rights_blocked = source.rights_status in {"blocked", "quarantined"}
        withdrawn = source.crawl_status == "withdrawn"
        stale = bool(
            source.last_successful_crawl_at
            and (
                (source.next_crawl_at and _aware(source.next_crawl_at) <= now)
                or source.crawl_status in {"failed", "retrying"}
            )
        )
        healthy_schedule = bool(
            source.last_successful_crawl_at
            and source.next_crawl_at
            and _aware(source.next_crawl_at) > now
            and source.crawl_status == "healthy"
        )
        if not mapping.reviewed:
            state = "unknown"
        elif rights_blocked or withdrawn:
            state = "restricted"
        elif not latest and metadata_check_at is None:
            state = "registered"
        elif not latest and metadata_check_at is not None:
            if stale:
                state = "stale"
            elif missing:
                state = "registered"
            elif healthy_schedule:
                state = "monitored"
            else:
                state = "registered"
        elif not latest_has_text:
            state = "crawled"
        elif "claims" in (mapping.required_artifact_types or []) and not approved_claims:
            state = "parsed"
        elif stale:
            state = "stale"
        elif missing:
            state = "grounded" if approved_claims else "parsed"
        elif healthy_schedule:
            state = "monitored"
        else:
            state = "grounded" if approved_claims else "parsed"
        rows.append({
            "mapping_id": mapping.id,
            "source_id": source.id,
            "title": source.title,
            "url": source.url,
            "publisher": source.publisher,
            "purpose": mapping.purpose,
            "source_tier": mapping.source_tier,
            "jurisdiction": mapping.jurisdiction,
            "required": mapping.required,
            "required_artifact_types": mapping.required_artifact_types,
            "available_artifact_types": sorted(available),
            "missing_artifact_types": missing,
            "source_universe_version": mapping.source_universe_version,
            "coverage_owner": mapping.coverage_owner,
            "rights_status": source.rights_status,
            "approved": source.approved,
            "crawl_status": source.crawl_status,
            "coverage_state": state,
            "snapshot_count": snapshot_count,
            "metadata_check_count": facts["metadata_check_counts"][mapping.source_id],
            "last_metadata_check_at": metadata_check_at,
            "approved_claim_count": int(approved_claims),
            "approved_asset_count": int(approved_assets),
            "last_successful_crawl_at": source.last_successful_crawl_at,
            "next_crawl_at": source.next_crawl_at,
            "last_crawl_error": source.last_crawl_error,
        })
    required = [row for row in rows if row["required"]]
    monitored = [row for row in required if row["coverage_state"] == "monitored"]
    known = [row for row in required if row["coverage_state"] != "unknown"]
    return {
        "event": {
            "id": event.id,
            "slug": event.slug,
            "name": event.name,
            "season": event.season,
            "division": event.division,
            "season_status": event.season_status,
        },
        "summary": {
            "mapped_sources": len(rows),
            "required_sources": len(required),
            "known_required_sources": len(known),
            "monitored_required_sources": len(monitored),
            "coverage_ratio": round(len(monitored) / len(required), 4) if required else 0.0,
            "competition_release_ready": bool(required)
            and event.season_status == "current"
            and len(monitored) == len(required),
        },
        "states": {
            state: sum(1 for row in rows if row["coverage_state"] == state)
            for state in ("unknown", "restricted", "registered", "crawled", "parsed", "grounded", "stale", "monitored")
        },
        "sources": rows,
    }


def events_source_coverage(db: Session, events: list[Event]) -> list[dict]:
    now = datetime.now(timezone.utc)
    event_ids = [event.id for event in events]
    mappings_by_event: dict[int, list[EventSourceMap]] = defaultdict(list)
    if event_ids:
        for mapping in db.scalars(
            select(EventSourceMap).where(EventSourceMap.event_id.in_(event_ids))
            .order_by(EventSourceMap.source_tier, EventSourceMap.purpose, EventSourceMap.id)
        ):
            mappings_by_event[mapping.event_id].append(mapping)
    source_ids = {m.source_id for ms in mappings_by_event.values() for m in ms}
    facts = _coverage_facts(db, source_ids)
    return [
        _event_scorecard(event, mappings_by_event.get(event.id, []), facts, now)
        for event in events
    ]


def event_source_coverage(db: Session, event: Event) -> dict:
    return events_source_coverage(db, [event])[0]
