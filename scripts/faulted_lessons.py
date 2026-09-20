"""Lessons an automated review faulted AT THEIR CURRENT VERSION, read from the database.

The repair loop first decided this by counting fault lines in the reviewer's stdout, which is
wrong in the one case that matters: the reviewer skips a lesson whose current version it has
already judged, so a course with four standing rejections and nothing new to read prints no
fault lines at all. The loop called that clean and stopped. A gate that cannot fail is not a
gate, and this one reported success precisely when there was nothing left to try.

The decisions are in the database either way. Asking it is both correct and independent of how
much the last review happened to print.

A second state matters just as much and is easy to mistake for success: a lesson REPAIRED
since the last review carries no decision at its new version at all. It is not faulted, and it
is also not cleared — nothing has read what is there now. Counting only faults, a course whose
every lesson had just been rewritten would report zero and look finished.

    DATABASE_URL=... PYTHONPATH=. python -m scripts.faulted_lessons --event solar-system-b-2027
    # prints one line per lesson; exit 0 if any are faulted OR unreviewed, 1 if all are clear
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import and_, select

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, ReviewDecision

# `student_visibility.automated_review_rejected` blocks on "reject" and nothing else, so a
# "revise" is advice about a lesson that is already fit to serve. Treating both as blocking
# made this gate stricter than the invariant the platform actually enforces, and left the
# hardening loop unable to ever finish: the video "event strategy" lessons carry revisions,
# come from outside any blueprint, and cannot be repaired by the loop that was waiting on them.
BLOCKING = ("reject", "rejected")
ADVISORY = ("revise",)
FAULTED = BLOCKING + ADVISORY


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


def unreviewed(db, event_slug: str) -> list[str]:
    """Lessons with no automated decision at the version they are currently serving."""
    event = db.scalar(select(Event).where(Event.slug == event_slug))
    if event is None:
        raise SystemExit(f"unknown event {event_slug!r}")
    judged = set(db.scalars(
        select(Lesson.slug)
        .join(ReviewDecision, and_(
            ReviewDecision.entity_type == "lesson",
            ReviewDecision.entity_id == Lesson.id,
            ReviewDecision.entity_version == Lesson.current_version,
        ))
        .where(Lesson.event_id == event.id, ReviewDecision.stage == "automated")
    ).all())
    everything = set(db.scalars(
        select(Lesson.slug).where(Lesson.event_id == event.id)).all())
    return sorted(everything - judged)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--quiet", action="store_true",
                        help="print only the count of lessons not yet cleared")
    args = parser.parse_args()
    with SessionLocal() as db:
        rows = faulted(db, args.event)
        pending = unreviewed(db, args.event)
    blocking = [r for r in rows if r[1] in BLOCKING]
    advisory = [r for r in rows if r[1] in ADVISORY]
    if args.quiet:
        # The count the loop tests: what actually stops this course being served.
        print(len(blocking) + len(pending))
    else:
        for slug, decision, notes in blocking:
            print(f"{decision:10} {slug}  {notes}")
        for slug in pending:
            print(f"{'unreviewed':10} {slug}  (no decision at its current version)")
        for slug, decision, notes in advisory:
            print(f"{'advisory':10} {slug}  {notes}")
    sys.exit(0 if (blocking or pending) else 1)


if __name__ == "__main__":
    main()
