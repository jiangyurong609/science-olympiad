"""Add private parent contribution scope."""
from alembic import op
import sqlalchemy as sa

revision = "0031_parent_material_shares"
down_revision = "0030_extraction_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parent_material_shares",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("upload_id", sa.Integer(), sa.ForeignKey("upload_submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("consent_scope", sa.String(length=80), nullable=False, server_default="intake_only"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_parent_material_shares_upload_id", "parent_material_shares", ["upload_id"], unique=True)
    op.create_index("ix_parent_material_shares_parent_user_id", "parent_material_shares", ["parent_user_id"])
    op.create_index("ix_parent_material_shares_student_user_id", "parent_material_shares", ["student_user_id"])
    op.create_index("ix_parent_material_shares_team_id", "parent_material_shares", ["team_id"])


def downgrade() -> None:
    op.drop_table("parent_material_shares")
