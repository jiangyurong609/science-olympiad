"""Create complete, locator-bearing passages from retained source snapshots."""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import SourcePassage, SourceSnapshot
from app.services.source_passages import ensure_source_passages, extract_passage_payloads


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--snapshot-id", type=int)
    args = parser.parse_args()
    with SessionLocal() as db:
        query = select(SourceSnapshot).order_by(SourceSnapshot.id)
        if args.snapshot_id:
            query = query.where(SourceSnapshot.id == args.snapshot_id)
        snapshots = db.scalars(query).all()
        report = {
            "mode": "apply" if args.apply else "dry_run",
            "snapshots": len(snapshots),
            "snapshots_with_text": 0,
            "snapshots_already_extracted": 0,
            "snapshots_extracted": 0,
            "passages": 0,
            "unusable_snapshots": [],
        }
        for snapshot in snapshots:
            if not (snapshot.extracted_text or "").strip():
                report["unusable_snapshots"].append(snapshot.id)
                continue
            report["snapshots_with_text"] += 1
            existing = db.scalar(select(SourcePassage.id).where(
                SourcePassage.source_snapshot_id == snapshot.id
            ))
            if existing:
                report["snapshots_already_extracted"] += 1
                continue
            payloads = extract_passage_payloads(snapshot)
            if not payloads:
                report["unusable_snapshots"].append(snapshot.id)
                continue
            report["passages"] += len(payloads)
            report["snapshots_extracted"] += 1
            if args.apply:
                ensure_source_passages(db, snapshot, commit=False)
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
