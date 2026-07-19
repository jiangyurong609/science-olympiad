"""Sync ONLY question images to prod — no deletes, no schema/FK risk.

Pushes two things from the local SQLite into the target (prod) DB, matching by id:
  * questions.assets        (the specimen photos attach_specimen_images.py set)
  * exam_items.snapshot      (its frozen `assets` list, so exam runners show them)

Unlike mirror_db_to_prod.py this NEVER deletes rows — it only UPDATEs existing
rows that exist in both databases. Rows absent on prod are skipped (reported).

Prereqs: start the Cloud SQL proxy (scripts/prod_db_proxy.sh).

Usage:
  DEST_URL='postgresql+psycopg2://soplat_app:<PASS>@127.0.0.1:5434/soplat' \
  python -m scripts.sync_assets_to_prod --yes
"""
from __future__ import annotations

import os
import sys
import time

from sqlalchemy import bindparam, create_engine, select, text, update
from sqlalchemy.exc import OperationalError

import app.models.entities  # noqa: F401 — registers tables
from app.models.entities import ExamItem, Question

BATCH = 40


def _tx(engine, work, tries: int = 5, delay: float = 2.0):
    for attempt in range(tries):
        try:
            with engine.begin() as dc:
                return work(dc)
        except OperationalError:
            if attempt == tries - 1:
                raise
            time.sleep(delay)


def _denul(value):
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _denul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_denul(v) for v in value]
    return value


def main() -> None:
    if "--yes" not in sys.argv:
        raise SystemExit("Refusing to run without --yes.")
    source_url = os.environ.get("SOURCE_URL", "sqlite:///./science_olympiad.db")
    dest_url = os.environ.get("DEST_URL")
    if not dest_url:
        raise SystemExit("Set DEST_URL to the target (prod) database URL.")

    src = create_engine(source_url)
    dst = create_engine(dest_url, pool_pre_ping=True, pool_recycle=300)

    with src.connect() as sc:
        local_assets = {qid: (assets or []) for qid, assets in
                        sc.execute(select(Question.id, Question.assets))}
        local_snaps = {iid: snap for iid, snap in
                       sc.execute(select(ExamItem.id, ExamItem.snapshot)) if snap}

    # Only the questions worth diffing: those that have (or on prod had) an image.
    # Pull prod's currently-non-empty rows and union with local's non-empty rows.
    with dst.connect() as dc:
        prod_assets = {qid: (a or []) for qid, a in dc.execute(
            select(Question.id, Question.assets).where(Question.assets.isnot(None)))
            if a not in (None, [])}
        # Compare snapshots by the sub-fields this sync touches (`assets` and
        # `figure_missing`) — cheap, and works for past-test items whose
        # question_id is None. Postgres extracts the JSON paths server-side.
        prod_snap = {iid: (a or [], bool(fm)) for iid, a, fm in dc.execute(
            text("SELECT id, snapshot->'assets', snapshot->'figure_missing' FROM exam_items"))}

    candidate_qids = set(prod_assets) | {q for q, a in local_assets.items() if a}
    q_rows = []
    for qid in candidate_qids:
        want = local_assets.get(qid, [])
        if qid in local_assets and want != prod_assets.get(qid, []):
            q_rows.append({"_id": qid, "assets": _denul(want)})

    # Push a snapshot whenever its assets OR figure_missing flag differ from prod.
    i_rows = [{"_id": iid, "snapshot": _denul(s)}
              for iid, s in local_snaps.items()
              if iid in prod_snap
              and (s.get("assets") or [], bool(s.get("figure_missing"))) != prod_snap[iid]]

    def _push(engine, stmt, rows, label):
        for start in range(0, len(rows), BATCH):
            batch = rows[start:start + BATCH]
            _tx(engine, lambda dc, b=batch: dc.execute(stmt, b))
            print(f"  {label}: {min(start + BATCH, len(rows))}/{len(rows)}", flush=True)

    _push(dst, update(Question).where(Question.id == bindparam("_id"))
          .values(assets=bindparam("assets")), q_rows, "questions.assets")
    _push(dst, update(ExamItem).where(ExamItem.id == bindparam("_id"))
          .values(snapshot=bindparam("snapshot")), i_rows, "exam_items.snapshot")

    print(f"Updated {len(q_rows)} questions.assets, {len(i_rows)} exam_items.snapshot "
          f"(changed vs prod only; no rows deleted).")


if __name__ == "__main__":
    main()
