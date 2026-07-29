"""Add structured student feedback for preview content."""
from alembic import op
import sqlalchemy as sa

revision = "0028_student_content_feedback"
down_revision = "0027_material_coverage_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "student_content_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="general"),
        sa.Column("feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("user_id", "event_id", "course_id", "entity_type", "entity_id", "created_at"):
        op.create_index(f"ix_student_content_feedback_{column}", "student_content_feedback", [column])


def downgrade() -> None:
    op.drop_table("student_content_feedback")
