"""Sync generated (`auto-`) courses for specific events into prod.

Replaces the destination's `auto-` lessons for each named event with the local
ones (lessons + their versions), matching events by SLUG so it is robust to id
drift, and nulling cross-references (concept_id, claim_ids) that may not exist on
the destination. Never touches manually-authored (non-`auto-`) lessons.

Prereqs: start the Cloud SQL proxy (scripts/prod_db_proxy.sh).

Usage:
  DEST_URL='postgresql+psycopg2://soplat_app:<PASS>@127.0.0.1:5434/soplat' \
  python -m scripts.sync_lessons_to_prod --yes robot-tour-c meteorology
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

import app.models.entities  # noqa: F401
from app.models.entities import Event, Lesson, LessonVersion


def _denul(value):
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _denul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_denul(v) for v in value]
    return value


def main() -> None:
    if "--yes" not in sys.argv:
        raise SystemExit("Refusing to run without --yes.")
    slugs = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not slugs:
        raise SystemExit("Pass one or more event slugs to sync.")
    source_url = os.environ.get("SOURCE_URL", "sqlite:///./science_olympiad.db")
    dest_url = os.environ.get("DEST_URL")
    if not dest_url:
        raise SystemExit("Set DEST_URL to the target (prod) database URL.")

    src = create_engine(source_url)
    dst = create_engine(dest_url, pool_pre_ping=True, pool_recycle=300)
    with Session(src) as ssrc, Session(dst) as sdst:
        for slug in slugs:
            local_event = ssrc.scalar(select(Event).where(Event.slug == slug))
            prod_event = sdst.scalar(select(Event).where(Event.slug == slug))
            if not local_event or not prod_event:
                print(f"  {slug}: SKIP (missing local or prod event)")
                continue
            local_lessons = ssrc.scalars(select(Lesson).where(
                Lesson.event_id == local_event.id, Lesson.slug.like("auto-%")
            ).order_by(Lesson.sequence)).all()
            bundles = [(L, ssrc.scalars(select(LessonVersion).where(
                LessonVersion.lesson_id == L.id)).all()) for L in local_lessons]

            old_ids = sdst.scalars(select(Lesson.id).where(
                Lesson.event_id == prod_event.id, Lesson.slug.like("auto-%"))).all()
            if old_ids:
                sdst.execute(delete(LessonVersion).where(LessonVersion.lesson_id.in_(old_ids)))
                sdst.execute(delete(Lesson).where(Lesson.id.in_(old_ids)))
                sdst.flush()
            for L, versions in bundles:
                new_lesson = Lesson(
                    event_id=prod_event.id, concept_id=None, slug=L.slug,
                    title=_denul(L.title), summary=_denul(L.summary), status=L.status,
                    current_version=L.current_version, sequence=L.sequence,
                    estimated_minutes=L.estimated_minutes, created_at=L.created_at,
                )
                sdst.add(new_lesson)
                sdst.flush()
                for V in versions:
                    sdst.add(LessonVersion(
                        lesson_id=new_lesson.id, version=V.version,
                        content=_denul(V.content), claim_ids=[],
                        citations=_denul(V.citations), review_status=V.review_status,
                        created_at=V.created_at,
                    ))
            sdst.commit()
            print(f"  {slug}: replaced {len(old_ids)} prod auto-lessons with {len(bundles)} local")
    print("Lesson sync complete.")


if __name__ == "__main__":
    main()
