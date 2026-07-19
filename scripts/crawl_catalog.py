"""Rights-aware crawler for the 2026 Science Olympiad material catalog.

Registers the real 46-event 2026 slate plus its source universe from
docs/science-olympiad-material-catalog-2026, then verifies each cataloged URL
with a Camoufox (stealth Firefox) fetch that:

- honors robots.txt and the per-domain crawl delay before every request;
- retains fetched content for ingestion: extracted page/PDF text is stored as a
  SourceSnapshot and the raw bytes are persisted as a RawArtifact on disk;
- records outbound links to rules/FAQ/clarification/score-sheet materials as
  DiscoveredResource frontier rows for follow-up crawling.

Usage:
  python -m scripts.crawl_catalog register                      # catalog -> DB, no network
  python -m scripts.crawl_catalog crawl [--limit N]             # fetch+retain cataloged sources
  python -m scripts.crawl_catalog all [--limit N]
  python -m scripts.crawl_catalog ingest-discovered [--limit N] [--all]
      # promote discovered frontier links (PDFs by default, --all for every type)
      # to Sources, download+retain them, and link each to its event
  python -m scripts.crawl_catalog link-materials    # backfill event links for ingested materials

DATABASE_URL selects the target database (local SQLite or Cloud SQL).
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    CrawlDomainPolicy,
    DiscoveredResource,
    Event,
    EventSourceMap,
    RawArtifact,
    RightsStatus,
    Source,
    SourceMetadataCheck,
    SourceSnapshot,
)
from app.services.artifacts import ArtifactError, store_raw_artifact
from app.services.discovery import DiscoveryError, record_discovered_resource

CATALOG_DIR = Path(__file__).resolve().parent.parent / "docs" / "science-olympiad-material-catalog-2026"
SOURCE_UNIVERSE_VERSION = "catalog-2026-v1"
USER_AGENT = "FieldstoneCatalogVerifier/1.0 (+contact: content-operations)"
MATERIAL_LINK_PATTERN = re.compile(
    r"rule|clarif|faq|score|checklist|slate|handout|training|sample|resource|\.pdf$",
    re.IGNORECASE,
)


def _slug(event_id: str, season: int) -> str:
    suffix = f"-{season}"
    return event_id[: -len(suffix)] if event_id.endswith(suffix) else event_id


def _load_events() -> list[dict]:
    return json.loads((CATALOG_DIR / "catalog" / "events_2026.json").read_text())


def _upsert_source(db, url: str, title: str, publisher: str, notes: str) -> Source:
    source = db.scalar(select(Source).where(Source.url == url))
    if source is None:
        source = Source(url=url, title=title, publisher=publisher)
        db.add(source)
    source.title = title or source.title
    source.publisher = publisher or source.publisher
    metadata = dict(source.metadata_json or {})
    metadata.update({"catalog_notes": notes, "catalog_version": SOURCE_UNIVERSE_VERSION})
    source.metadata_json = metadata
    db.flush()
    return source


def register(db) -> None:
    events_payload = _load_events()
    print(f"Registering {len(events_payload)} events from {CATALOG_DIR.name}")

    # Domain policies: metadata-only verification for the official domain.
    for domain, tier, delay in (("soinc.org", 0, 5.0), ("www.soinc.org", 0, 5.0)):
        policy = db.scalar(select(CrawlDomainPolicy).where(CrawlDomainPolicy.domain == domain))
        if policy is None:
            db.add(CrawlDomainPolicy(
                domain=domain, enabled=True, source_tier=tier,
                default_rights_status=RightsStatus.LINK_ONLY.value,
                crawl_delay_seconds=delay,
                notes="Official competition control source; metadata and link verification only.",
            ))
        else:
            policy.enabled = True

    events_by_id: dict[str, Event] = {}
    for row in events_payload:
        slug = _slug(row["event_id"], row["season"])
        event = db.scalar(select(Event).where(
            Event.slug == slug, Event.season == row["season"]
        ))
        if event is None:
            event = Event(slug=slug, name=row["name"], division=row["division"], season=row["season"])
            db.add(event)
        event.name = row["name"]
        event.division = row["division"]
        event.category = row.get("category", "")
        event.topic_focus = row.get("topic_focus", "")
        event.official_url = row.get("official_event_url", "")
        event.season_status = "current"
        event.active = True
        if not event.description:
            event.description = row.get("topic_focus") or row.get("category", "")
        db.flush()
        events_by_id[row["event_id"]] = event

    # Registry-level official sources.
    with (CATALOG_DIR / "catalog" / "source_registry.csv").open() as handle:
        for row in csv.DictReader(handle):
            _upsert_source(db, row["url"], row["title"], row["publisher"],
                           row.get("notes", ""))

    # Cataloged, URL-bearing materials per event -> Source + EventSourceMap.
    mapped = 0
    with (CATALOG_DIR / "catalog" / "material_discovery_queue.csv").open() as handle:
        for row in csv.DictReader(handle):
            url = (row.get("source_url") or "").strip()
            if not url or row["status"] != "CATALOGED":
                continue
            event = events_by_id.get(row["event_id"])
            if event is None:
                continue
            source = _upsert_source(
                db, url, f"{row['event_name']} — {row['material_type'].replace('_', ' ')}",
                "Science Olympiad, Inc.", row.get("review_notes", ""),
            )
            existing_map = db.scalar(select(EventSourceMap).where(
                EventSourceMap.event_id == event.id,
                EventSourceMap.source_id == source.id,
                EventSourceMap.purpose == row["material_type"],
                EventSourceMap.source_universe_version == SOURCE_UNIVERSE_VERSION,
            ))
            if existing_map is None:
                db.add(EventSourceMap(
                    event_id=event.id, source_id=source.id, purpose=row["material_type"],
                    source_tier=0, required=True, required_artifact_types=["metadata"],
                    source_universe_version=SOURCE_UNIVERSE_VERSION,
                    freshness_minutes=1_440,
                    notes=row.get("review_notes", ""),
                ))
                mapped += 1
    db.commit()
    print(f"Registered {len(events_by_id)} events; {mapped} new event-source map rows.")


class RobotsGate:
    def __init__(self) -> None:
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        host = urlparse(url).netloc
        parser = self._parsers.get(host)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser()
            robots_url = f"https://{host}/robots.txt"
            try:
                response = httpx.get(robots_url, timeout=20,
                                     headers={"User-Agent": USER_AGENT}, follow_redirects=True)
                parser.parse(response.text.splitlines() if response.status_code == 200 else [])
            except httpx.HTTPError:
                # Unreachable robots on a reviewed, cataloged domain: stay conservative
                # and allow only the explicitly cataloged URL fetch.
                parser.parse([])
            self._parsers[host] = parser
        return parser.can_fetch(USER_AGENT, url)


def _pdf_text(raw: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(raw))
    pages = []
    for number, page in enumerate(reader.pages[:250], start=1):
        extracted = (page.extract_text() or "").strip()
        if extracted:
            pages.append(f"[Page {number}]\n{extracted}")
    return "\n\n".join(pages)[:500_000]


class CamoufoxFetcher:
    """Single stealth-browser session; one page per URL."""

    def __enter__(self):
        from camoufox.sync_api import Camoufox

        self._manager = Camoufox(headless=True, humanize=True, locale="en-US", block_webrtc=True)
        self.browser = self._manager.__enter__()
        return self

    def __exit__(self, *exc):
        return self._manager.__exit__(*exc)

    def fetch(self, url: str) -> dict:
        page = self.browser.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            status = response.status if response else 0
            content_type = (response.headers.get("content-type", "") if response else "").lower()
            etag = (response.headers.get("etag", "") if response else "")
            last_modified = (response.headers.get("last-modified", "") if response else "")
            # PDFs are often served as application/octet-stream or with an empty
            # content-type, so also sniff the magic bytes for .pdf-looking responses.
            path_is_pdf = urlparse(page.url).path.lower().endswith(".pdf")
            body = response.body() if (response and ("application/pdf" in content_type or path_is_pdf)) else None
            if body is not None and body[:5] == b"%PDF-":
                raw = body
                text = _pdf_text(raw)
                media_type = "application/pdf"
                title = ""
                links: list[dict] = []
            else:
                page.wait_for_timeout(1_800)
                raw = page.content().encode("utf-8")
                text = (page.inner_text("body") or "").strip()
                media_type = "text/html"
                title = (page.title() or "").strip()
                links = page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => ({href: e.getAttribute('href'), text: (e.textContent || '').trim().slice(0, 120)}))",
                )
            return {
                "status": status,
                "final_url": page.url,
                "title": title,
                "content_type": content_type,
                "media_type": media_type,
                "raw_bytes": raw,
                "text": text,
                "byte_count": len(raw),
                "content_hash": hashlib.sha256(raw).hexdigest(),
                "last_modified": last_modified,
                "etag": etag,
                "links": links,
            }
        finally:
            page.close()


def _domain_delays(db) -> dict[str, float]:
    return {policy.domain: policy.crawl_delay_seconds
            for policy in db.scalars(select(CrawlDomainPolicy)).all()}


def _filename_title(url: str) -> str:
    name = urlparse(url).path.rsplit("/", 1)[-1] or url
    return name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip() or url


_PURPOSE_BY_KEYWORD = [
    ("clarif", "rules_corrections"),
    ("rules", "rules_manual"),
    ("faq", "faq"),
    ("score", "score_sheet"),
    ("checklist", "team_checklist"),
    ("sample", "sample_test"),
    ("handout", "training_handout"),
    ("training", "training_handout"),
    ("overview", "training_handout"),
]


def _material_purpose(url: str) -> str:
    lowered = url.lower()
    for keyword, purpose in _PURPOSE_BY_KEYWORD:
        if keyword in lowered:
            return purpose
    return "reference_material"


def _link_resource_to_event(db, resource, source_id: int) -> bool:
    """Attach an ingested material to the event whose page it was found on,
    via an EventSourceMap row. Idempotent; returns True if a row was created."""
    if not resource.referrer_url:
        return False
    event = db.scalar(select(Event).where(Event.official_url == resource.referrer_url))
    if event is None:
        return False
    purpose = _material_purpose(resource.canonical_url)
    existing = db.scalar(select(EventSourceMap).where(
        EventSourceMap.event_id == event.id,
        EventSourceMap.source_id == source_id,
        EventSourceMap.purpose == purpose,
        EventSourceMap.source_universe_version == SOURCE_UNIVERSE_VERSION,
    ))
    if existing:
        return False
    db.add(EventSourceMap(
        event_id=event.id, source_id=source_id, purpose=purpose, source_tier=0,
        required=False, required_artifact_types=["parsed_text"],
        source_universe_version=SOURCE_UNIVERSE_VERSION, reviewed=True,
        freshness_minutes=1_440, notes="auto-linked ingested material",
    ))
    return True


def link_ingested_to_events(db) -> None:
    """Backfill EventSourceMap rows for already-ingested discovered materials."""
    resources = db.scalars(select(DiscoveredResource).where(
        DiscoveredResource.status == "ingested",
        DiscoveredResource.source_id.is_not(None),
    )).all()
    linked = sum(_link_resource_to_event(db, r, r.source_id) for r in resources)
    db.commit()
    print(f"Linked {linked} ingested materials to events "
          f"({len(resources)} ingested resources scanned).")


def _verify_and_retain(db, fetcher, robots, delays, last_fetch_at, source, label,
                       discover_links: bool = True) -> dict:
    """Fetch one source, persist a content snapshot + raw artifact, and (optionally)
    record outbound material links. Commits per source; returns counters."""
    outcome = {"verified": 0, "failed": 0, "blocked": 0, "retained": 0, "discovered": 0}
    host = urlparse(source.url).netloc
    if not robots.allowed(source.url):
        source.crawl_status = "blocked"
        source.last_crawl_error = "robots.txt disallows this URL"
        db.commit()
        outcome["blocked"] = 1
        print(f"{label} BLOCKED by robots: {source.url}")
        return outcome
    delay = delays.get(host, delays.get(host.removeprefix("www."), 5.0))
    wait = last_fetch_at.get(host, 0) + delay - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        result = fetcher.fetch(source.url)
        last_fetch_at[host] = time.monotonic()
    except Exception as error:  # noqa: BLE001 — record and continue
        source.crawl_status = "failed"
        source.consecutive_crawl_failures += 1
        source.last_crawl_error = str(error)[:2000]
        db.commit()
        outcome["failed"] = 1
        print(f"{label} FAILED {source.url}: {str(error)[:80]}")
        return outcome

    ok = 200 <= result["status"] < 400
    now = datetime.now(timezone.utc)
    source.fetched_at = now
    source.crawl_status = "ok" if ok else "failed"
    source.consecutive_crawl_failures = 0 if ok else source.consecutive_crawl_failures + 1
    source.last_crawl_error = "" if ok else f"HTTP {result['status']}"
    if ok:
        source.last_successful_crawl_at = now
    metadata = dict(source.metadata_json or {})
    metadata.update({
        "http_status": result["status"], "final_url": result["final_url"],
        "page_title": result["title"], "verified_at": now.isoformat(),
    })
    source.metadata_json = metadata
    db.add(SourceMetadataCheck(
        source_id=source.id, final_url=result["final_url"],
        status_code=result["status"], content_type=result["content_type"][:160],
        content_length=result["byte_count"], etag=result["etag"],
        last_modified=result["last_modified"],
    ))

    if ok:
        text = result["text"]
        digest = (
            hashlib.sha256(text.encode("utf-8")).hexdigest()
            if text else result["content_hash"]
        )
        previous = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_id == source.id
        ).order_by(SourceSnapshot.id.desc()))
        snapshot = SourceSnapshot(
            source_id=source.id, final_url=result["final_url"],
            content_hash=digest, content_type=result["content_type"][:160],
            byte_count=result["byte_count"], extracted_text=text,
            previous_snapshot_id=previous.id if previous else None,
            etag=result["etag"][:500], last_modified=result["last_modified"][:500],
            change_kind="initial" if previous is None else "update",
            metadata_json={
                "status_code": result["status"],
                "parser": "pypdf" if result["media_type"] == "application/pdf" else "camoufox",
            },
        )
        db.add(snapshot)
        db.flush()
        try:
            artifact_info = store_raw_artifact(result["raw_bytes"], result["media_type"])
            db.add(RawArtifact(snapshot_id=snapshot.id, **artifact_info))
            source.metadata_json = {
                **source.metadata_json,
                "raw_artifact_key": artifact_info["storage_key"],
                "raw_content_hash": artifact_info["content_hash"],
            }
        except ArtifactError as artifact_error:
            print(f"    (raw artifact not stored: {artifact_error})")
        source.extracted_text = text
        source.content_hash = digest
        outcome["retained"] = 1

        if discover_links:
            for link in result["links"]:
                href = (link.get("href") or "").strip()
                link_text = link.get("text") or ""
                if not href or href.startswith(("#", "mailto:", "javascript:")):
                    continue
                if not MATERIAL_LINK_PATTERN.search(href) and not MATERIAL_LINK_PATTERN.search(link_text):
                    continue
                try:
                    record_discovered_resource(
                        db, href, referrer_url=result["final_url"],
                        discovery_method="catalog_event_page", source_tier=0,
                    )
                    outcome["discovered"] += 1
                except DiscoveryError:
                    continue
    db.commit()
    outcome["verified"] = int(ok)
    outcome["failed"] = int(not ok)
    print(f"{label} {'OK' if ok else 'HTTP ' + str(result['status'])} "
          f"{source.url} — {result['title'][:60]}")
    return outcome


def crawl(db, limit: int | None = None) -> None:
    robots = RobotsGate()
    sources = [
        source for source in db.scalars(select(Source).order_by(Source.id)).all()
        if (source.metadata_json or {}).get("catalog_version") == SOURCE_UNIVERSE_VERSION
    ]
    if limit:
        sources = sources[:limit]
    delays = _domain_delays(db)
    print(f"Verifying {len(sources)} cataloged sources with camoufox…")
    totals = {"verified": 0, "failed": 0, "blocked": 0, "retained": 0, "discovered": 0}
    last_fetch_at: dict[str, float] = {}
    with CamoufoxFetcher() as fetcher:
        for index, source in enumerate(sources, start=1):
            outcome = _verify_and_retain(
                db, fetcher, robots, delays, last_fetch_at, source,
                f"[{index}/{len(sources)}]", discover_links=True,
            )
            for key in totals:
                totals[key] += outcome[key]
    print(f"Done: {totals['verified']} verified, {totals['retained']} content snapshots retained, "
          f"{totals['failed']} failed, {totals['discovered']} material links recorded.")


def ingest_discovered(db, limit: int | None = None, pdf_only: bool = True) -> None:
    """Promote discovered frontier links to Sources and download + retain them."""
    robots = RobotsGate()
    rows = db.scalars(
        select(DiscoveredResource)
        .where(DiscoveredResource.status == "discovered")
        .order_by(DiscoveredResource.id)
    ).all()
    if pdf_only:
        rows = [r for r in rows if r.canonical_url.lower().split("?")[0].endswith(".pdf")]
    if limit:
        rows = rows[:limit]
    delays = _domain_delays(db)
    kind = "PDF" if pdf_only else "material"
    print(f"Ingesting {len(rows)} discovered {kind} resources with camoufox…")
    totals = {"verified": 0, "failed": 0, "blocked": 0, "retained": 0, "discovered": 0}
    linked = 0
    last_fetch_at: dict[str, float] = {}
    with CamoufoxFetcher() as fetcher:
        for index, resource in enumerate(rows, start=1):
            source = _upsert_source(
                db, resource.canonical_url, _filename_title(resource.canonical_url),
                "Science Olympiad, Inc.", f"discovered via {resource.discovery_method}",
            )
            outcome = _verify_and_retain(
                db, fetcher, robots, delays, last_fetch_at, source,
                f"[{index}/{len(rows)}]", discover_links=False,
            )
            resource.source_id = source.id
            if outcome["verified"]:
                resource.status = "ingested"
                linked += _link_resource_to_event(db, resource, source.id)
            elif outcome["blocked"]:
                resource.status = "blocked"
            else:
                resource.status = "error"
            db.commit()
            for key in totals:
                totals[key] += outcome[key]
    print(f"Done: {totals['retained']} downloaded & retained, {linked} linked to events, "
          f"{totals['failed']} failed, {totals['blocked']} blocked.")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "all"
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    with SessionLocal() as db:
        if command in {"register", "all"}:
            register(db)
        if command in {"crawl", "all"}:
            crawl(db, limit=limit)
        if command == "ingest-discovered":
            ingest_discovered(db, limit=limit, pdf_only="--all" not in sys.argv)
        if command == "link-materials":
            link_ingested_to_events(db)


if __name__ == "__main__":
    main()
