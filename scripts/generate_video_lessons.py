"""Generate draft (never student-visible) lessons for transcript snapshots."""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

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
        targets = []
        for event in events:
            mappings = db.scalars(select(EventSourceMap).where(EventSourceMap.event_id == event.id)).all()
            for mapping in mappings:
                source = db.get(Source, mapping.source_id)
                snap = db.scalar(select(SourceSnapshot).where(SourceSnapshot.source_id == mapping.source_id).order_by(SourceSnapshot.id.desc()))
                if not source or not snap or snap.metadata_json.get("kind") != "youtube_transcript":
                    continue
                if args.limit is not None and len(targets) >= args.limit:
                    break
                targets.append((event.id, event.slug, source.id))
            if args.limit is not None and len(targets) >= args.limit: break
        # The model calls are independent and slow; each worker owns its DB session.
        def work(item):
            event_id, event_slug, source_id = item
            with SessionLocal() as worker_db:
                try:
                    lesson = generate_video_lesson(worker_db, worker_db.get(Event, event_id), worker_db.get(Source, source_id), commit=args.apply)
                    return {"event": event_slug, "lesson_id": lesson.id, "status": lesson.status} if lesson else None
                except Exception as exc:  # noqa: BLE001
                    worker_db.rollback()
                    return {"event": event_slug, "error": str(exc)[:240]}
        made = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            for future in as_completed([pool.submit(work, item) for item in targets]):
                result = future.result()
                if result: made.append(result)
        print(json.dumps({"mode": "apply" if args.apply else "dry_run", "drafts": made}, indent=2))


if __name__ == "__main__":
    main()
