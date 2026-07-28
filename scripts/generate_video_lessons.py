"""Generate draft (never student-visible) lessons for transcript snapshots."""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, EventSourceMap, Source, SourceSnapshot
from app.services.video_lesson_generation import generate_video_lesson


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2027)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        events = db.scalars(select(Event).where(Event.season == args.season).order_by(Event.id)).all()
        made = []
        for event in events:
            mappings = db.scalars(select(EventSourceMap).where(EventSourceMap.event_id == event.id)).all()
            for mapping in mappings:
                source = db.get(Source, mapping.source_id)
                snap = db.scalar(select(SourceSnapshot).where(SourceSnapshot.source_id == mapping.source_id).order_by(SourceSnapshot.id.desc()))
                if not source or not snap or snap.metadata_json.get("kind") != "youtube_transcript":
                    continue
                if args.limit is not None and len(made) >= args.limit:
                    break
                try:
                    lesson = generate_video_lesson(db, event, source, commit=args.apply)
                    if lesson: made.append({"event": event.slug, "lesson_id": lesson.id, "status": lesson.status})
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    print(json.dumps({"event": event.slug, "error": str(exc)[:240]}))
            if args.limit is not None and len(made) >= args.limit: break
        print(json.dumps({"mode": "apply" if args.apply else "dry_run", "drafts": made}, indent=2))


if __name__ == "__main__":
    main()
