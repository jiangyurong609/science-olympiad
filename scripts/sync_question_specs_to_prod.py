"""Sync question `answer_spec` (distractor misconception mappings) to prod, and
backfill the same into existing exam-item snapshots so remediation is specific
everywhere — new mock exams AND already-assembled past-test exams.

UPDATE-only, matched by id (questions) and by question_id / stem+correct_index
(snapshots). No deletes.

Prereqs: start the Cloud SQL proxy (scripts/prod_db_proxy.sh).

Usage:
  DEST_URL='postgresql+psycopg2://...@127.0.0.1:5434/soplat' \
  python -m scripts.sync_question_specs_to_prod --yes
"""
from __future__ import annotations

import os
import sys
import time

from sqlalchemy import bindparam, create_engine, select, text, update
from sqlalchemy.exc import OperationalError

import app.models.entities  # noqa: F401
from app.models.entities import ExamItem, Question

BATCH = 40


def _tx(engine, work, tries=5, delay=2.0):
    for attempt in range(tries):
        try:
            with engine.begin() as dc:
                return work(dc)
        except OperationalError:
            if attempt == tries - 1:
                raise
            time.sleep(delay)


def _push(engine, stmt, rows, label):
    for start in range(0, len(rows), BATCH):
        batch = rows[start:start + BATCH]
        _tx(engine, lambda dc, b=batch: dc.execute(stmt, b))
        print(f"  {label}: {min(start + BATCH, len(rows))}/{len(rows)}", flush=True)


def main() -> None:
    if "--yes" not in sys.argv:
        raise SystemExit("Refusing to run without --yes.")
    dest_url = os.environ.get("DEST_URL")
    if not dest_url:
        raise SystemExit("Set DEST_URL.")
    src = create_engine(os.environ.get("SOURCE_URL", "sqlite:///./science_olympiad.db"))
    dst = create_engine(dest_url, pool_pre_ping=True, pool_recycle=300)

    # Local questions that now carry a distractor mapping, plus stems for
    # matching frozen past-test snapshots that have no question_id.
    with src.connect() as sc:
        mapped, by_key = {}, {}
        for qid, stem, spec in sc.execute(select(Question.id, Question.stem, Question.answer_spec)):
            if (spec or {}).get("distractor_error_types"):
                mapped[qid] = spec
                by_key[(stem, (spec or {}).get("correct_index"))] = spec
        local_snaps = [(iid, snap) for iid, snap in sc.execute(select(ExamItem.id, ExamItem.snapshot)) if snap]

    # 1) Push question answer_spec by id.
    with dst.connect() as dc:
        prod_specs = {qid: (spec or {}) for qid, spec in dc.execute(select(Question.id, Question.answer_spec))}
    q_rows = [{"_id": qid, "answer_spec": spec} for qid, spec in mapped.items()
              if prod_specs.get(qid, {}).get("distractor_error_types") != spec.get("distractor_error_types")]
    _push(dst, update(Question).where(Question.id == bindparam("_id"))
          .values(answer_spec=bindparam("answer_spec")), q_rows, "questions.answer_spec")

    # 2) Backfill exam-item snapshots. Match by question_id when present, else by
    #    (stem, correct_index) so frozen past-test items get the mapping too.
    by_id = mapped
    i_rows = []
    for iid, snap in local_snaps:
        if snap.get("question_type") != "single_choice" or (snap.get("answer_spec") or {}).get("distractor_error_types"):
            continue
        spec = by_id.get(snap.get("question_id")) or by_key.get((snap.get("stem"), (snap.get("answer_spec") or {}).get("correct_index")))
        if not spec:
            continue
        new_snap = dict(snap)
        new_spec = dict(new_snap.get("answer_spec") or {})
        new_spec["distractor_error_types"] = spec["distractor_error_types"]
        new_spec["misconception_by_choice"] = spec.get("misconception_by_choice", {})
        new_snap["answer_spec"] = new_spec
        i_rows.append({"_id": iid, "snapshot": new_snap})
    _push(dst, update(ExamItem).where(ExamItem.id == bindparam("_id"))
          .values(snapshot=bindparam("snapshot")), i_rows, "exam_items.snapshot")

    print(f"Synced {len(q_rows)} question specs, backfilled {len(i_rows)} snapshots.")


if __name__ == "__main__":
    main()
