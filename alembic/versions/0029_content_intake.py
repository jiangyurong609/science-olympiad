"""Add auditable upload intake and ingestion runs."""
from alembic import op
import sqlalchemy as sa

revision = "0029_content_intake"
down_revision = "0028_student_content_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "upload_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uploader_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("declared_media_type", sa.String(length=160), nullable=False, server_default="application/octet-stream"),
        sa.Column("artifact_key", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rights_attestation", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="received"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("uploader_user_id", "event_id", "sha256", "status"):
        op.create_index(f"ix_upload_submissions_{column}", "upload_submissions", [column])
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("upload_id", sa.Integer(), sa.ForeignKey("upload_submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False, server_default="received"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("worker_version", sa.String(length=80), nullable=False, server_default="v1"),
        sa.Column("diagnostics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("upload_id", "stage", "status", "source_id"):
        op.create_index(f"ix_ingestion_runs_{column}", "ingestion_runs", [column])


def downgrade() -> None:
    op.drop_table("ingestion_runs")
    op.drop_table("upload_submissions")
