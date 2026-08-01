"""Check that a course claiming to be published actually has something to serve.

Two states are incoherent and neither is currently detected:

  * a course marked `published` whose lessons are all unreviewed, so a student who navigates
    to it is shown an empty course — worse than either "here is the content" or "this is not
    ready", because it reads as a broken product rather than an honest one;
  * a course marked `published` with no published `ContentRelease`, so nothing records what
    the catalog is actually serving under that name.

This reports both and changes nothing by default. The catalog-wide count is large and
reducing it is a content decision, not a script's call; `--fix-empty` is provided for the
narrow case of a course whose lessons were *just* moved to draft by a pipeline step.

    PYTHONPATH=. python -m scripts.audit_release_consistency
    PYTHONPATH=. python -m scripts.audit_release_consistency --event rocks-and-minerals-b --fix-empty
"""
from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    ContentRelease, Course, Event, Lesson, LessonSkill, Skill,
)

SERVABLE = {"published"}


def rows(db, event_slug: str | None = None) -> list[dict]:
    query = select(Course)
    if event_slug:
        event = db.scalar(select(Event).where(Event.slug == event_slug))
        if not event:
            raise SystemExit(f"unknown event {event_slug!r}")
        query = query.where(Course.event_id == event.id)
    out = []
    for course in db.scalars(query.order_by(Course.slug)).all():
        skill_ids = [s.id for s in db.scalars(select(Skill).where(
            Skill.course_id == course.id, Skill.status != "withdrawn")).all()]
        lesson_ids = sorted({link.lesson_id for link in db.scalars(select(LessonSkill).where(
            LessonSkill.skill_id.in_(skill_ids))).all()}) if skill_ids else []
        lessons = db.scalars(select(Lesson).where(
            Lesson.id.in_(lesson_ids))).all() if lesson_ids else []
        servable = [l for l in lessons if l.status in SERVABLE]
        release = db.scalar(select(ContentRelease).where(
            ContentRelease.course_id == course.id,
            ContentRelease.status == "published"))
        problems = []
        if course.status == "published" and not servable:
            problems.append("published_but_serves_nothing")
        if course.status == "published" and release is None:
            problems.append("published_without_a_release")
        out.append({"course": course, "slug": course.slug, "status": course.status,
                    "lessons": len(lessons), "servable": len(servable),
                    "has_release": release is not None, "problems": problems})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Course/release consistency")
    ap.add_argument("--event", default=None)
    ap.add_argument("--fix-empty", action="store_true",
                    help="move a published course that serves nothing to student_preview")
    args = ap.parse_args()

    with SessionLocal() as db:
        report = rows(db, args.event)
        if not report:
            raise SystemExit("FAIL: no courses matched. An empty population is not a pass.")

        empty = [r for r in report if "published_but_serves_nothing" in r["problems"]]
        no_release = [r for r in report if "published_without_a_release" in r["problems"]]

        print("=" * 74)
        print("COURSE / RELEASE CONSISTENCY")
        print("=" * 74)
        print(f"courses audited                      : {len(report)}")
        print(f"published but serving no lesson      : {len(empty)}")
        print(f"published without a content release  : {len(no_release)}")
        if empty:
            print("-" * 74)
            for row in empty[:12]:
                print(f"  {row['slug'][:46]:48} lessons={row['lessons']:3} servable=0")
            if len(empty) > 12:
                print(f"  ... and {len(empty) - 12} more")

        if args.fix_empty and empty:
            for row in empty:
                row["course"].status = "student_preview"
            db.commit()
            print("-" * 74)
            print(f"moved {len(empty)} course(s) to student_preview — they claim nothing "
                  f"they cannot serve")
        elif empty:
            print("-" * 74)
            print("nothing changed. re-run with --fix-empty to correct the courses listed")
        print("=" * 74)


if __name__ == "__main__":
    main()
