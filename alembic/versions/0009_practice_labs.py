"""versioned practice labs and resumable sessions

Revision ID: 0009_practice_labs
Revises: 0008_crawl_freshness
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_practice_labs"
down_revision = "0008_crawl_freshness"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "practice_sets" not in existing:
        op.create_table(
            "practice_sets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("concept_id", sa.Integer(), sa.ForeignKey("concepts.id"), nullable=True),
            sa.Column("slug", sa.String(length=140), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("practice_type", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("current_version", sa.Integer(), nullable=False),
            sa.Column("estimated_minutes", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("event_id", "slug", name="uq_practice_set_event_slug"),
        )
        op.create_index("ix_practice_sets_event_id", "practice_sets", ["event_id"])
        op.create_index("ix_practice_sets_concept_id", "practice_sets", ["concept_id"])
        op.create_index("ix_practice_sets_status", "practice_sets", ["status"])
    if "practice_set_versions" not in existing:
        op.create_table(
            "practice_set_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("practice_set_id", sa.Integer(), sa.ForeignKey("practice_sets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("items", sa.JSON(), nullable=False),
            sa.Column("claim_ids", sa.JSON(), nullable=False),
            sa.Column("citations", sa.JSON(), nullable=False),
            sa.Column("review_status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("practice_set_id", "version", name="uq_practice_set_version"),
        )
        op.create_index("ix_practice_set_versions_practice_set_id", "practice_set_versions", ["practice_set_id"])
    if "practice_sessions" not in existing:
        op.create_table(
            "practice_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("practice_set_id", sa.Integer(), sa.ForeignKey("practice_sets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("practice_set_version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("item_order", sa.JSON(), nullable=False),
            sa.Column("current_index", sa.Integer(), nullable=False),
            sa.Column("results", sa.JSON(), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_practice_sessions_user_id", "practice_sessions", ["user_id"])
        op.create_index("ix_practice_sessions_practice_set_id", "practice_sessions", ["practice_set_id"])
        op.create_index("ix_practice_sessions_status", "practice_sessions", ["status"])


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("practice_sessions", "practice_set_versions", "practice_sets"):
        if table in existing:
            op.drop_table(table)
