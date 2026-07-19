"""Add image/diagram assets to questions for visual identification events.

Revision ID: 0025_question_assets
Revises: 0024_event_catalog_fields
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_question_assets"
down_revision = "0024_event_catalog_fields"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("questions")}
    if "assets" not in columns:
        with op.batch_alter_table("questions") as batch:
            batch.add_column(sa.Column("assets", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    with op.batch_alter_table("questions") as batch:
        batch.drop_column("assets")
