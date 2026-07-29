"""Add explicit parent/student relationship approvals."""
from alembic import op
import sqlalchemy as sa

revision = "0034_parent_student_links"
down_revision = "0033_upload_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parent_student_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parent_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("consent_scope", sa.String(length=80), nullable=False, server_default="materials_intake"),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("parent_user_id", "student_user_id", name="uq_parent_student_link"),
    )
    op.create_index("ix_parent_student_links_parent_user_id", "parent_student_links", ["parent_user_id"])
    op.create_index("ix_parent_student_links_student_user_id", "parent_student_links", ["student_user_id"])
    op.create_index("ix_parent_student_links_status", "parent_student_links", ["status"])


def downgrade() -> None:
    op.drop_index("ix_parent_student_links_status", table_name="parent_student_links")
    op.drop_index("ix_parent_student_links_student_user_id", table_name="parent_student_links")
    op.drop_index("ix_parent_student_links_parent_user_id", table_name="parent_student_links")
    op.drop_table("parent_student_links")
