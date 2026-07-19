"""crawler discovery frontier and domain policies

Revision ID: 0006_discovery_frontier
Revises: 0005_lessons
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_discovery_frontier"
down_revision = "0005_lessons"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "crawl_domain_policies" not in existing:
        op.create_table(
            "crawl_domain_policies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("domain", sa.String(length=253), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("source_tier", sa.Integer(), nullable=False),
            sa.Column("default_rights_status", sa.String(length=64), nullable=False),
            sa.Column("max_urls", sa.Integer(), nullable=False),
            sa.Column("crawl_delay_seconds", sa.Float(), nullable=False),
            sa.Column("allow_paths", sa.JSON(), nullable=False),
            sa.Column("deny_paths", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_crawl_domain_policies_domain", "crawl_domain_policies", ["domain"], unique=True)
        op.create_index("ix_crawl_domain_policies_enabled", "crawl_domain_policies", ["enabled"])
    if "discovered_resources" not in existing:
        op.create_table(
            "discovered_resources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("canonical_url", sa.String(length=2048), nullable=False),
            sa.Column("canonical_hash", sa.String(length=64), nullable=False),
            sa.Column("discovered_url", sa.String(length=2048), nullable=False),
            sa.Column("domain", sa.String(length=253), nullable=False),
            sa.Column("referrer_url", sa.String(length=2048), nullable=False),
            sa.Column("discovery_method", sa.String(length=64), nullable=False),
            sa.Column("source_tier", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("relevance_score", sa.Float(), nullable=False),
            sa.Column("event_candidates", sa.JSON(), nullable=False),
            sa.Column("discovery_count", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=False),
            sa.Column("first_discovered_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_discovered_resources_canonical_hash", "discovered_resources", ["canonical_hash"], unique=True)
        op.create_index("ix_discovered_resources_domain", "discovered_resources", ["domain"])
        op.create_index("ix_discovered_resources_discovery_method", "discovered_resources", ["discovery_method"])
        op.create_index("ix_discovered_resources_source_tier", "discovered_resources", ["source_tier"])
        op.create_index("ix_discovered_resources_status", "discovered_resources", ["status"])


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("discovered_resources", "crawl_domain_policies"):
        if table in existing:
            op.drop_table(table)
