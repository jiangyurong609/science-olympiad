"""Phase 0: explicit student-exposure disposition on exams

Revision ID: 0038_exam_disposition
Revises: 0037_video_render_chapters
"""
from alembic import op
import sqlalchemy as sa

from app.core.migration_guards import add_column_if_absent, drop_column_if_present

revision = "0038_exam_disposition"
down_revision = "0037_video_render_chapters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_absent(
        "exams",
        sa.Column("disposition", sa.String(length=32), nullable=False,
                  server_default="pending_disposition"),
    )


def downgrade() -> None:
    drop_column_if_present("exams", "disposition")
