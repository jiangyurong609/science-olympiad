"""Lessons an automated review faulted AT THEIR CURRENT VERSION, read from the database.

The repair loop first decided this by counting fault lines in the reviewer's stdout, which is
wrong in the one case that matters: the reviewer skips a lesson whose current version it has
already judged, so a course with four standing rejections and nothing new to read prints no
fault lines at all. The loop called that clean and stopped. A gate that cannot fail is not a
gate, and this one reported success precisely when there was nothing left to try.

The decisions are in the database either way. Asking it is both correct and independent of how
much the last review happened to print.

    DATABASE_URL=... PYTHONPATH=. python -m scripts.faulted_lessons --event solar-system-b-2027
    # prints one slug per line; exit 0 if any are faulted, 1 if the course is clean
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import and_, select

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, ReviewDecision

FAULTED = ("reject", "rejected", "revise")


def faulted(db, event_slug: str) -> list[tuple[str, str, str]]:
    event = db.scalar(select(Event).where(Event.slug == event_slug))
    if event is None:
        raise SystemExit(f"unknown event {event_slug!r}")
    rows = db.execute(
        select(Lesson.slug, ReviewDecision.decision, ReviewDecision.notes)
        .join(ReviewDecision, and_(
            ReviewDecision.entity_type == "lesson",
            ReviewDecision.entity_id == Lesson.id,
            ReviewDecision.entity_version == Lesson.current_version,
        ))
        .where(
            Lesson.event_id == event.id,
            ReviewDecision.stage == "automated",
            ReviewDecision.decision.in_(FAULTED),
        )
        .order_by(Lesson.slug)
    ).all()
    # One row per lesson: a lesson re-reviewed at the same version keeps its latest verdict.
    seen: dict[str, tuple[str, str, str]] = {}
    for slug, decision, notes in rows:
        seen[slug] = (slug, decision, (notes or "")[:120])
    return list(seen.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--quiet", action="store_true", help="print only the count")
    args = parser.parse_args()
    with SessionLocal() as db:
        rows = faulted(db, args.event)
    if args.quiet:
        print(len(rows))
    else:
        for slug, decision, notes in rows:
            print(f"{decision:8} {slug}  {notes}")
    sys.exit(0 if rows else 1)


if __name__ == "__main__":
    main()
