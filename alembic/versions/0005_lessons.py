"""versioned lessons and student progress

Revision ID: 0005_lessons
Revises: 0004_firebase_identity
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_lessons"
down_revision = "0004_firebase_identity"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "lessons" not in existing:
        op.create_table(
            "lessons",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("concept_id", sa.Integer(), sa.ForeignKey("concepts.id"), nullable=True),
            sa.Column("slug", sa.String(length=140), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("current_version", sa.Integer(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("estimated_minutes", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("event_id", "slug", name="uq_lesson_event_slug"),
        )
        op.create_index("ix_lessons_event_id", "lessons", ["event_id"])
        op.create_index("ix_lessons_concept_id", "lessons", ["concept_id"])
        op.create_index("ix_lessons_status", "lessons", ["status"])
    if "lesson_versions" not in existing:
        op.create_table(
            "lesson_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column("claim_ids", sa.JSON(), nullable=False),
            sa.Column("citations", sa.JSON(), nullable=False),
            sa.Column("review_status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("lesson_id", "version", name="uq_lesson_version"),
        )
        op.create_index("ix_lesson_versions_lesson_id", "lesson_versions", ["lesson_id"])
    if "lesson_progress" not in existing:
        op.create_table(
            "lesson_progress",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lesson_version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("current_block", sa.Integer(), nullable=False),
            sa.Column("completed_block_ids", sa.JSON(), nullable=False),
            sa.Column("checkpoint_results", sa.JSON(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("user_id", "lesson_id", name="uq_lesson_progress_user"),
        )
        op.create_index("ix_lesson_progress_user_id", "lesson_progress", ["user_id"])
        op.create_index("ix_lesson_progress_lesson_id", "lesson_progress", ["lesson_id"])
        op.create_index("ix_lesson_progress_status", "lesson_progress", ["status"])


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("lesson_progress", "lesson_versions", "lessons"):
        if table in existing:
            op.drop_table(table)
