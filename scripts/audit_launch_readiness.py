"""What a student would actually find, event by event, if we launched today.

Every other audit here measures a phase gate. This one measures the product: pick an event the
way a student would, and ask whether there is a course to learn from and an exam to take. It
reports per event and refuses to average — "82% ready" is meaningless when a student lands on
one event and finds nothing.

Four things a student needs, in the order they need them:

  1. **lessons they can open** — published *and* student-visible. A published lesson nobody
     reviewed and that carries no `unreviewed_practice` disposition is invisible, so the
     published count on its own overstates the catalog badly.
  2. **lessons of a sensible length** — the plan's target is 5–12 minutes. A 25-minute wall of
     prose is the thing that makes people stop.
  3. **video** — the pilot proved the pipeline; everything else has none.
  4. **an exam they can start** — this is where the catalog is emptiest, and the number that
     decides whether "launch" means anything.

    PYTHONPATH=. python -m scripts.audit_launch_readiness
    DATABASE_URL=<prod> PYTHONPATH=. python -m scripts.audit_launch_readiness --top 20
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Event, Exam, Lesson, LessonVersion, Question, User, VideoRender, VideoStoryboard,
)
from app.services import lesson_blocks
from app.services import student_visibility as sv

TARGET_MIN, TARGET_MAX = 5, 12
WORDS_PER_MINUTE = 130


def reading_minutes(content: list) -> float:
    words = sum(len(lesson_blocks.block_text(b).split()) if hasattr(lesson_blocks, "block_text")
                else 0 for b in content or [])
    return round(words / WORDS_PER_MINUTE, 1)


def audit() -> dict:
    probe = User(id=-1, email="launch@invalid", full_name="Launch probe", role="student")
    rows = []
    totals: Counter[str] = Counter()

    with SessionLocal() as db:
        from app.services.course_quality import block_text

        events = db.scalars(select(Event).where(Event.active.is_(True))
                            .order_by(Event.slug)).all()
        lessons_by_event: dict[int, list[Lesson]] = {}
        for lesson in db.scalars(select(Lesson)).all():
            lessons_by_event.setdefault(lesson.event_id, []).append(lesson)
        versions = {(v.lesson_id, v.version): v for v in db.scalars(select(LessonVersion)).all()}
        boards_by_lesson: dict[int, VideoStoryboard] = {}
        for board in db.scalars(select(VideoStoryboard)).all():
            boards_by_lesson[board.lesson_id] = board
        renders_by_board: dict[int, list[VideoRender]] = {}
        for render in db.scalars(select(VideoRender)).all():
            renders_by_board.setdefault(render.storyboard_id, []).append(render)
        exams_by_event: dict[int, list[Exam]] = {}
        for exam in db.scalars(select(Exam)).all():
            exams_by_event.setdefault(exam.event_id, []).append(exam)
        items_by_event: dict[int, list[Question]] = {}
        for question in db.scalars(select(Question)).all():
            items_by_event.setdefault(question.event_id, []).append(question)

        for event in events:
            lessons = [l for l in lessons_by_event.get(event.id, [])
                       if l.status == "published"]
            openable, in_range, with_video, checkpoints = 0, 0, 0, 0
            for lesson in lessons:
                version = versions.get((lesson.id, lesson.current_version))
                if version is None:
                    continue
                if not sv.lesson_is_student_visible(db, probe, lesson, version):
                    continue
                openable += 1
                minutes = round(sum(len(block_text(b).split())
                                    for b in version.content or []) / WORDS_PER_MINUTE, 1)
                if TARGET_MIN <= minutes <= TARGET_MAX:
                    in_range += 1
                checkpoints += len(lesson_blocks.checkpoint_ids(version.content or []))
                board = boards_by_lesson.get(lesson.id)
                if board and any(r.status == "succeeded" and r.qa_status == "approved"
                                 for r in renders_by_board.get(board.id, [])):
                    with_video += 1

            items = items_by_event.get(event.id, [])
            ready_items = [q for q in items if sv.item_is_student_ready(q)]
            startable_exams = 0
            for exam in exams_by_event.get(event.id, []):
                allowed, _ = sv.can_start_new_attempt(db, exam)
                if allowed:
                    startable_exams += 1

            rows.append({
                "event": event.slug, "division": event.division or "",
                "published": len(lessons), "openable": openable,
                "in_range": in_range, "video": with_video,
                "checkpoints": checkpoints,
                "items": len(items), "ready_items": len(ready_items),
                "exams": len(exams_by_event.get(event.id, [])),
                "startable_exams": startable_exams,
            })
            totals["events"] += 1
            if openable:
                totals["events_with_something_to_read"] += 1
            if with_video:
                totals["events_with_video"] += 1
            if startable_exams:
                totals["events_with_a_startable_exam"] += 1
            if openable and startable_exams:
                totals["events_launch_complete"] += 1
            for key in ("published", "openable", "in_range", "video", "checkpoints",
                        "items", "ready_items", "exams", "startable_exams"):
                totals[key] += rows[-1][key]
    return {"rows": rows, "totals": totals}


def main() -> None:
    ap = argparse.ArgumentParser(description="What a student would find if we launched today")
    ap.add_argument("--top", type=int, default=15, help="worst-first rows to print")
    args = ap.parse_args()

    result = audit()
    rows, totals = result["rows"], result["totals"]
    print("=" * 92)
    print("LAUNCH READINESS — per event, worst first")
    print("=" * 92)
    print(f"  {'event':32} {'open':>5} {'5-12m':>6} {'vid':>4} {'chks':>5} "
          f"{'items':>6} {'ready':>6} {'exams':>6} {'start':>6}")
    worst = sorted(rows, key=lambda r: (r["openable"] > 0, r["startable_exams"] > 0,
                                        r["openable"]))
    for row in worst[:args.top]:
        print(f"  {row['event'][:32]:32} {row['openable']:>5} {row['in_range']:>6} "
              f"{row['video']:>4} {row['checkpoints']:>5} {row['items']:>6} "
              f"{row['ready_items']:>6} {row['exams']:>6} {row['startable_exams']:>6}")
    print("-" * 92)
    print(f"  events                                {totals['events']}")
    print(f"  …with a lesson a student can open     {totals['events_with_something_to_read']}")
    print(f"  …with QA-approved video               {totals['events_with_video']}")
    print(f"  …with an exam a student can start     {totals['events_with_a_startable_exam']}")
    print(f"  …ready to launch (both)               {totals['events_launch_complete']}")
    print("-" * 92)
    print(f"  lessons published {totals['published']}, openable {totals['openable']}, "
          f"within 5-12 min {totals['in_range']}, with video {totals['video']}")
    print(f"  checkpoints {totals['checkpoints']}")
    print(f"  items {totals['items']}, student-scoreable {totals['ready_items']}")
    print(f"  exams {totals['exams']}, startable {totals['startable_exams']}")
    print("=" * 92)


if __name__ == "__main__":
    main()
