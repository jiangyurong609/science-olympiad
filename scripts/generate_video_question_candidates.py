"""Generate non-servable assessment candidates from test-oriented video transcripts."""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, EventSourceMap, Source, SourceSnapshot
from app.services.video_question_generation import generate_video_question_candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2027)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        events = db.scalars(select(Event).where(Event.season == args.season)).all()
        targets = []
        for event in events:
            for mapping in db.scalars(select(EventSourceMap).where(EventSourceMap.event_id == event.id)).all():
                source = db.get(Source, mapping.source_id)
                snap = db.scalar(select(SourceSnapshot).where(SourceSnapshot.source_id == mapping.source_id).order_by(SourceSnapshot.id.desc()))
                if source and snap and snap.metadata_json.get("kind") == "youtube_transcript" and "example test" in source.title.lower():
                    targets.append((event, source))
        report = {"mode": "apply" if args.apply else "dry_run", "targets": len(targets), "candidates": 0, "events": []}
        if not args.apply:
            report["events"] = [{"event": event.slug, "source": source.title, "count": args.count} for event, source in targets]
            print(json.dumps(report, indent=2))
            return
        for event, source in targets:
            try:
                rows = generate_video_question_candidates(db, event, source, count=args.count, commit=args.apply)
                report["candidates"] += len(rows)
                report["events"].append({"event": event.slug, "source": source.title, "count": len(rows)})
                if not args.apply: db.rollback()
            except Exception as exc:  # noqa: BLE001
                db.rollback(); report["events"].append({"event": event.slug, "source": source.title, "error": str(exc)[:240]})
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
