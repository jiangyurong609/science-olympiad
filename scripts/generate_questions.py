"""Generate grounded practice questions from downloaded materials.

Usage:
  python -m scripts.generate_questions --event <event_id> [--count 15]
  python -m scripts.generate_questions --all-missing [--count 15] [--min-chars 1500]
      # generate for every event that has materials with text but no questions yet
"""
from __future__ import annotations

import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, EventSourceMap, Question, Source, SourceSnapshot
from app.services.question_generation import generate_from_material


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _richest_material(db, event_id: int, min_chars: int) -> tuple[Source, int] | None:
    best, best_len = None, 0
    for m in db.scalars(select(EventSourceMap).where(EventSourceMap.event_id == event_id)).all():
        snap = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_id == m.source_id
        ).order_by(SourceSnapshot.id.desc()))
        n = len((snap.extracted_text or "").strip()) if snap else 0
        if n > best_len:
            best, best_len = db.get(Source, m.source_id), n
    return (best, best_len) if best and best_len >= min_chars else None


def _events_with_questions(db) -> set[int]:
    events = set()
    for q in db.scalars(select(Question).where(Question.status == "draft")).all():
        if (q.generation_provenance or {}).get("import_kind") in {"past_test", "generated_from_material"}:
            events.add(q.event_id)
    return events


def main() -> None:
    count = int(_arg("--count", "15"))
    min_chars = int(_arg("--min-chars", "1500"))
    with SessionLocal() as db:
        if "--event" in sys.argv:
            targets = [int(_arg("--event"))]
        elif "--all-missing" in sys.argv:
            have = _events_with_questions(db)
            linked = {m.event_id for m in db.scalars(select(EventSourceMap).where(
                EventSourceMap.notes == "auto-linked ingested material"
            )).all()}
            targets = sorted(linked - have)
        else:
            raise SystemExit(__doc__)

        print(f"Generating for {len(targets)} event(s), count={count}…\n")
        made = 0
        for i, event_id in enumerate(targets, start=1):
            event = db.get(Event, event_id)
            picked = _richest_material(db, event_id, min_chars)
            if not picked:
                print(f"[{i}/{len(targets)}] skip {event.slug}: no material with >= {min_chars} chars")
                continue
            source, n = picked
            try:
                qs = generate_from_material(db, event, source, count=count)
                made += len(qs)
                print(f"[{i}/{len(targets)}] {event.slug:26} +{len(qs)} q from "
                      f"'{source.title[:36]}' ({n} chars)")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                print(f"[{i}/{len(targets)}] FAIL {event.slug}: {str(exc)[:90]}")
        print(f"\nDone: generated {made} questions.")


if __name__ == "__main__":
    main()
