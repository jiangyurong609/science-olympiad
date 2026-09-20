"""Measure the shape of a subject's own past tests, so a generated paper can match it.

`FORMATS` in `build_season_exam` holds two shapes, and both were derived from Dynamic Planet
papers. They are good shapes — a real invitational and a real state paper — but they are not
THIS subject's shape, and the difference is not cosmetic. Disease Detectives' own past tests
run 111 items at 1 point each with a tail of 3-, 4- and 6-point short answers; Rocks &
Minerals runs stations. Handing a student a 30-item multiple-choice paper to prepare for
either one trains them for a test they will not sit.

This reads the imported past tests already in the database for an event — papers that were
transcribed from real tournaments — and reports what they actually contain: how many items,
the mix of question types, the points distribution, and how much of the paper is short answer.

It measures; it does not generate. The output is meant to be read by a person deciding what a
practice paper for this subject should look like, and to seed a format spec.

    DATABASE_URL=... python -m scripts.profile_past_exams --event disease-detectives-b
    DATABASE_URL=... python -m scripts.profile_past_exams --all
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Exam, Question

IMPORTED = "imported_practice"


def profile(db, base_slug: str) -> dict:
    """Every past test held for this subject, in any season, as one profile."""
    events = db.scalars(select(Event).where(Event.slug.like(f"{base_slug}%"))).all()
    if not events:
        return {"subject": base_slug, "error": "no such event"}
    exams = db.scalars(select(Exam).where(
        Exam.event_id.in_([e.id for e in events]),
        Exam.release_class == IMPORTED)).all()
    exams = [x for x in exams if (x.question_ids or [])]
    if not exams:
        return {"subject": base_slug, "past_tests": 0,
                "note": "no past test is held for this subject; a generated paper has no "
                        "measured shape of its own to match"}

    counts = [len(x.question_ids) for x in exams]
    types: Counter[str] = Counter()
    points: Counter[float] = Counter()
    for exam in exams:
        qs = db.scalars(select(Question).where(Question.id.in_(exam.question_ids))).all()
        for q in qs:
            types[q.question_type] += 1
            points[float((q.answer_spec or {}).get("points") or 1)] += 1
    total = sum(types.values()) or 1
    return {
        "subject": base_slug,
        "past_tests": len(exams),
        "items_per_paper": {"median": int(statistics.median(counts)),
                            "min": min(counts), "max": max(counts)},
        "question_types": {k: f"{v} ({100 * v / total:.0f}%)" for k, v in types.most_common()},
        "points": {str(k): v for k, v in sorted(points.items())},
        "short_answer_share": f"{100 * types.get('short_answer', 0) / total:.0f}%",
        "papers": sorted(re.sub(r"^.*Past Test:\s*", "", x.title)[:52] for x in exams),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", help="base slug, e.g. disease-detectives-b")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.all:
            bases = sorted({re.sub(r"-(19|20)\d{2}$", "", e.slug)
                            for e in db.scalars(select(Event)).all()
                            if e.division == "B"})
        else:
            bases = [args.event]
        for base in bases:
            result = profile(db, base)
            if result.get("past_tests"):
                print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
