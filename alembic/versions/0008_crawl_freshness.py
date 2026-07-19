"""crawl freshness scheduling and health state

Revision ID: 0008_crawl_freshness
Revises: 0007_source_change_pipeline
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_crawl_freshness"
down_revision = "0007_source_change_pipeline"
branch_labels = None
depends_on = None


def upgrade():
    source_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("sources")
    }
    with op.batch_alter_table("sources") as batch_op:
        if "last_successful_crawl_at" not in source_columns:
            batch_op.add_column(sa.Column("last_successful_crawl_at", sa.DateTime(timezone=True), nullable=True))
        if "next_crawl_at" not in source_columns:
            batch_op.add_column(sa.Column("next_crawl_at", sa.DateTime(timezone=True), nullable=True))
            batch_op.create_index("ix_sources_next_crawl_at", ["next_crawl_at"])
        if "consecutive_crawl_failures" not in source_columns:
            batch_op.add_column(sa.Column("consecutive_crawl_failures", sa.Integer(), nullable=False, server_default="0"))
        if "last_crawl_error" not in source_columns:
            batch_op.add_column(sa.Column("last_crawl_error", sa.Text(), nullable=False, server_default=""))
        if "crawl_status" not in source_columns:
            batch_op.add_column(sa.Column("crawl_status", sa.String(length=32), nullable=False, server_default="never"))
            batch_op.create_index("ix_sources_crawl_status", ["crawl_status"])
    policy_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("crawl_domain_policies")
    }
    if "recrawl_minutes" not in policy_columns:
        op.add_column(
            "crawl_domain_policies",
            sa.Column("recrawl_minutes", sa.Integer(), nullable=False, server_default="43200"),
        )


def downgrade():
    op.drop_column("crawl_domain_policies", "recrawl_minutes")
    with op.batch_alter_table("sources") as batch_op:
        batch_op.drop_index("ix_sources_crawl_status")
        batch_op.drop_column("crawl_status")
        batch_op.drop_column("last_crawl_error")
        batch_op.drop_column("consecutive_crawl_failures")
        batch_op.drop_index("ix_sources_next_crawl_at")
        batch_op.drop_column("next_crawl_at")
        batch_op.drop_column("last_successful_crawl_at")
