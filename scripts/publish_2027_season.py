"""Put the 2027 season in front of students, and take the wrong season out.

Two halves, and the second matters as much as the first. Publishing the new Dynamic Planet
freshwater course achieves nothing if the 2026 oceanography course keeps sitting beside it under
the same name, and a student revising Meteorology from a climate course is worse off than one who
knows there is no current course yet.

What gets published and how:
  Lessons become `published` with disposition `unreviewed_practice` and `disposition_version` set
  to the version that decision covers. `student_visibility` treats that as an explicit per-lesson
  decision to let unreviewed content be READ while being reported as unreviewed. It is not an
  approval: no editor or SME ReviewDecision is written, because no editor or SME has read these,
  and inventing those rows is the one thing this project has decided it will never do.

What does NOT get published:
  The authored exams. `machine_practice` — the class that would let a machine-written paper be
  started — is earned by clearing an independent blind solver, an independent verifier and
  grounding in approved claims. These papers cleared the structural validator only, so
  `classify_exam` earns them `unreviewed_practice`, which refuses new attempts. Publishing them
  would put a paper in the catalog that no student can start. They stay held until the gates run.

What gets demoted:
  Courses whose subject is not what 2027 tests move to `prior_season_practice`: kept, reachable,
  badged "Prior season", listed on the archive surface, and no longer presented as current-season
  coverage. Division B rotations are verified against the 2027 Division B rules manual. Division C
  has no manual here, so only events whose topic is demonstrably division-shared are touched, and
  the reason is recorded per event.

Usage: [--apply]
"""
from __future__ import annotations

import argparse

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.models.entities import AuditLog, Event, Lesson, LessonVersion
from app.services import lesson_blocks
from app.services.student_visibility import DISPOSITION_UNREVIEWED_PRACTICE

# Events whose newly authored 2027 course should go live, with the event status they end in.
PUBLISH_EVENTS = [
    ("dynamic-planet-b-2027", "current"),
    ("roller-coaster-b-2027", "current"),
]

# (event id, why this course is not 2027 coverage). Division B verified against the manual.
DEMOTE = [
    (12, "2026 course teaches oceanography; 2027 tests Earth's fresh waters, now covered by the "
         "new 2027 course"),
    (7, "2026 course teaches the nervous system; 2027 tests respiratory, digestive and immune "
        "systems"),
    (13, "2026 course teaches everyday weather and climate; 2027 tests severe weather and storms"),
    (16, "2026 course is a solar system survey; 2027 tests habitability and astrobiology"),
    (11, "2026 course teaches freshwater macroinvertebrates; 2027 tests marine and estuary "
         "systems and coral reef organisms"),
    # Division C: no Division C manual was read. These are events whose rotating topic is
    # demonstrably shared across divisions — our own past-test corpus shows the 2026 Dynamic
    # Planet B and C papers both testing oceanography and the 2025 B and C papers both testing
    # glaciers — and the Anatomy & Physiology rotation chart is published for "B & C" together.
    (30, "Anatomy & Physiology rotation is published for B and C together; 2027 tests "
         "respiratory, digestive and immune systems"),
    (36, "Dynamic Planet's topic is shared across divisions (2026 B and C papers both "
         "oceanography, 2025 both glaciers); 2027 tests fresh waters and no Division C "
         "freshwater course exists yet"),
    (34, "Water Quality's rotating topic is shared across divisions; 2027 tests marine and "
         "estuary systems and coral reef organisms"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    changed = 0

    print("== 1. publish authored 2027 lessons ==")
    for slug, end_status in PUBLISH_EVENTS:
        event = db.scalar(select(Event).where(Event.slug == slug))
        if not event:
            print(f"  !! no event {slug}")
            continue
        lessons = db.scalars(select(Lesson).where(Lesson.event_id == event.id)
                            .order_by(Lesson.sequence)).all()
        publishable, blocked = [], []
        for lesson in lessons:
            if lesson.status == "published" and lesson.disposition:
                continue                    # already live and already dispositioned
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version))
            if version is None:
                blocked.append((lesson, "no current version"))
                continue
            # The hard gate: a lesson whose checkpoint cannot be answered correctly can never be
            # finished, so serving it promises work that cannot be completed.
            if lesson_blocks.ungradeable_checkpoints(version.content or []):
                blocked.append((lesson, "has an ungradeable checkpoint"))
                continue
            publishable.append(lesson)
        print(f"  {event.slug}: {len(publishable)} to publish, {len(blocked)} blocked, "
              f"event {event.season_status!r} -> {end_status!r}")
        for lesson, why in blocked:
            print(f"     BLOCKED [{lesson.id}] {lesson.title[:46]} — {why}")
        if args.apply:
            for lesson in publishable:
                lesson.status = "published"
                # Labelled, readable, and explicitly NOT approved. `disposition_version` pins the
                # decision to the text it was made about, so a later edit does not inherit it.
                lesson.disposition = DISPOSITION_UNREVIEWED_PRACTICE
                lesson.disposition_version = lesson.current_version
                db.add(AuditLog(
                    actor_user_id=None, action="lesson.published_as_unreviewed_practice",
                    entity_type="lesson", entity_id=str(lesson.id),
                    details={"event": event.slug, "version": lesson.current_version,
                             "review_status": "ai_draft",
                             "reason": "published on the operator's instruction as labelled "
                                       "unreviewed practice; no editor or SME has read it and "
                                       "no approval was recorded"}))
            if event.season_status != end_status:
                db.add(AuditLog(
                    actor_user_id=None, action="event.opened_to_students_for_season",
                    entity_type="event", entity_id=str(event.id),
                    details={"event": event.slug, "previous_season_status": event.season_status,
                             "new_season_status": end_status, "season": 2027,
                             "published_lessons": len(publishable)}))
                event.season_status = end_status
                event.active = True
        changed += len(publishable)

    print("\n== 2. demote courses whose subject is not what 2027 tests ==")
    for event_id, why in DEMOTE:
        event = db.get(Event, event_id)
        if not event:
            print(f"  !! no event {event_id}")
            continue
        if event.season_status == "prior_season_practice":
            print(f"  ok   [{event_id}] {event.name} {event.division} already prior-season")
            continue
        counts = db.execute(text("""
            select (select count(*) from lessons l
                    where l.event_id = :e and l.status = 'published') lessons,
                   (select count(*) from exams x
                    where x.event_id = :e and x.published) exams
        """), {"e": event_id}).first()
        print(f"  demote [{event_id}] {event.name} {event.division} "
              f"({counts.lessons} lessons, {counts.exams} exams kept and badged)")
        print(f"         {why}")
        if args.apply:
            db.add(AuditLog(
                actor_user_id=None, action="event.demoted_topic_not_in_season",
                entity_type="event", entity_id=str(event_id),
                details={"event": event.name, "division": event.division,
                         "previous_season_status": event.season_status, "season_audited": 2027,
                         "reason": why, "lessons_retained": counts.lessons,
                         "exams_retained": counts.exams}))
            event.season_status = "prior_season_practice"
        changed += 1

    if args.apply:
        db.commit()
        print(f"\ncommitted {changed} change(s)")
    else:
        db.rollback()
        print(f"\ndry run — {changed} change(s) would be applied")


if __name__ == "__main__":
    main()
