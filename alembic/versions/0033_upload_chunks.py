"""Add durable resumable upload chunks."""
from alembic import op
import sqlalchemy as sa

revision = "0033_upload_chunks"
down_revision = "0032_background_job_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "upload_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("upload_id", sa.Integer(), sa.ForeignKey("upload_submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("artifact_key", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("upload_id", "chunk_index", name="uq_upload_chunk_index"),
    )
    op.create_index("ix_upload_chunks_upload_id", "upload_chunks", ["upload_id"])


def downgrade() -> None:
    op.drop_index("ix_upload_chunks_upload_id", table_name="upload_chunks")
    op.drop_table("upload_chunks")
