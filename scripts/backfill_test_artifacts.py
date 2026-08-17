"""Give the local-imported past tests back the bytes they were extracted from.

`import_past_test` recovers figures through `_retained_bytes`, which looks for a RawArtifact on
the source's snapshot. Tests ingested from the local corpus kept only their extracted text — no
artifact — so figure recovery could never run for any of them, and every image-dependent
question was dropped. The PDFs are still on disk, so this uploads each one and records the
artifact the importer already knows how to find.

This is the durable fix, not a one-off: once the artifact exists, the ordinary import path
recovers figures for that source with no special casing, exactly as it does for a PDF an admin
uploads through Add Materials.

Usage: --plan, or --apply [--match <substring>]
"""
import argparse
import hashlib
import os

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import RawArtifact, Source, SourceSnapshot
from app.services import media_storage

from pathlib import Path


def _safe_db_label() -> str:
    """Never print the connection string: it carries the production password."""
    from urllib.parse import urlparse
    parsed = urlparse(os.environ.get("DATABASE_URL", ""))
    return f"{parsed.hostname or '?'}:{parsed.port or '?'}/{(parsed.path or '').lstrip('/')}"


ROOT = Path("docs/science_olympiad_tests/_extracted")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--match", default="")
    args = parser.parse_args()
    db = SessionLocal()
    print(f"database: {_safe_db_label()}")
    print(f"storage:  {os.environ.get('ARTIFACT_STORE_BACKEND','local')} "
          f"{os.environ.get('ARTIFACT_STORE_BUCKET','')}\n")

    sources = db.scalars(select(Source).where(Source.url.like("local://%"))).all()
    if args.match:
        sources = [s for s in sources if args.match.lower() in (s.url or "").lower()]

    done = missing = already = failed = 0
    for source in sources:
        rel = (source.url or "").replace("local://", "")
        path = ROOT / rel
        snapshot = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_id == source.id
        ).order_by(SourceSnapshot.created_at.desc(), SourceSnapshot.id.desc()))
        if not snapshot:
            missing += 1
            continue
        if db.scalar(select(RawArtifact).where(RawArtifact.snapshot_id == snapshot.id)):
            already += 1
            continue
        if not path.exists():
            missing += 1
            print(f"   missing on disk: {rel[:70]}")
            continue
        if not args.apply:
            done += 1
            continue
        data = path.read_bytes()
        key = f"sources/{source.id}/snapshot-{snapshot.id}/{path.name}"
        try:
            stored = media_storage.upload_media(key, data, "application/pdf")
        except Exception as exc:
            failed += 1
            print(f"   upload failed for {rel[:60]}: {type(exc).__name__}")
            continue
        db.add(RawArtifact(
            snapshot_id=snapshot.id, storage_key=getattr(stored, "key", key),
            content_hash=hashlib.sha256(data).hexdigest(), byte_count=len(data),
            detected_media_type="application/pdf", scan_status="local_corpus"))
        db.commit()
        done += 1

    verb = "would backfill" if not args.apply else "backfilled"
    print(f"{verb}: {done} · already had bytes: {already} · not on disk: {missing} · failed: {failed}")


if __name__ == "__main__":
    main()
