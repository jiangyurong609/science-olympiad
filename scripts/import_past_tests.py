"""Import a downloaded past test into structured Questions + a mock Exam.

Usage:
  python -m scripts.import_past_tests --source <exam_source_id> [--key <key_source_id>] \
      [--event <event_id>] [--feedback-mode after_submit|per_question] \
      [--include-image-dependent] [--dry-run]

--dry-run parses with the LLM and prints the structured items WITHOUT writing to
the database. Without --dry-run it creates Question rows and a takeable Exam.
"""
from __future__ import annotations

import json
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, EventSourceMap, Source
from app.services.past_test_import import import_past_test


def _arg(flag: str, default: str | None = None) -> str | None:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _resolve_event(db, exam_source_id: int, explicit: str | None) -> Event:
    if explicit:
        event = db.get(Event, int(explicit))
        if not event:
            raise SystemExit(f"Event {explicit} not found")
        return event
    mapping = db.scalar(select(EventSourceMap).where(EventSourceMap.source_id == exam_source_id))
    if not mapping:
        raise SystemExit("Could not resolve event for this source; pass --event <id>")
    return db.get(Event, mapping.event_id)


def _filename(url: str) -> str:
    from urllib.parse import unquote
    return unquote(url.rsplit("/", 1)[-1])


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a.lower(), b.lower()):
        if x != y:
            break
        n += 1
    return n


def batch() -> None:
    """Import every un-imported sample-test PDF that maps to an event, pairing
    answer keys by filename and skipping docs that yield too few questions."""
    from app.models.entities import DiscoveredResource, Exam
    from app.services.past_test_import import import_past_test

    feedback_mode = _arg("--feedback-mode", "after_submit")
    min_questions = int(_arg("--min-questions", "3"))
    limit = int(_arg("--limit", "0"))

    with SessionLocal() as db:
        ingested = db.scalars(select(DiscoveredResource).where(
            DiscoveredResource.status == "ingested"
        )).all()
        is_key = lambda r: any(k in r.canonical_url.lower() for k in ("key", "answer"))
        tests = [r for r in ingested
                 if any(k in r.canonical_url.lower() for k in ("sample", "test", "exam")) and not is_key(r)]
        keys = [r for r in ingested if is_key(r)]
        done = {(e.blueprint or {}).get("exam_source_id")
                for e in db.scalars(select(Exam).where(Exam.release_class == "past_test")).all()}

        # resolve event per source and pair keys within the same event
        def event_id_of(source_id):
            m = db.scalar(select(EventSourceMap).where(EventSourceMap.source_id == source_id))
            return m.event_id if m else None

        key_event = {k.source_id: event_id_of(k.source_id) for k in keys}
        pending = [(r, event_id_of(r.source_id)) for r in tests if r.source_id not in done]
        pending = [(r, db.get(Event, eid)) for r, eid in pending if eid is not None]
        if limit:
            pending = pending[:limit]
        print(f"Batch importing {len(pending)} past tests "
              f"(min_questions={min_questions}, feedback_mode={feedback_mode})…\n")

        totals = {"imported": 0, "skipped": 0, "failed": 0, "questions": 0}
        for i, (resource, event) in enumerate(pending, start=1):
            exam_source = db.get(Source, resource.source_id)
            # Pair an answer key only when the same-event filename overlap has a single
            # unambiguous winner (>=6 chars). On a tie (e.g. TestB vs KeyB/KeyC sharing
            # the same prefix), skip pairing rather than risk attaching the wrong key.
            key_source = None
            cands = sorted(
                ((k, _common_prefix_len(_filename(resource.canonical_url), _filename(k.canonical_url)))
                 for k in keys if key_event.get(k.source_id) == event.id),
                key=lambda c: c[1], reverse=True,
            )
            if cands and cands[0][1] >= 6 and (len(cands) == 1 or cands[0][1] > cands[1][1]):
                key_source = db.get(Source, cands[0][0].source_id)
            label = _filename(resource.canonical_url)
            try:
                res = import_past_test(
                    db, event, exam_source, key_source, feedback_mode=feedback_mode,
                    min_questions=min_questions,
                )
                if res.get("skipped"):
                    totals["skipped"] += 1
                    print(f"[{i}/{len(pending)}] skip  {label} ({res['parsed_items']} items, too few usable)")
                else:
                    totals["imported"] += 1
                    totals["questions"] += res["questions_created"]
                    key_note = f" +key {_filename(key_source.url)}" if key_source else ""
                    print(f"[{i}/{len(pending)}] OK    {event.slug}: {label} -> "
                          f"exam {res['exam_id']} ({res['questions_created']} q){key_note}")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                totals["failed"] += 1
                print(f"[{i}/{len(pending)}] FAIL  {label}: {str(exc)[:90]}")
        print(f"\nDone: {totals['imported']} exams imported "
              f"({totals['questions']} questions), {totals['skipped']} skipped, {totals['failed']} failed.")


def main() -> None:
    if "batch" in sys.argv:
        batch()
        return
    if "--source" not in sys.argv:
        raise SystemExit(__doc__)
    exam_source_id = int(_arg("--source"))
    key_source_id = _arg("--key")
    feedback_mode = _arg("--feedback-mode", "after_submit")
    dry_run = "--dry-run" in sys.argv
    include_image = "--include-image-dependent" in sys.argv

    with SessionLocal() as db:
        exam_source = db.get(Source, exam_source_id)
        if not exam_source:
            raise SystemExit(f"Source {exam_source_id} not found")
        key_source = db.get(Source, int(key_source_id)) if key_source_id else None
        event = _resolve_event(db, exam_source_id, _arg("--event"))
        print(f"Parsing '{exam_source.title}' for {event.name} ({event.division}) "
              f"[feedback_mode={feedback_mode}, dry_run={dry_run}]…")
        result = import_past_test(
            db, event, exam_source, key_source,
            feedback_mode=feedback_mode, include_image_dependent=include_image,
            build=not dry_run, commit=not dry_run,
        )
        print(f"\nParsed {result['parsed_items']} items "
              f"({result['image_dependent_items']} image-dependent).")
        if dry_run:
            for item in result["items"]:
                flag = " [IMG]" if item.get("image_dependent") else ""
                ans = item.get("reference_answer") or item.get("acceptance_notes") or "(no answer)"
                print(f"\n  {item.get('section') or ''} #{item.get('label')}{flag} "
                      f"[{item.get('question_type')}]")
                print(f"    Q: {str(item.get('stem'))[:220]}")
                print(f"    A: {str(ans)[:160]}")
        else:
            print(f"Created {result['questions_created']} questions; exam_id={result['exam_id']}")


if __name__ == "__main__":
    main()
