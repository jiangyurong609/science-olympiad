"""Phase V: video storyboards and renders

Revision ID: 0036_video_storyboards
Revises: 0035_parent_relationship_teams
"""
from alembic import op
import sqlalchemy as sa

revision = "0036_video_storyboards"
down_revision = "0035_parent_relationship_teams"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_storyboards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("lesson_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("scenes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft", index=True),
        sa.Column("review_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("lesson_id", "version", name="uq_video_storyboard_version"),
    )
    op.create_table(
        "video_renders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("storyboard_id", sa.Integer(), sa.ForeignKey("video_storyboards.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued", index=True),
        sa.Column("spec_hash", sa.String(length=64), nullable=False, server_default="", index=True),
        sa.Column("duration_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("audio_keys", sa.JSON(), nullable=False),
        sa.Column("slide_keys", sa.JSON(), nullable=False),
        sa.Column("video_key", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("worker_job_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("qa_status", sa.String(length=32), nullable=False, server_default="pending", index=True),
        sa.Column("qa_notes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("video_renders")
    op.drop_table("video_storyboards")
