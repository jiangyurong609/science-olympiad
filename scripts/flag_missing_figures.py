"""Flag exam-item snapshots that depend on a figure we don't have.

Past-test import was text-only, so ~224 questions reference "the diagram/figure
shown" with no image. This marks each affected ExamItem snapshot
`figure_missing: True` so the scorer excludes it (not counted for/against the
student) and the exam runner can show a "figure unavailable" notice instead of
silently presenting an unanswerable question.

Usage: python -m scripts.flag_missing_figures [--dry-run]
"""
from __future__ import annotations

import sys

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.entities import ExamItem
from app.services.scoring import is_figure_missing


def main() -> None:
    dry = "--dry-run" in sys.argv
    changed = 0
    with SessionLocal() as db:
        for item in db.scalars(select(ExamItem)):
            snap = item.snapshot or {}
            missing = is_figure_missing(snap.get("stem", ""), snap.get("assets"))
            if bool(snap.get("figure_missing")) == bool(missing):
                continue
            changed += 1
            if not dry:
                snap["figure_missing"] = bool(missing)
                item.snapshot = snap
                flag_modified(item, "snapshot")
        if not dry:
            db.commit()
    print(f"{'DRY-RUN: would flag' if dry else 'Flagged'} {changed} exam-item snapshots "
          f"(figure_missing set/cleared).")


if __name__ == "__main__":
    main()
