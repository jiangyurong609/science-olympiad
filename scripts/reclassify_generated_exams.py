"""Stop labelling machine-written exams as transcribed past tests.

`imported_practice` means "transcribed from a real tournament paper", and the catalog shows it
as a Past Test. 49 exams carried that class while every one of their questions was generated —
304 of them by the 2026 catalog pass (gpt-4o-mini), the rest by the competition-item prompts —
titled "Grounded Practice Exam" or "Competition-Style Mock". A student reading "Past Test"
reasonably assumes a real tournament wrote it.

An exam keeps `imported_practice` only if EVERY question on it was imported from a past test
(`generation_provenance.import_kind == "past_test"`). Anything else is `machine_practice`.
Only the stored label changes: whether a student may start the exam is decided by its
disposition, which this does not touch.

    DATABASE_URL=... python -m scripts.reclassify_generated_exams
    DATABASE_URL=... python -m scripts.reclassify_generated_exams --apply
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Exam, Question

IMPORTED = "imported_practice"
MACHINE = "machine_practice"


def is_transcribed(question: Question | None) -> bool:
    return question is not None and (question.generation_provenance or {}).get("import_kind") == "past_test"


def reclassify(db, apply: bool) -> Counter:
    stats: Counter[str] = Counter()
    for exam in db.scalars(select(Exam).where(Exam.release_class == IMPORTED)):
        ids = exam.question_ids or []
        questions = db.scalars(select(Question).where(Question.id.in_(ids))).all() if ids else []
        if ids and len(questions) == len(ids) and all(is_transcribed(q) for q in questions):
            stats["kept_transcribed"] += 1
            continue
        if not ids:
            stats["empty_left_alone"] += 1
            continue
        stats["relabelled_machine"] += 1
        print(f"  {exam.id:>5}  {exam.title[:70]}")
        if apply:
            exam.release_class = MACHINE
    if apply:
        db.commit()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        print(dict(reclassify(db, args.apply)))


if __name__ == "__main__":
    main()
