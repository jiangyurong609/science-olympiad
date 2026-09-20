"""Move a subject's imported past tests onto the event students are actually shown.

A subject's papers and a subject's course can end up on two different Event rows. The 2027
events were created as twins of the 2026 ones; whichever twin was `current` when
`import_local_tests --parse` ran is the one the resulting Exam rows point at. So the eight
subjects built first hold their past tests on the 2027 event, and every subject built later
holds them on a 2026 twin now marked `prior_season_practice` — Disease Detectives has nine
papers and its 2027 event has none.

Nothing is lost that way, but a student opening the current Disease Detectives sees a course
with no past paper beside it, which is the thing the papers were collected for. This moves
them, and it moves what hangs off them: an Exam's questions carry their own `event_id`, and
leaving those behind would put a paper on one event whose items belong to another.

It only ever moves `imported_practice` exams — real transcribed papers. Machine-authored
papers stay where they were written, because they were written against one event's concepts.

    DATABASE_URL=... python -m scripts.port_past_tests_to_current --event disease-detectives-b-2027
    DATABASE_URL=... python -m scripts.port_past_tests_to_current --all --apply
"""
from __future__ import annotations

import argparse
import json
import re

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Exam, Question

IMPORTED = "imported_practice"
CURRENT = "current"


def _base(slug: str) -> str:
    return re.sub(r"-(19|20)\d{2}$", "", slug)


def port(db, target: Event, apply: bool) -> dict:
    """Bring every past test held by a twin of `target` onto `target` itself."""
    twins = [e for e in db.scalars(select(Event).where(
        Event.slug.like(f"{_base(target.slug)}%"))).all()
        if e.id != target.id and e.division == target.division]
    moved, questions_moved, titles = 0, 0, []
    for twin in twins:
        for exam in db.scalars(select(Exam).where(Exam.event_id == twin.id,
                                                  Exam.release_class == IMPORTED)).all():
            if not (exam.question_ids or []):
                continue
            titles.append(f"{twin.slug}: {exam.title[:60]}")
            moved += 1
            if not apply:
                continue
            exam.event_id = target.id
            for question in db.scalars(select(Question).where(
                    Question.id.in_(exam.question_ids))).all():
                if question.event_id != target.id:
                    question.event_id = target.id
                    questions_moved += 1
    if apply:
        db.commit()
    return {"event": target.slug, "exams_moved": moved,
            "questions_repointed": questions_moved, "papers": titles}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event")
    parser.add_argument("--all", action="store_true",
                        help="every event whose season_status is 'current'")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.all:
            targets = db.scalars(select(Event).where(
                Event.season_status == CURRENT).order_by(Event.slug)).all()
        else:
            targets = [db.scalar(select(Event).where(Event.slug == args.event))]
        for target in targets:
            if target is None:
                raise SystemExit("no such event")
            result = port(db, target, args.apply)
            if result["exams_moved"]:
                print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
