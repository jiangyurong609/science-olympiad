"""server-authoritative station practice timing

Revision ID: 0010_station_practice
Revises: 0009_practice_labs
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_station_practice"
down_revision = "0009_practice_labs"
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("practice_sessions")
    }
    with op.batch_alter_table("practice_sessions") as batch_op:
        if "mode" not in columns:
            batch_op.add_column(sa.Column("mode", sa.String(length=32), nullable=False, server_default="study"))
            batch_op.create_index("ix_practice_sessions_mode", ["mode"])
        if "seconds_per_item" not in columns:
            batch_op.add_column(sa.Column("seconds_per_item", sa.Integer(), nullable=True))
        if "item_started_at" not in columns:
            batch_op.add_column(sa.Column("item_started_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE practice_sessions SET item_started_at = started_at WHERE item_started_at IS NULL")
    with op.batch_alter_table("practice_sessions") as batch_op:
        batch_op.alter_column("item_started_at", existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade():
    with op.batch_alter_table("practice_sessions") as batch_op:
        batch_op.drop_column("item_started_at")
        batch_op.drop_column("seconds_per_item")
        batch_op.drop_index("ix_practice_sessions_mode")
        batch_op.drop_column("mode")
