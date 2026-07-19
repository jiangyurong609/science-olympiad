"""Remove the redundant thin `foundations-*` lessons so the deep `auto-` course
is what students actually see.

Every event now has a systematic 8-lesson `auto-` course, but a leftover single
thin non-`auto-` "Foundations" lesson sorts first and is featured as THE course
— the "5 slides, nothing to learn" a student sees. This deletes those thin
lessons, but ONLY for events that still have a full (>=6 lesson) `auto-` course,
so no event is ever left without a course.

Runs against TARGET_URL (default: local sqlite). For prod, start the proxy and
pass the prod DEST-style URL as TARGET_URL.

Usage:
  python -m scripts.remove_thin_lessons --yes                    # local
  TARGET_URL='postgresql+psycopg2://...@127.0.0.1:5434/soplat' \
  python -m scripts.remove_thin_lessons --yes                    # prod
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

import app.models.entities  # noqa: F401
from app.models.entities import Event, Lesson, LessonVersion


def main() -> None:
    if "--yes" not in sys.argv:
        raise SystemExit("Refusing to run without --yes.")
    url = os.environ.get("TARGET_URL", "sqlite:///./science_olympiad.db")
    engine = create_engine(url, pool_pre_ping=True)
    removed = 0
    with Session(engine) as db:
        for event in db.scalars(select(Event)).all():
            auto = db.scalar(select(func.count()).select_from(Lesson).where(
                Lesson.event_id == event.id, Lesson.slug.like("auto-%")))
            if auto < 6:
                continue  # never strip an event down to no course
            thin_ids = db.scalars(select(Lesson.id).where(
                Lesson.event_id == event.id, ~Lesson.slug.like("auto-%"))).all()
            if not thin_ids:
                continue
            db.execute(delete(LessonVersion).where(LessonVersion.lesson_id.in_(thin_ids)))
            db.execute(delete(Lesson).where(Lesson.id.in_(thin_ids)))
            removed += len(thin_ids)
            print(f"  {event.slug}: removed {len(thin_ids)} thin lesson(s)")
        db.commit()
    print(f"Removed {removed} thin foundations lessons from {url.split('@')[-1]}.")


if __name__ == "__main__":
    main()
