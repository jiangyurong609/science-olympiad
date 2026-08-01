"""Phase 0: explicit student-exposure disposition on lessons

Revision ID: 0039_lesson_disposition
Revises: 0038_exam_disposition
"""
from alembic import op
import sqlalchemy as sa

from app.core.migration_guards import add_column_if_absent, drop_column_if_present

revision = "0039_lesson_disposition"
down_revision = "0038_exam_disposition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_absent(
        "lessons",
        sa.Column("disposition", sa.String(length=32), nullable=False,
                  server_default="pending_disposition"),
    )
    # Grandfather existing published lessons explicitly rather than by season, so review
    # evidence is consulted for everything created from now on.
    op.execute(
        "UPDATE lessons SET disposition = 'unreviewed_practice' "
        "WHERE status = 'published' AND disposition = 'pending_disposition'"
    )


def downgrade() -> None:
    drop_column_if_present("lessons", "disposition")
