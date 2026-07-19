"""raw artifacts, snapshot lineage, and source change impact

Revision ID: 0007_source_change_pipeline
Revises: 0006_discovery_frontier
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_source_change_pipeline"
down_revision = "0006_discovery_frontier"
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("source_snapshots")
    }
    with op.batch_alter_table("source_snapshots") as batch_op:
        if "previous_snapshot_id" not in columns:
            batch_op.add_column(sa.Column("previous_snapshot_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_source_snapshot_previous",
                "source_snapshots",
                ["previous_snapshot_id"],
                ["id"],
            )
        if "etag" not in columns:
            batch_op.add_column(sa.Column("etag", sa.String(length=500), nullable=False, server_default=""))
        if "last_modified" not in columns:
            batch_op.add_column(sa.Column("last_modified", sa.String(length=500), nullable=False, server_default=""))
        if "change_kind" not in columns:
            batch_op.add_column(sa.Column("change_kind", sa.String(length=32), nullable=False, server_default="initial"))
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "raw_artifacts" not in existing:
        op.create_table(
            "raw_artifacts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("source_snapshots.id", ondelete="CASCADE"), nullable=False),
            sa.Column("storage_key", sa.String(length=500), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("byte_count", sa.Integer(), nullable=False),
            sa.Column("detected_media_type", sa.String(length=160), nullable=False),
            sa.Column("scan_status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_raw_artifacts_snapshot_id", "raw_artifacts", ["snapshot_id"], unique=True)
        op.create_index("ix_raw_artifacts_content_hash", "raw_artifacts", ["content_hash"])
    if "source_changes" not in existing:
        op.create_table(
            "source_changes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("previous_snapshot_id", sa.Integer(), sa.ForeignKey("source_snapshots.id"), nullable=True),
            sa.Column("current_snapshot_id", sa.Integer(), sa.ForeignKey("source_snapshots.id"), nullable=False),
            sa.Column("change_kind", sa.String(length=32), nullable=False),
            sa.Column("review_status", sa.String(length=32), nullable=False),
            sa.Column("summary", sa.JSON(), nullable=False),
            sa.Column("impact", sa.JSON(), nullable=False),
            sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_source_changes_source_id", "source_changes", ["source_id"])
        op.create_index("ix_source_changes_change_kind", "source_changes", ["change_kind"])
        op.create_index("ix_source_changes_review_status", "source_changes", ["review_status"])


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("source_changes", "raw_artifacts"):
        if table in existing:
            op.drop_table(table)
    with op.batch_alter_table("source_snapshots") as batch_op:
        batch_op.drop_column("change_kind")
        batch_op.drop_column("last_modified")
        batch_op.drop_column("etag")
        batch_op.drop_constraint("fk_source_snapshot_previous", type_="foreignkey")
        batch_op.drop_column("previous_snapshot_id")
