"""audited timed accommodations and immutable session snapshots

Revision ID: 0013_accommodations
Revises: 0012_taxonomy_assets
"""

from alembic import op
import sqlalchemy as sa

from app.core.database import Base
import app.models.entities  # noqa: F401


revision = "0013_accommodations"
down_revision = "0012_taxonomy_assets"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for name in ("accommodation_profiles", "accommodation_changes"):
        if name not in existing:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)
    practice_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("practice_sessions")
    }
    with op.batch_alter_table("practice_sessions") as batch_op:
        if "time_multiplier" not in practice_columns:
            batch_op.add_column(sa.Column("time_multiplier", sa.Float(), nullable=False, server_default="1.0"))
        if "base_seconds_per_item" not in practice_columns:
            batch_op.add_column(sa.Column("base_seconds_per_item", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE practice_sessions SET base_seconds_per_item = seconds_per_item "
        "WHERE mode = 'station' AND base_seconds_per_item IS NULL"
    )
    attempt_columns = {column["name"] for column in sa.inspect(bind).get_columns("attempts")}
    if "time_multiplier" not in attempt_columns:
        with op.batch_alter_table("attempts") as batch_op:
            batch_op.add_column(sa.Column("time_multiplier", sa.Float(), nullable=False, server_default="1.0"))


def downgrade():
    bind = op.get_bind()
    attempt_columns = {column["name"] for column in sa.inspect(bind).get_columns("attempts")}
    if "time_multiplier" in attempt_columns:
        with op.batch_alter_table("attempts") as batch_op:
            batch_op.drop_column("time_multiplier")
    practice_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("practice_sessions")
    }
    with op.batch_alter_table("practice_sessions") as batch_op:
        if "base_seconds_per_item" in practice_columns:
            batch_op.drop_column("base_seconds_per_item")
        if "time_multiplier" in practice_columns:
            batch_op.drop_column("time_multiplier")
    existing = set(sa.inspect(bind).get_table_names())
    for name in ("accommodation_changes", "accommodation_profiles"):
        if name in existing:
            Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
