"""Phase V: per-chapter video renders

Revision ID: 0037_video_render_chapters
Revises: 0036_video_storyboards
"""
from alembic import op
import sqlalchemy as sa

from app.core.migration_guards import add_column_if_absent, drop_column_if_present

revision = "0037_video_render_chapters"
down_revision = "0036_video_storyboards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_absent(
        "video_renders",
        sa.Column("chapter", sa.String(length=120), nullable=False, server_default=""),
    )


def downgrade() -> None:
    drop_column_if_present("video_renders", "chapter")
