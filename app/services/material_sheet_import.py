from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Event, EventSourceMap, RightsStatus, Source
from app.services.discovery import DiscoveryError, canonicalize_url


ALLOWED_HOSTS = {"soinc.org", "www.soinc.org", "youtu.be", "youtube.com", "www.youtube.com"}
REQUIRED_COLUMNS = {"Link Text", "Internal URL Reference"}

# The sheet is a flattened export of event sections. These aliases identify the
# section boundaries without pretending that every resource title repeats its event.
EVENT_ALIASES = {
    "anatomy and physiology": "Anatomy & Physiology",
    "astronomy": "Astronomy",
    "boomilever": "Boomilever",
    "chemistry lab": "Chemistry Lab",
    "circuit lab": "Circuit Lab",
    "codebusters": "Codebusters",
    "crime busters": "Crime Busters",
    "designer genes": "Designer Genes",
    "disease detectives": "Disease Detectives",
    "dynamic planet": "Dynamic Planet",
    "electric vehicle": "Electric Vehicle",
    "engineering cad": "Engineering CAD",
    "experimental design": "Experimental Design",
    "food science": "Food Science",
    "forensics": "Forensics",
    "glider": "Elastic Launch Glider",
    "heredity": "Heredity",
    "hovercraft": "Hovercraft",
    "meteorology": "Meteorology",
    "mission possible": "Mission Possible",
    "ping pong parachute": "Ping Pong Parachute",
    "protein modeling": "Protein Modeling",
    "remote sensing": "Remote Sensing",
    "rocks and minerals": "Rocks and Minerals",
    "roller coaster": "Roller Coaster",
    "solar system": "Solar System",
    "thermodynamics": "Thermodynamics",
    "wright stuff": "Wright Stuff",
    "write it do it": "Write It Do It",
}

GLOBAL_TITLES = {
    "welcome video",
    "live session schedule",
    "build clinic schedule",
    "scienceolympiadtv",
}


class MaterialSheetError(ValueError):
    pass


@dataclass(frozen=True)
class MaterialSheetRow:
    row_number: int
    title: str
    url: str


@dataclass(frozen=True)
class PreparedMaterial:
    row_number: int
    title: str
    original_url: str
    canonical_url: str | None
    event_name: str | None
    division_hint: str | None
    purpose: str
    issue: str | None = None


@dataclass
class MaterialImportReport:
    mode: str
    season: int
    spreadsheet_id: str
    gid: str
    source_fingerprint: str
    rows_seen: int = 0
    rows_ready: int = 0
    sources_created: int = 0
    sources_updated: int = 0
    sources_existing: int = 0
    mappings_created: int = 0
    mappings_existing: int = 0
    skipped_global: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def parse_material_csv(payload: bytes) -> list[MaterialSheetRow]:
    if len(payload) > 5_000_000:
        raise MaterialSheetError("Spreadsheet export exceeds the 5 MB safety limit")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MaterialSheetError("Spreadsheet export must be UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text))
    headers = set(reader.fieldnames or [])
    if not REQUIRED_COLUMNS.issubset(headers):
        missing = ", ".join(sorted(REQUIRED_COLUMNS - headers))
        raise MaterialSheetError(f"Spreadsheet is missing required columns: {missing}")
    rows = []
    for row_number, raw in enumerate(reader, start=2):
        title = (raw.get("Link Text") or "").strip()
        url = (raw.get("Internal URL Reference") or "").strip()
        rows.append(MaterialSheetRow(row_number=row_number, title=title, url=url))
    return rows


def _normalize_name(value: str) -> str:
    value = value.lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def _event_boundary(title: str) -> str | None:
    normalized = _normalize_name(title)
    for alias in sorted(EVENT_ALIASES, key=len, reverse=True):
        if normalized == alias or normalized.startswith(f"{alias} "):
            return EVENT_ALIASES[alias]
    return None


def _is_global(title: str) -> bool:
    normalized = _normalize_name(title)
    return (
        not normalized
        or title.startswith("[![")
        or any(normalized.startswith(value) for value in GLOBAL_TITLES)
        or "certificate" in normalized
        or "conflict blocks" in normalized
    )


def _division_hint(title: str) -> str | None:
    match = re.search(r"\b(?:division|div)\s*([bc])\b", title, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _purpose(title: str, url: str) -> str:
    value = f"{title} {url}".lower()
    if "certificate" in value:
        return "certificate"
    if "schedule" in value or "conflict blocks" in value:
        return "season_schedule"
    if "rule change" in value or "correction" in value or "clarification" in value:
        return "rules_corrections"
    if "answer" in value and ("key" in value or "sheet" in value):
        return "answer_key_and_rubric"
    if "sample test" in value or "example test" in value or "invitational test" in value:
        return "sample_test"
    if "station" in value:
        return "sample_test"
    if "questions & answers" in value or "questions and answers" in value:
        return "faq"
    if "results" in value:
        return "tournament_results"
    if "youtu" in value or "video" in value:
        return "official_video"
    if any(
        token in value
        for token in (
            "powerpoint",
            "slides",
            "notes",
            "guide",
            "worksheet",
            "chart",
            "table",
            "flow chart",
            "diagram",
            "textbook",
            "reaction sheet",
        )
    ):
        return "training_handout"
    return "reference_material"


def _canonical_material_url(value: str) -> str:
    if not value:
        raise MaterialSheetError("missing_url")
    try:
        canonical = canonicalize_url(value)
    except (DiscoveryError, ValueError) as exc:
        raise MaterialSheetError("invalid_url") from exc
    parsed = urlparse(canonical)
    if parsed.hostname not in ALLOWED_HOSTS:
        raise MaterialSheetError("unapproved_domain")
    if re.search(r"\.pdf\d+$", parsed.path, re.IGNORECASE):
        raise MaterialSheetError("malformed_pdf_url")
    return canonical


def prepare_materials(rows: list[MaterialSheetRow]) -> list[PreparedMaterial]:
    prepared = []
    current_event: str | None = None
    for row in rows:
        boundary = _event_boundary(row.title)
        if boundary:
            current_event = boundary
        event_name = boundary or current_event
        if _is_global(row.title):
            event_name = None
        issue = None
        try:
            canonical = _canonical_material_url(row.url)
        except MaterialSheetError as exc:
            canonical = None
            issue = str(exc)
        if not row.title:
            issue = issue or "missing_title"
        if event_name is None:
            issue = issue or "global_or_unmapped_resource"
        prepared.append(
            PreparedMaterial(
                row_number=row.row_number,
                title=row.title,
                original_url=row.url,
                canonical_url=canonical,
                event_name=event_name,
                division_hint=_division_hint(row.title),
                purpose=_purpose(row.title, row.url),
                issue=issue,
            )
        )
    return prepared


def _publisher(url: str) -> str:
    host = urlparse(url).hostname or ""
    return "Science Olympiad, Inc." if host.endswith("soinc.org") else "Science Olympiad TV"


def _row_fingerprint(row: PreparedMaterial) -> str:
    value = f"{row.title}\n{row.canonical_url}\n{row.event_name}\n{row.purpose}"
    return hashlib.sha256(value.encode()).hexdigest()


def import_materials(
    db: Session,
    payload: bytes,
    *,
    season: int,
    spreadsheet_id: str,
    gid: str = "0",
    apply: bool = False,
    include_global: bool = False,
) -> MaterialImportReport:
    rows = parse_material_csv(payload)
    prepared = prepare_materials(rows)
    source_fingerprint = hashlib.sha256(payload).hexdigest()
    report = MaterialImportReport(
        mode="apply" if apply else "dry_run",
        season=season,
        spreadsheet_id=spreadsheet_id,
        gid=gid,
        source_fingerprint=source_fingerprint,
        rows_seen=len(rows),
    )
    events = db.scalars(select(Event).where(Event.season == season)).all()
    events_by_name: dict[str, list[Event]] = {}
    for event in events:
        events_by_name.setdefault(_normalize_name(event.name), []).append(event)
    universe = f"sheet-{spreadsheet_id[:12]}-gid{gid}-season{season}"
    season_resources = db.scalar(
        select(Event).where(
            Event.slug == f"season-resources-bc-{season}",
            Event.season == season,
        )
    )

    for row in prepared:
        summary = {"row": row.row_number, "title": row.title, "url": row.original_url}
        if row.issue == "global_or_unmapped_resource":
            if not include_global:
                report.skipped_global.append({**summary, "reason": row.issue})
                continue
            if season_resources is None:
                report.rejected.append(
                    {
                        **summary,
                        "reason": "season_resources_event_not_registered",
                        "season": season,
                    }
                )
                continue
            matching_events = [season_resources]
        else:
            matching_events = []
        if row.issue and row.issue != "global_or_unmapped_resource":
            report.rejected.append({**summary, "reason": row.issue})
            continue
        if not matching_events:
            matching_events = events_by_name.get(_normalize_name(row.event_name or ""), [])
            if row.division_hint:
                matching_events = [
                    event for event in matching_events if event.division == row.division_hint
                ]
        if not matching_events:
            report.rejected.append(
                {
                    **summary,
                    "reason": "event_not_registered_for_target_season",
                    "event": row.event_name,
                    "season": season,
                    "division_hint": row.division_hint,
                }
            )
            continue

        report.rows_ready += 1
        source = db.scalar(select(Source).where(Source.url == row.canonical_url))
        if source is None:
            report.sources_created += 1
            if apply:
                source = Source(
                    url=row.canonical_url,
                    title=row.title,
                    publisher=_publisher(row.canonical_url or ""),
                    rights_status=RightsStatus.LINK_ONLY.value,
                    license_name="unknown",
                    approved=False,
                )
                db.add(source)
                db.flush()
        else:
            metadata = dict(source.metadata_json or {})
            provenance = {
                "spreadsheet_id": spreadsheet_id,
                "gid": gid,
                "row_number": row.row_number,
                "row_fingerprint": _row_fingerprint(row),
                "source_fingerprint": source_fingerprint,
                "target_season": season,
            }
            if metadata.get("material_sheet_import") == provenance:
                report.sources_existing += 1
            else:
                report.sources_updated += 1
                if apply:
                    metadata["material_sheet_import"] = provenance
                    source.metadata_json = metadata
                    db.add(source)
        if not apply and source is None:
            # A dry run cannot query mappings for a source that does not exist yet.
            report.mappings_created += len(matching_events)
            continue
        if apply and source is not None:
            metadata = dict(source.metadata_json or {})
            metadata["material_sheet_import"] = {
                "spreadsheet_id": spreadsheet_id,
                "gid": gid,
                "row_number": row.row_number,
                "row_fingerprint": _row_fingerprint(row),
                "source_fingerprint": source_fingerprint,
                "target_season": season,
            }
            source.metadata_json = metadata
            db.flush()
        for event in matching_events:
            mapping = db.scalar(
                select(EventSourceMap).where(
                    EventSourceMap.event_id == event.id,
                    EventSourceMap.source_id == source.id,
                    EventSourceMap.purpose == row.purpose,
                    EventSourceMap.source_universe_version == universe,
                )
            )
            if mapping:
                report.mappings_existing += 1
                continue
            report.mappings_created += 1
            if apply:
                db.add(
                    EventSourceMap(
                        event_id=event.id,
                        source_id=source.id,
                        purpose=row.purpose,
                        source_tier=0,
                        required=False,
                        required_artifact_types=["metadata"],
                        source_universe_version=universe,
                        freshness_minutes=43_200,
                        reviewed=True,
                        notes=(
                            f"Imported from Google Sheet gid={gid}, row={row.row_number}; "
                            "validated link-only material; not approved for generation"
                        ),
                    )
                )
    if apply:
        db.commit()
    return report


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
