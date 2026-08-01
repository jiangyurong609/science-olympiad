"""Phase 0d — give every exam an explicit student-exposure disposition.

No exam may sit in an implicit "published" state. Each one is classified by what it actually
contains: fully human-reviewed items make it `reviewed`; anything else becomes
`unreviewed_practice`, which stays visible and resumable but is labelled and refuses new
attempts. Empty exams are withdrawn.

Dry-run by default. Read-only until --apply.

    PYTHONPATH=. python -m scripts.disposition_exams
    PYTHONPATH=. python -m scripts.disposition_exams --apply
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Attempt, Exam
from app.services import student_visibility as sv


def plan(db) -> list[dict]:
    rows = []
    for exam in db.scalars(select(Exam).order_by(Exam.id)).all():
        current = sv.exam_disposition(exam)
        earned = sv.classify_exam(db, exam)
        unreviewed = sv.unreviewed_item_ids(db, list(exam.question_ids or []))
        in_flight = db.scalar(select(Attempt).where(
            Attempt.exam_id == exam.id, Attempt.status == "in_progress",
        ).limit(1))
        rows.append({
            "exam_id": exam.id, "title": exam.title[:48], "release_class": exam.release_class,
            "published": exam.published, "from": current, "to": earned,
            "items": len(exam.question_ids or []), "unreviewed": len(unreviewed),
            "has_in_flight_attempt": bool(in_flight),
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Assign explicit exam dispositions")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with SessionLocal() as db:
        rows = plan(db)
        counts = Counter(r["to"] for r in rows)
        implicit = sum(1 for r in rows if r["from"] == sv.DISPOSITION_PENDING)
        print("=" * 72)
        print(f"exams: {len(rows)} | currently without an explicit disposition: {implicit}")
        for k, v in counts.most_common():
            print(f"  -> {k:24} {v}")
        at_risk = [r for r in rows if r["has_in_flight_attempt"] and r["to"] != sv.DISPOSITION_REVIEWED]
        print(f"in-flight attempts on exams being restricted: {len(at_risk)} "
              f"(these stay resumable by design)")
        print("=" * 72)

        if args.apply:
            for row in rows:
                db.get(Exam, row["exam_id"]).disposition = row["to"]
            db.commit()
            remaining = sum(1 for e in db.scalars(select(Exam)).all()
                            if sv.exam_disposition(e) == sv.DISPOSITION_PENDING)
            print(f"APPLIED. exams still without an explicit disposition: {remaining}")


if __name__ == "__main__":
    main()
