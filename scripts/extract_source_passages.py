"""Create complete, locator-bearing passages from retained source snapshots."""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

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
            if args.apply:
                # Commit per snapshot, and retry once on a dropped connection. Held to a
                # single commit at the end, one TLS drop on the Cloud SQL proxy threw away
                # every passage extracted in the run — Botany lost 102 sources' worth and the
                # build stopped with 86 passages and no lessons. A snapshot's passages are a
                # complete unit of work; there is no reason to risk the rest of the run on it.
                try:
                    ensure_source_passages(db, snapshot, commit=True)
                except OperationalError:
                    db.rollback()
                    print(f"   connection dropped on snapshot {snapshot.id} — retrying once",
                          flush=True)
                    try:
                        ensure_source_passages(db, snapshot, commit=True)
                    except OperationalError:
                        db.rollback()
                        report["failed_snapshots"] = report.get("failed_snapshots", [])
                        report["failed_snapshots"].append(snapshot.id)
                        continue
            report["passages"] += len(payloads)
            report["snapshots_extracted"] += 1
        if not args.apply:
            db.rollback()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
