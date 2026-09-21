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
from app.models.entities import AuditLog, Event, Lesson, LessonVersion, ReviewDecision
from app.services import lesson_blocks
from app.services.student_visibility import DISPOSITION_UNREVIEWED_PRACTICE

# Events whose newly authored 2027 course should go live, with the event status they end in.
CURRENT = "current"
PRIOR_SEASON = "prior_season_practice"
# Statuses that put an event in the catalog beside a current one. `prior_season_practice` is
# not here: it is badged and filed on the archive surface, which is where a demoted twin
# belongs and why the six subjects already demoted show as one row each.
CATALOG_VISIBLE_PEERS = {"current", "foundational"}

PUBLISH_EVENTS = [
    ("dynamic-planet-b-2027", "current"),
    ("roller-coaster-b-2027", "current"),
    # The six subjects built for 2027. Four had no course at all because their only course
    # taught the topic that rotated out; Botany and Thermodynamics had never had one. Each
    # carries a full blueprint course, grounded on measured open sources, taken through
    # review-and-repair until a round found nothing.
    ("meteorology-b-2027", "current"),
    ("solar-system-b-2027", "current"),
    ("anatomy-and-physiology-b-2027", "current"),
    ("water-quality-b-2027", "current"),
    ("botany-b-2027", "current"),
    ("thermodynamics-b-2027", "current"),
    # Disease Detectives: the course exists, and its nine past papers sit on the 2026 twin
    # because that twin was the current event when they were parsed. Publishing this event
    # is what lets `port_past_tests_to_current` bring them across.
    ("disease-detectives-b-2027", "current"),
    # Heredity: 31 lessons, one advisory finding standing and no rejections. Its 204-page
    # corpus was built for the 2027 topic list; the `genetics` domain it used to reach holds
    # eighteen pages.
    ("heredity-b-2027", "current"),
    # Food Science: the first build ran out of repair rounds with a rejection standing —
    # the pasteurization lesson contradicted itself on whether 135C UHT sterilizes. The
    # reviewer's finding was handed back as an explicit correction and a later round came
    # back clean. Published only after that, not after the loop merely stopped.
    ("food-science-b-2027", "current"),
    # Circuit Lab: 38 lessons over a corpus built to the manual's in-scope AND out-of-scope
    # lines, reviewed by an independent electrical engineer before publication, and cited
    # against zero past-test PDFs.
    ("circuit-lab-b-2027", "current"),
    # Rocks & Minerals keeps its name and its rotation, but the 2027 course is the one built
    # against the 2027 National Rocks and Minerals List, and the event was never grounded
    # until today. The 2026 twin is demoted below.
    ("rocks-and-minerals-b-2027", "current"),
    # Crime Busters: 26 lessons on the 2027 evidence list. The plastics lesson was rejected
    # three rounds running because its grounding passage gave polystyrene's range including
    # foamed grades; the rules name non-expanded PS, and the correction says so.
    ("crime-busters-b-2027", "current"),
    # Codebusters: 26 lessons. Two worked examples were wrong and caught by review (the ZEBRAS
    # read-out order and a keyword-alphabet mapping); both verified by hand before publishing.
    ("codebusters-b-2027", "current"),
    # Experimental Design: rebuilt on the official 2026 Division B checklist and CER guide,
    # which the first build never had. The guide's own slope (0.80 s/paperclip) does not
    # match its tabulated means (least squares gives ~0.96); the lessons use the data shown.
    ("experimental-design-b-2027", "current"),
    # Remote Sensing: 42 lessons on the 2027 Observable Earth topic (SAR/InSAR, radar
    # altimetry, elevation products). Three lessons were fixed by hand after repair kept
    # restoring grounded overstatements: clouds are bright in NIR (snow is not), geostationary
    # satellites cannot see the poles, altimeters do not measure wavelength or wind direction.
    ("remote-sensing-b-2027", "current"),
    # Write It Do It: 19 lessons. Its scoring exists only in the rules, so the event's 2027
    # rules section is a registered source (register_rules_sources); before that the author
    # refused the scoring lesson outright and drifted into number sequences.
    ("write-it-do-it-b-2027", "current"),
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
    # Publishing is per-season by default, and it publishes every draft that passes the gate.
    # Run while another listed course is mid-review and that course goes live half-repaired.
    # `--event` publishes one course and leaves the rest of the list alone.
    ap.add_argument("--event", help="publish only this event slug from PUBLISH_EVENTS")
    # A repair loop returns lessons to draft and writes a new version before reviewing it. A
    # publish run in that window would serve a version no reviewer has read. With this flag a
    # draft is published only when the automated reviewer approved THIS version, so a course
    # can be put back in front of students while a few of its lessons are still being repaired.
    ap.add_argument("--require-approval", action="store_true",
                    help="publish only lessons whose current version has an automated approve")
    args = ap.parse_args()
    if args.event and args.event not in {slug for slug, _ in PUBLISH_EVENTS}:
        raise SystemExit(f"{args.event} is not in PUBLISH_EVENTS")
    db = SessionLocal()
    changed = 0

    print("== 1. publish authored 2027 lessons ==")
    for slug, end_status in PUBLISH_EVENTS:
        if args.event and slug != args.event:
            continue
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
            if args.require_approval and db.scalar(select(ReviewDecision.decision).where(
                    ReviewDecision.entity_type == "lesson",
                    ReviewDecision.entity_id == lesson.id,
                    ReviewDecision.entity_version == lesson.current_version,
                    ReviewDecision.stage == "automated",
            ).order_by(ReviewDecision.id.desc()).limit(1)) not in {"approve", "approved"}:
                blocked.append((lesson, f"v{lesson.current_version} not approved by review yet"))
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

    # Publishing a 2027 event makes it `current`. Its 2026 twin keeps whatever status it
    # had, and if that status is catalog-visible the subject appears TWICE in the event
    # picker — "Disease Detectives · Div B · 2027" directly above "Disease Detectives · Div
    # B · 2026". The DEMOTE list below is hand-maintained and by event ID, so every newly
    # published subject has to be remembered separately; Rocks and Minerals was missed, then
    # Disease Detectives, and seven more subjects are queued behind them.
    #
    # This is structural instead: at most one catalog-visible event per (name, division),
    # which is the same invariant `consolidate_seasons` asserts after a merge. The recorded
    # reason says only what is actually known here — that a current event of this name exists
    # — and never claims a topic rotation, which is what the DEMOTE entries below are for and
    # which was verified against the manual one event at a time.
    print("\n== 1b. demote a twin that shares a name with a newly current event ==")
    published = {slug for slug, end_status in PUBLISH_EVENTS if end_status == CURRENT}
    for slug in sorted(published):
        current = db.scalar(select(Event).where(Event.slug == slug))
        if current is None or current.season_status != CURRENT:
            continue
        twins = [e for e in db.scalars(select(Event).where(
            Event.division == current.division)).all()
            if e.id != current.id
            and e.name.strip().lower() == current.name.strip().lower()
            and e.season_status in CATALOG_VISIBLE_PEERS]
        for twin in twins:
            print(f"  demote [{twin.id}] {twin.name} {twin.division} season={twin.season} "
                  f"({twin.season_status!r}) — {current.slug} is current under the same name")
            if args.apply:
                db.add(AuditLog(
                    actor_user_id=None, action="event.demoted_duplicate_catalog_entry",
                    entity_type="event", entity_id=str(twin.id),
                    details={"event": twin.name, "division": twin.division,
                             "previous_season_status": twin.season_status,
                             "new_season_status": PRIOR_SEASON,
                             "current_event": current.slug,
                             "reason": "another event with the same name and division is "
                                       "current, and the catalog shows both"}))
                twin.season_status = PRIOR_SEASON
                changed += 1

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
