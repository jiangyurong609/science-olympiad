"""event source universe and season status

Revision ID: 0014_source_coverage
Revises: 0013_accommodations
"""

from alembic import op
import sqlalchemy as sa

from app.core.database import Base
import app.models.entities  # noqa: F401


revision = "0014_source_coverage"
down_revision = "0013_accommodations"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("events")}
    if "season_status" not in columns:
        with op.batch_alter_table("events") as batch_op:
            batch_op.add_column(sa.Column("season_status", sa.String(length=32), nullable=False, server_default="current"))
            batch_op.create_index("ix_events_season_status", ["season_status"])
    if "event_source_maps" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["event_source_maps"].create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    if "event_source_maps" in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["event_source_maps"].drop(bind=bind, checkfirst=True)
    columns = {column["name"] for column in sa.inspect(bind).get_columns("events")}
    if "season_status" in columns:
        with op.batch_alter_table("events") as batch_op:
            batch_op.drop_index("ix_events_season_status")
            batch_op.drop_column("season_status")
