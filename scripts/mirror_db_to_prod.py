"""Mirror the local database into a target (prod) database — REPLACING its contents.

Copies every table's rows from SOURCE_URL into DEST_URL: deletes all destination
rows (child tables first), then inserts the source rows (parent tables first),
then resets Postgres identity sequences. Uses the app's SQLAlchemy metadata so
JSON / boolean / datetime columns convert correctly between SQLite and Postgres.

DESTRUCTIVE on the destination. Requires --yes.

Prereqs: start the Cloud SQL proxy first (scripts/prod_db_proxy.sh).

Usage:
  DEST_URL='postgresql+psycopg2://soplat_app:<PASS>@127.0.0.1:5434/soplat' \
  SOURCE_URL='sqlite:///./science_olympiad.db' \
  python -m scripts.mirror_db_to_prod --yes
"""
from __future__ import annotations

import os
import sys
import time

from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

import app.models.entities  # noqa: F401 — registers every table on the metadata
from app.models.entities import Base, Event

# Account/org structure — never touched by --content-only (references only itself).
PRESERVE_TABLES = {
    "organizations", "users", "teams", "team_memberships",
    "accommodation_profiles", "accommodation_changes", "guardian_consents",
}
# Content — wiped on the destination and reloaded from the source. Their user/org
# FK columns (all nullable) are stripped on load so they don't reference prod users.
CONTENT_TABLES = {
    "events", "concepts", "sources", "source_snapshots", "raw_artifacts",
    "source_metadata_checks", "source_changes", "event_source_maps", "taxa",
    "event_taxon_scopes", "specimen_assets", "scientific_claims", "questions",
    "exams", "exam_items", "lessons", "lesson_versions", "practice_sets",
    "practice_set_versions", "crawl_domain_policies", "discovered_resources",
}
# Everything else (attempts, responses, reviews, notifications, …) is activity that
# FKs content+users; on --content-only it is CLEARED on the destination, not reloaded.


def _strip_user_org(row: dict) -> dict:
    return {k: (None if (k.endswith("_user_id") or k == "organization_id") else v)
            for k, v in row.items()}


def _denul(value):
    """Postgres text/json cannot hold NUL (0x00); SQLite (from PDF extraction) can.
    Strip NUL from every string, recursing into JSON dict/list columns."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _denul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_denul(v) for v in value]
    return value


def _clean_row(row: dict) -> dict:
    return {k: _denul(v) for k, v in row.items()}


def _tx(dst, work, tries: int = 5, delay: float = 2.0):
    """Run `work(connection)` in its own transaction, retrying on a dropped
    connection (the proxy/small instance occasionally aborts mid-load)."""
    for attempt in range(tries):
        try:
            with dst.begin() as dc:
                return work(dc)
        except OperationalError:
            if attempt == tries - 1:
                raise
            time.sleep(delay)


def main() -> None:
    if "--yes" not in sys.argv:
        raise SystemExit("Refusing to run without --yes: this REPLACES the destination database.")
    source_url = os.environ.get("SOURCE_URL", "sqlite:///./science_olympiad.db")
    dest_url = os.environ.get("DEST_URL")
    if not dest_url:
        raise SystemExit("Set DEST_URL to the target (prod) database URL.")

    src = create_engine(source_url)
    dst = create_engine(dest_url, pool_pre_ping=True, pool_recycle=300)
    tables = Base.metadata.sorted_tables  # parents first; reverse for deletes

    # Guard: never wipe a destination using an empty/absent source.
    with src.connect() as sc:
        events = len(sc.execute(select(Event.__table__.c.id)).all())
    if events == 0:
        raise SystemExit(f"Source {source_url} has 0 events — aborting to avoid wiping the destination.")
    print(f"Source has {events} events. Mirroring {len(tables)} tables → {dest_url.split('@')[-1]}")

    with dst.connect() as check:
        check.execute(text("SELECT 1"))

    content_only = "--full" not in sys.argv
    all_names = {t.name for t in tables}
    if content_only:
        clear = all_names - PRESERVE_TABLES - CONTENT_TABLES
        missing = CONTENT_TABLES - all_names
        if missing:
            raise SystemExit(f"Unknown CONTENT_TABLES: {missing}")
        print(f"Mode: CONTENT-ONLY | preserve {len(PRESERVE_TABLES)} account tables, "
              f"replace {len(CONTENT_TABLES)} content tables, clear {len(clear)} activity tables.")
        # tables to delete on dest = content + activity (everything except preserved), child-first
        to_delete = [t for t in reversed(tables) if t.name not in PRESERVE_TABLES]
        to_load = [t for t in tables if t.name in CONTENT_TABLES]
    else:
        print("Mode: FULL MIRROR | replacing ALL tables (incl. users/attempts).")
        to_delete = list(reversed(tables))
        to_load = list(tables)

    copied = 0
    skipped = 0
    with src.connect() as sc:
        # Valid PK sets per content table — used to drop rows whose FKs dangle
        # (SQLite doesn't enforce FKs, so the source can contain orphaned rows).
        valid_ids = {t.name: set(sc.execute(select(t.c.id)).scalars().all())
                     for t in to_load if "id" in t.c}

        # Delete child-first, each in its own transaction (keeps the DB's memory low).
        for table in to_delete:
            _tx(dst, lambda dc, t=table: dc.execute(t.delete()))

        # Load parent-first, committing every batch so no single transaction holds all
        # the large extracted_text at once (a small Cloud SQL instance OOMs otherwise).
        for table in to_load:
            order = list(table.primary_key.columns) or list(table.columns)
            rows = []
            for raw in sc.execute(select(table).order_by(*order)):
                row = _clean_row(dict(raw._mapping))
                if content_only:
                    row = _strip_user_org(row)
                drop = False
                for fk in table.foreign_keys:
                    child_col, parent_tbl = fk.parent.name, fk.column.table.name
                    val, parent_ids = row.get(child_col), valid_ids.get(parent_tbl)
                    if val is None or parent_ids is None or val in parent_ids:
                        continue
                    if fk.parent.nullable:
                        row[child_col] = None
                    else:
                        drop = True
                        break
                if drop:
                    skipped += 1
                else:
                    rows.append(row)
            for start in range(0, len(rows), 15):
                batch = rows[start:start + 15]
                try:
                    _tx(dst, lambda dc, b=batch: dc.execute(insert(table), b))
                    copied += len(batch)
                except IntegrityError:  # fall back to row-by-row, skipping the bad ones
                    for one in batch:
                        try:
                            _tx(dst, lambda dc, o=one: dc.execute(insert(table), [o]))
                            copied += 1
                        except IntegrityError:
                            skipped += 1
            print(f"  load {table.name:28} {len(rows)}", flush=True)
    print(f"Copied {copied} rows ({skipped} orphaned/skipped).")

    if dest_url.startswith("postgresql"):
        with dst.begin() as dc:
            for table in to_load:
                if "id" in table.c:
                    dc.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table.name}), 1), true)"
                    ))
        print("Reset identity sequences.")
    print("Mirror complete.")


if __name__ == "__main__":
    main()
