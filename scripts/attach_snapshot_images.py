"""Attach specimen images to exam-item SNAPSHOTS by stem-matching.

Past-test / mock exams store self-contained ExamItem snapshots (question_id is
None), so updating question.assets never reaches them. This applies the same
precise "specimen <Letter>, <name>," label matcher used by
attach_specimen_images.py, but directly to each snapshot's stem, using the
owning exam's event to choose the media library.

Usage:
  python -m scripts.attach_snapshot_images            # all media-covered exams
  python -m scripts.attach_snapshot_images --dry-run
"""
from __future__ import annotations

import json
import sys

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.entities import Event, Exam, ExamItem
from app.services.scoring import specimen_definitions
from scripts.attach_specimen_images import (
    MANIFEST, _build_matchers, _match_asset, _media_key,
)


def main() -> None:
    dry = "--dry-run" in sys.argv
    manifest = json.load(open(MANIFEST))
    matchers = _build_matchers(manifest)
    changed = attached = cleared = 0
    with SessionLocal() as db:
        exams = db.scalars(select(Exam)).all()
        for exam in exams:
            event = db.get(Event, exam.event_id)
            entries = matchers.get(_media_key(event.slug)) if event else None
            if not entries:
                continue
            for item in db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id)):
                snap = item.snapshot or {}
                stem = snap.get("stem") or ""
                assets: dict[str, dict] = {}
                for letter, name in specimen_definitions(stem).items():
                    asset = _match_asset(name, entries)
                    if asset and asset["url"] not in assets:
                        assets[asset["url"]] = {**asset, "alt": f"Specimen {letter}: {asset['alt']}"}
                new = list(assets.values())[:4]
                if (snap.get("assets") or []) != new:
                    changed += 1
                    attached += 1 if new else 0
                    cleared += 0 if new else 1
                    if not dry:
                        snap["assets"] = new
                        item.snapshot = snap
                        flag_modified(item, "snapshot")
        if not dry:
            db.commit()
    print(f"{'DRY-RUN: would change' if dry else 'Changed'} {changed} snapshots "
          f"({attached} given an image, {cleared} cleared).")


if __name__ == "__main__":
    main()
