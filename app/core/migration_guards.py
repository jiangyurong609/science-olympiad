"""Helpers for migrations that must tolerate the 0001 `create_all` baseline.

Migration 0001 calls `Base.metadata.create_all()`, so a brand-new database is born with
every table in *today's* models — including tables that later migrations also create. Those
later `create_table` calls then fail with "table already exists" on a fresh install, while
working fine on long-lived databases that predate them.

These helpers let a migration express "ensure this exists" instead of "create this", so the
same chain runs on both a fresh database and a deployed one.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import inspect


def has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def create_table_if_absent(name: str, *columns, **kwargs) -> bool:
    """Create the table unless the 0001 baseline already made it. Returns True if created."""
    if has_table(name):
        return False
    op.create_table(name, *columns, **kwargs)
    return True


def create_index_if_absent(index_name: str, table_name: str, columns: list[str], **kwargs) -> bool:
    if not has_table(table_name):
        return False
    existing = {ix["name"] for ix in inspect(op.get_bind()).get_indexes(table_name)}
    if index_name in existing:
        return False
    op.create_index(index_name, table_name, columns, **kwargs)
    return True


def drop_table_if_present(name: str) -> bool:
    if not has_table(name):
        return False
    op.drop_table(name)
    return True


def has_column(table: str, column: str) -> bool:
    if not has_table(table):
        return False
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def add_column_if_absent(table: str, column, **kwargs) -> bool:
    """Add the column unless the 0001 baseline already produced it."""
    if has_column(table, column.name):
        return False
    op.add_column(table, column, **kwargs)
    return True


def drop_column_if_present(table: str, column: str, **kwargs) -> bool:
    if not has_column(table, column):
        return False
    op.drop_column(table, column, **kwargs)
    return True
