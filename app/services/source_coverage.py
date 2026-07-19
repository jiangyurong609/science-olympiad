from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Event, EventSourceMap, ScientificClaim, Source, SourceMetadataCheck, SourceSnapshot,
    SpecimenAsset,
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def event_source_coverage(db: Session, event: Event) -> dict:
    now = datetime.now(timezone.utc)
    mappings = db.scalars(select(EventSourceMap).where(
        EventSourceMap.event_id == event.id
    ).order_by(EventSourceMap.source_tier, EventSourceMap.purpose, EventSourceMap.id)).all()
    rows = []
    for mapping in mappings:
        source = db.get(Source, mapping.source_id)
        snapshots = db.scalars(select(SourceSnapshot).where(
            SourceSnapshot.source_id == mapping.source_id
        ).order_by(SourceSnapshot.created_at.desc())).all()
        latest = snapshots[0] if snapshots else None
        metadata_check = db.scalar(select(SourceMetadataCheck).where(
            SourceMetadataCheck.source_id == mapping.source_id
        ).order_by(SourceMetadataCheck.checked_at.desc(), SourceMetadataCheck.id.desc()))
        approved_claims = db.scalar(select(func.count(ScientificClaim.id)).where(
            ScientificClaim.source_id == mapping.source_id,
            ScientificClaim.approved.is_(True),
            ScientificClaim.source_snapshot_id.is_not(None),
        )) or 0
        approved_assets = db.scalar(select(func.count(SpecimenAsset.id)).where(
            SpecimenAsset.source_id == mapping.source_id,
            SpecimenAsset.review_status == "approved",
            SpecimenAsset.taxon_verified.is_(True),
            SpecimenAsset.rights_status.in_([
                "public_domain", "approved_with_attribution", "derivative_generation_allowed",
            ]),
        )) or 0
        available = {"registry_record"}
        if metadata_check:
            available.add("metadata")
        if latest:
            available.add("raw_snapshot")
        if latest and latest.extracted_text.strip():
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
        elif not latest and not metadata_check:
            state = "registered"
        elif not latest and metadata_check:
            if stale:
                state = "stale"
            elif missing:
                state = "registered"
            elif healthy_schedule:
                state = "monitored"
            else:
                state = "registered"
        elif not latest.extracted_text.strip():
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
            "snapshot_count": len(snapshots),
            "metadata_check_count": db.scalar(select(func.count(SourceMetadataCheck.id)).where(
                SourceMetadataCheck.source_id == mapping.source_id
            )) or 0,
            "last_metadata_check_at": metadata_check.checked_at if metadata_check else None,
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
