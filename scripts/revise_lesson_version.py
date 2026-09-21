"""Turn a corrected lesson's text into a NEW version, so review sees what students will see.

Review decisions are keyed to (lesson, version), and so is the automated reject that hides a
lesson from students. Editing a version's content in place therefore does two wrong things
at once: the reviewer skips it as "already reviewed", and whatever decision was recorded
now describes text it never saw. Two Solar System lessons were rejected for real errors,
corrected in place, and stayed both hidden and unreviewable — the reject still attached.

This copies the current version's content (already corrected) into version N+1, carries its
evidence links, and bumps `current_version`. If the lesson was published as labelled
unreviewed practice FOR the version being replaced, that same disposition is re-granted for
the new one and logged: it is the same decision about the same lesson, following the text,
and it is not an approval. Nothing here writes a review decision of any kind.

    DATABASE_URL=... python -m scripts.revise_lesson_version --event X --lesson a,b --reason "..."
"""
from __future__ import annotations

import argparse
import copy

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import AuditLog, Event, Lesson, LessonVersion
from app.services.student_visibility import DISPOSITION_UNREVIEWED_PRACTICE


def revise(db, event: Event, slug: str, reason: str) -> str:
    lesson = db.scalar(select(Lesson).where(Lesson.event_id == event.id, Lesson.slug == slug))
    if lesson is None:
        return f"{slug}: no such lesson"
    current = db.scalar(select(LessonVersion).where(
        LessonVersion.lesson_id == lesson.id, LessonVersion.version == lesson.current_version))
    if current is None:
        return f"{slug}: no current version"
    new_number = max(v.version for v in db.scalars(select(LessonVersion).where(
        LessonVersion.lesson_id == lesson.id)).all()) + 1
    db.add(LessonVersion(
        lesson_id=lesson.id, version=new_number, content=copy.deepcopy(current.content),
        claim_ids=list(current.claim_ids or []), citations=copy.deepcopy(current.citations or []),
        review_status="ai_draft",
    ))
    previous = lesson.current_version
    lesson.current_version = new_number
    followed = False
    if (lesson.disposition == DISPOSITION_UNREVIEWED_PRACTICE
            and lesson.disposition_version == previous):
        lesson.disposition_version = new_number
        followed = True
    db.add(AuditLog(
        actor_user_id=None, action="lesson.corrected_version_created",
        entity_type="lesson", entity_id=str(lesson.id),
        details={"event": event.slug, "lesson": slug, "from_version": previous,
                 "to_version": new_number, "reason": reason,
                 "unreviewed_practice_disposition_followed": followed,
                 "review_decision_written": False}))
    return f"{slug}: v{previous} -> v{new_number}  (disposition followed: {followed})"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--lesson", required=True, help="comma-separated slugs")
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == args.event))
        for slug in [s.strip() for s in args.lesson.split(",") if s.strip()]:
            print(revise(db, event, slug, args.reason))
        db.commit()


if __name__ == "__main__":
    main()
