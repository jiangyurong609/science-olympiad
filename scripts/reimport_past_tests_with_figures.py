"""Re-import every published past test that still serves no figures.

Each source runs through the ordinary importer, which now recovers figures (Pillow present,
label matching fixed, caption binding fixed). The importer publishes its new exam directly, so
every run must end one of two ways — never with the old and new exam published side by side:

  swap    — the new exam kept everything (all items gradeable, at least as many items as the
            old exam, every referenced figure actually downloadable) and the old exam has no
            student attempts. Old exam retired, audited, reversible.
  held    — any check failed, or a student has attempted the old exam. The NEW exam is
            unpublished for review and the old one keeps serving, so nothing regresses
            silently.

Usage: [--only <exam_id,...>] [--limit N]
"""
import argparse
import os
import sys
import traceback

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.models.entities import AuditLog, Event, EventSourceMap, Exam, RawArtifact, Source, SourceSnapshot
from app.services import media_storage
from app.services.past_test_import import import_past_test
from app.services.scoring import is_gradeable


def _safe_db_label() -> str:
    from urllib.parse import urlparse
    parsed = urlparse(os.environ.get("DATABASE_URL", ""))
    return f"{parsed.hostname or '?'}:{parsed.port or '?'}/{(parsed.path or '').lstrip('/')}"


def targets(db):
    rows = db.execute(text("""
      select e.id as exam_id, e.title, (e.blueprint::jsonb->>'exam_source_id')::int as src_id,
        (select count(*) from exam_items i where i.exam_id=e.id) as items,
        (select count(*) from attempts a where a.exam_id=e.id) as attempts
      from exams e
      where e.published and e.blueprint::jsonb->>'exam_source_id' is not null
        and not exists (select 1 from exam_items i where i.exam_id=e.id
             and jsonb_array_length(coalesce(i.snapshot::jsonb->'assets','[]'::jsonb)) > 0)
      order by e.id
    """)).mappings().all()
    return rows


def verify_new_exam(db, exam_id):
    """The checks that decide a swap. Returns (ok, detail dict)."""
    rows = db.execute(text(
        "select snapshot::jsonb as s from exam_items where exam_id=:e").bindparams(e=exam_id)
    ).mappings().all()
    total = len(rows)
    gradeable = sum(1 for r in rows if is_gradeable(
        r["s"].get("question_type"), r["s"].get("answer_spec")))
    keys, with_img = set(), 0
    for r in rows:
        assets = r["s"].get("assets") or []
        if assets:
            with_img += 1
        for a in assets:
            k = a.get("storage_key") or a.get("key")
            if k:
                keys.add(k)
    bad_keys = []
    for k in sorted(keys):
        try:
            data = media_storage.download_media(k)
            if not data:
                bad_keys.append(k)
        except Exception:
            bad_keys.append(k)
    return {"total": total, "gradeable": gradeable, "with_img": with_img,
            "figures": len(keys), "bad_figures": bad_keys}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    db = SessionLocal()
    print(f"database: {_safe_db_label()}", flush=True)

    only = {int(x) for x in args.only.split(",") if x.strip()}
    rows = targets(db)
    if only:
        rows = [r for r in rows if r["exam_id"] in only]
    if args.limit:
        rows = rows[:args.limit]
    print(f"{len(rows)} published figure-less past tests to re-import\n", flush=True)

    swapped, held, failed = [], [], []
    for n, row in enumerate(rows, 1):
        old_id, src_id = row["exam_id"], row["src_id"]
        print(f"[{n}/{len(rows)}] exam {old_id} · src {src_id} · {row['title'][:64]}", flush=True)
        try:
            source = db.get(Source, src_id)
            has_bytes = db.scalar(
                select(RawArtifact.id).join(SourceSnapshot, RawArtifact.snapshot_id == SourceSnapshot.id)
                .where(SourceSnapshot.source_id == src_id))
            if not has_bytes:
                print("    no retained PDF bytes — backfill has not covered it; skipping", flush=True)
                failed.append((old_id, "no_bytes"))
                continue
            mapping = db.scalar(select(EventSourceMap).where(EventSourceMap.source_id == src_id))
            event = db.get(Event, mapping.event_id)

            result = import_past_test(db, event, source, build=True, commit=True)
            new_id = result.get("exam_id")
            if not new_id:
                print(f"    importer produced no exam ({result.get('questions_created')} questions)", flush=True)
                failed.append((old_id, "no_exam"))
                continue

            v = verify_new_exam(db, new_id)
            attempts = row["attempts"]
            reasons = []
            if v["gradeable"] < v["total"]:
                reasons.append(f"ungradeable {v['total'] - v['gradeable']}")
            if v["total"] < row["items"]:
                reasons.append(f"items {v['total']} < old {row['items']}")
            if v["bad_figures"]:
                reasons.append(f"unreadable figures {len(v['bad_figures'])}")
            if attempts:
                reasons.append(f"old exam has {attempts} attempt(s)")

            new_exam = db.get(Exam, new_id)
            old_exam = db.get(Exam, old_id)
            if not reasons:
                old_exam.published = False
                db.add(AuditLog(actor_user_id=None, action="past_test_superseded_by_reimport",
                                entity_type="exam", entity_id=str(old_id),
                                details={"reason": "re-imported with figures recovered",
                                         "replaced_by": new_id,
                                         "reversible": "republish this exam, unpublish the new one"}))
                db.commit()
                swapped.append((old_id, new_id, v))
                print(f"    swapped -> exam {new_id}: {v['total']} items ({row['items']} before), "
                      f"{v['with_img']} with figures, {v['figures']} distinct figures verified", flush=True)
            else:
                new_exam.published = False
                db.add(AuditLog(actor_user_id=None, action="past_test_reimport_held_for_review",
                                entity_type="exam", entity_id=str(new_id),
                                details={"replaces": old_id, "reasons": reasons}))
                db.commit()
                held.append((old_id, new_id, reasons, v))
                print(f"    HELD exam {new_id} ({'; '.join(reasons)}) — old exam keeps serving", flush=True)
        except Exception as exc:
            db.rollback()
            print(f"    FAILED: {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc(file=sys.stdout)
            failed.append((old_id, f"{type(exc).__name__}"))

    print(f"\n=== done: swapped {len(swapped)} · held {len(held)} · failed {len(failed)}", flush=True)
    for old_id, new_id, v in swapped:
        print(f"  swap {old_id} -> {new_id} · {v['with_img']}/{v['total']} items carry a figure", flush=True)
    for old_id, new_id, reasons, v in held:
        print(f"  held {new_id} (replaces {old_id}): {'; '.join(reasons)}", flush=True)
    for old_id, why in failed:
        print(f"  failed {old_id}: {why}", flush=True)


if __name__ == "__main__":
    main()
