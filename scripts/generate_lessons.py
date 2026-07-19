"""Generate grounded learning-path lessons for events from their materials.

Usage:
  python -m scripts.generate_lessons --event <event_id>
  python -m scripts.generate_lessons --all-missing [--limit N]
      # events that have text materials but no auto-generated lessons yet
"""
from __future__ import annotations

import sys

from sqlalchemy import select

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.entities import Event, EventSourceMap, Lesson
from app.services.lesson_generation import (
    event_has_generated_lessons, generate_lessons_for_event,
)


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main() -> None:
    limit = int(_arg("--limit")) if "--limit" in sys.argv else None
    with SessionLocal() as db:
        if "--event" in sys.argv:
            targets = [db.get(Event, int(_arg("--event")))]
        elif "--all-missing" in sys.argv or "--all" in sys.argv:
            linked = {m.event_id for m in db.scalars(select(EventSourceMap)).all()}
            targets = [db.get(Event, eid) for eid in sorted(linked) if db.get(Event, eid)]
            if "--all-missing" in sys.argv:
                targets = [e for e in targets if not event_has_generated_lessons(db, e)]
            else:
                # --all regenerates every event, but is RESUMABLE: skip events that
                # already have a deep (>=6 lesson) course from a prior run.
                def _lesson_count(eid):
                    return db.scalar(select(func.count()).select_from(Lesson).where(
                        Lesson.event_id == eid, Lesson.slug.like("auto-%"))) or 0
                targets = [e for e in targets if _lesson_count(e.id) < 6]
            if limit:
                targets = targets[:limit]
        else:
            raise SystemExit(__doc__)

        print(f"Generating lessons for {len(targets)} event(s)…\n")
        made = 0
        for i, event in enumerate(targets, start=1):
            try:
                lessons = generate_lessons_for_event(db, event)
                made += len(lessons)
                titles = ", ".join(lesson.title[:28] for lesson in lessons[:3])
                print(f"[{i}/{len(targets)}] {event.slug:26} +{len(lessons)} lessons: {titles}")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                print(f"[{i}/{len(targets)}] FAIL {event.slug}: {str(exc)[:90]}")
        print(f"\nDone: generated {made} lessons.")


if __name__ == "__main__":
    main()
