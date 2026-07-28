"""Extract English YouTube captions into versioned source snapshots.

Dry-run is the default. Use --apply only after reviewing the report. Channel
URLs and videos without English captions are reported, never silently skipped.
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, EventSourceMap, Source
from app.services.video_transcripts import TranscriptError, ingest_youtube_source, youtube_video_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2027)
    parser.add_argument("--source-id", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.source_id:
            sources = [db.get(Source, args.source_id)]
        else:
            event_ids = select(Event.id).where(Event.season == args.season)
            source_ids = select(EventSourceMap.source_id).where(EventSourceMap.event_id.in_(event_ids)).distinct()
            sources = db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
        sources = [s for s in sources if s and ("youtube" in s.url or "youtu.be" in s.url)]
        if args.limit:
            sources = sources[:args.limit]
        report = {"mode": "apply" if args.apply else "dry_run", "season": args.season,
                  "seen": len(sources), "transcribed": 0, "unchanged": 0, "failed": []}
        for source in sources:
            if not youtube_video_id(source.url):
                report["failed"].append({"source_id": source.id, "title": source.title, "reason": "channel_or_unsupported_url"})
                continue
            try:
                result = ingest_youtube_source(db, source, commit=args.apply)
                if result["status"] == "transcribed": report["transcribed"] += 1
                else: report["unchanged"] += 1
                print(json.dumps(result))
                if not args.apply: db.rollback()
            except TranscriptError as exc:
                db.rollback()
                report["failed"].append({"source_id": source.id, "title": source.title, "reason": str(exc)})
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
