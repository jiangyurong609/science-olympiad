"""Phase 4 — rehearse a promotion and its rollback against real course content.

Unit tests prove the release machinery on fixtures. Fixtures are the case the author thought
of; a rehearsal is the case the catalog actually contains — a course with 24 lessons, 90
claims, 21 source dispositions, and whatever inconsistencies real data carries. Phase 4's gate
asks for "a rehearsed rollback restores the prior state", and this is that rehearsal.

Nothing is committed. Every step runs inside a transaction that is rolled back at the end, so
the rehearsal can be run against production data safely and repeatedly. What it verifies:

  1. a manifest can be built at all from the real course (a missing lesson version fails here);
  2. publishing writes it and moves the pointer;
  3. republishing identical content is idempotent rather than forking the release;
  4. changing content and republishing under the same version is refused;
  5. a second version supersedes the first without deleting it;
  6. rollback restores the earlier manifest *and* the version pointer;
  7. drift is detected when live content diverges from the active release.

    PYTHONPATH=. python -m scripts.rehearse_release --event rocks-and-minerals-b
"""
from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import ContentRelease, Course, Event, Lesson, User
from app.services.content_release import (
    ReleaseError, build_manifest, publish_release, release_drift, rollback_release,
)


class RehearsalFailure(AssertionError):
    """A step behaved differently on real content than the unit tests promised."""


def _check(label: str, condition: bool, detail: str = "") -> None:
    status = "ok  " if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        raise RehearsalFailure(f"{label}: {detail}")


def rehearse(event_slug: str) -> dict:
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == event_slug))
        if not event:
            raise SystemExit(f"unknown event {event_slug!r}")
        course = db.scalar(select(Course).where(Course.event_id == event.id))
        if not course:
            raise SystemExit(f"{event_slug} has no course")
        actor = db.scalar(select(User).where(User.role.in_(("editor", "admin"))))
        if not actor:
            raise SystemExit("no editor/admin account to attribute the rehearsal to")

        original_version = course.current_version
        original_status = course.status
        # plain values, not ORM objects: the verification below runs in a second session and
        # a detached instance cannot be refreshed
        course_slug = course.slug
        print(f"rehearsing on {course.slug} (version {original_version}, {original_status})")

        print("\n1. build a manifest from live content")
        manifest = build_manifest(db, course)
        counts = manifest["counts"]
        print(f"     {counts}")
        _check("manifest covers the course's lessons", counts["lessons"] > 0,
               f"{counts['lessons']} lessons")
        _check("every lesson pinned with a version",
               all(isinstance(row.get("version"), int) for row in manifest["lessons"]))
        _check("manifest carries a digest", bool(manifest["digest"]))

        first_lesson_id = manifest["lessons"][0]["id"]
        digest = manifest["digest"]

        print("\n2. publish")
        first = publish_release(db, actor, course, notes="rehearsal v1")
        _check("release is published", first.status == "published")
        _check("digest recorded", first.manifest.get("digest") == manifest["digest"])

        print("\n3. republish identical content")
        again = publish_release(db, actor, course, notes="rehearsal v1 again")
        _check("idempotent — same release row", again.id == first.id,
               f"first={first.id} again={again.id}")

        print("\n4. change content, republish under the same version")
        lesson = db.scalar(select(Lesson).where(
            Lesson.id == manifest["lessons"][0]["id"]))
        saved_title = lesson.title
        lesson.title = f"{saved_title} (rehearsal edit)"
        db.flush()
        refused = False
        try:
            publish_release(db, actor, course)
        except ReleaseError as exc:
            refused = "immutable" in str(exc)
        _check("refused — membership is immutable", refused)

        print("\n5. drift detection")
        drift = release_drift(db, course)
        _check("drift reported against the active release", drift["drifted"] is True,
               f"{drift['changes'][:2]}")

        print("\n6. publish a second version")
        course.current_version = original_version + 1
        second = publish_release(db, actor, course, notes="rehearsal v2")
        db.flush()
        _check("second release is active", second.status == "published")
        _check("first release superseded, not deleted", first.status == "superseded")

        print("\n7. roll back")
        restored = rollback_release(db, actor, course)
        db.flush()
        _check("restored the earlier release", restored.id == first.id)
        _check("version pointer moved back", course.current_version == original_version,
               f"now {course.current_version}")
        _check("the rolled-forward release is marked, not removed",
               second.status == "rolled_back")

        print("\n8. leave nothing behind")
        db.rollback()

    # A fresh session reads committed state. Asserting on the rolled-back session would only
    # prove that the in-memory objects were reset, which is not the claim being made.
    with SessionLocal() as db:
        course = db.scalar(select(Course).where(Course.slug == course_slug))
        lesson = db.scalar(select(Lesson).where(Lesson.id == first_lesson_id))
        _check("course version unchanged", course.current_version == original_version,
               f"{course.current_version}")
        _check("course status unchanged", course.status == original_status, course.status)
        _check("edited lesson title reverted", lesson.title == saved_title, lesson.title)
        _check("no release row was left behind",
               db.scalar(select(ContentRelease).where(
                   ContentRelease.course_id == course.id)) is None)
    return {"event": event_slug, "counts": counts, "digest": digest}


def main() -> None:
    ap = argparse.ArgumentParser(description="Rehearse release + rollback on real content")
    ap.add_argument("--event", required=True)
    args = ap.parse_args()

    print("=" * 74)
    print("PHASE 4 RELEASE REHEARSAL (nothing is committed)")
    print("=" * 74)
    result = rehearse(args.event)
    print("=" * 74)
    print(f"PASSED on {result['event']} — {result['counts']}")
    print("=" * 74)


if __name__ == "__main__":
    main()
