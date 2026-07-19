"""Real 2026 event-catalog fields: category, topic focus, official URL.

Revision ID: 0024_event_catalog_fields
Revises: 0023_exam_response_recovery
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_event_catalog_fields"
down_revision = "0023_exam_response_recovery"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("events")}
    with op.batch_alter_table("events") as batch:
        if "category" not in columns:
            batch.add_column(sa.Column("category", sa.String(120), nullable=False, server_default=""))
        if "topic_focus" not in columns:
            batch.add_column(sa.Column("topic_focus", sa.Text(), nullable=False, server_default=""))
        if "official_url" not in columns:
            batch.add_column(sa.Column("official_url", sa.String(1024), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("events") as batch:
        batch.drop_column("official_url")
        batch.drop_column("topic_focus")
        batch.drop_column("category")
