"""Persist extraction diagnostics for Content Studio review."""
from alembic import op
import sqlalchemy as sa

revision = "0030_extraction_assets"
down_revision = "0029_content_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extraction_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("upload_id", sa.Integer(), sa.ForeignKey("upload_submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("extraction_version", sa.String(length=80), nullable=False, server_default="v1"),
        sa.Column("artifact_key", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="completed"),
        sa.Column("diagnostics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_extraction_assets_upload_id", "extraction_assets", ["upload_id"], unique=True)
    op.create_index("ix_extraction_assets_status", "extraction_assets", ["status"])


def downgrade() -> None:
    op.drop_table("extraction_assets")
