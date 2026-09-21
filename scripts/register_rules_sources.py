"""Make each event's 2027 rules section a citable source for that event's course.

The author writes only from source passages, and the rules manual was never one. For most
subjects that costs little: the science is in the open references. For the events that are
ABOUT their rules it costs the course. Write It Do It's scoring (points per piece for size,
colour, location, orientation and connection; correct pieces beyond a wrong connection still
count; no drawings; 25 minutes to write, 20 to build) exists only in the manual, so the author
reported every one of those as "no supporting passage" and refused a whole lesson rather than
teach it uncited. Experimental Design's timing and penalties were the same.

This registers `docs/season_2027/manual_scope/<event>.md` — the event's own section, already
extracted from the 2027 Division B manual — as a Source with a snapshot, and maps it to the
2027 event. `extract_source_passages --apply` then turns it into passages like any other
source. The URL scheme is `rules://`, deliberately not `local://`, which marks past tests and
is excluded from teaching evidence.

    DATABASE_URL=... python -m scripts.register_rules_sources --event write-it-do-it-b-2027
    DATABASE_URL=... python -m scripts.register_rules_sources --all --apply
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, EventSourceMap, Source, SourceSnapshot

SCOPE_DIR = Path("docs/season_2027/manual_scope")
SEASON = 2027
URL_PREFIX = "rules://2027/B/"
PUBLISHER = "Science Olympiad, Inc."
LICENSE = "2027 Division B Rules Manual, event section (rules facts used with attribution)"


def rules_text(path: Path) -> str:
    """The event section itself, without the internal-audit preamble at the top of the file."""
    lines = path.read_text().splitlines()
    body = [l for l in lines if not l.startswith("#")
            and "internal course" not in l and "authoritative statement" not in l
            and "Consult the official manual" not in l and "Extracted from the official" not in l]
    return "\n".join(body).strip()


def register(db, event: Event, path: Path, apply: bool) -> str:
    url = URL_PREFIX + path.stem
    text = rules_text(path)
    if len(text) < 400:
        return f"{event.slug}: {path.name} too short ({len(text)} chars)"
    source = db.scalar(select(Source).where(Source.url == url))
    if source is None:
        if not apply:
            return f"{event.slug}: would register {url} ({len(text)} chars)"
        source = Source(url=url, title=f"2027 Division B Rules — {event.name}",
                        rights_status="fact_grounding_allowed", approved=True,
                        license_name=LICENSE, publisher=PUBLISHER)
        db.add(source)
        db.flush()
    digest = hashlib.sha256(text.encode()).hexdigest()
    snapshot = db.scalar(select(SourceSnapshot).where(SourceSnapshot.source_id == source.id)
                         .order_by(SourceSnapshot.id.desc()))
    if snapshot is None or snapshot.content_hash != digest:
        if apply:
            db.add(SourceSnapshot(source_id=source.id, final_url=url,
                                  content_hash=digest, extracted_text=text))
            source.extracted_text = text
            source.content_hash = digest
    mapped = db.scalar(select(EventSourceMap).where(
        EventSourceMap.event_id == event.id, EventSourceMap.source_id == source.id))
    if mapped is None and apply:
        db.add(EventSourceMap(
            event_id=event.id, source_id=source.id, purpose="fact_grounding",
            source_tier=0, required=True, required_artifact_types=["parsed_text"],
            source_universe_version="rules_2027", reviewed=True,
            notes="the event's own 2027 rules section"))
    if apply:
        db.flush()
    return f"{event.slug}: {'registered' if apply else 'ok'} {url} ({len(text)} chars)"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        for path in sorted(SCOPE_DIR.glob("*.md")):
            slug = f"{path.stem}-b-{SEASON}"
            if args.event and slug != args.event:
                continue
            if not (args.all or args.event):
                continue
            event = db.scalar(select(Event).where(Event.slug == slug))
            if event is None:
                print(f"{slug}: no such event — skipped")
                continue
            print(register(db, event, path, args.apply))
        if args.apply:
            db.commit()


if __name__ == "__main__":
    main()
