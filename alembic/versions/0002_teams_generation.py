"""teams and generation runs

Revision ID: 0002_teams_generation
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_teams_generation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "teams" not in existing:
        op.create_table(
            "teams",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=180), nullable=False),
            sa.Column("division", sa.String(length=8), nullable=False),
            sa.Column("season", sa.Integer(), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("organization_id", "name", name="uq_team_org_name"),
        )
        op.create_index("ix_teams_organization_id", "teams", ["organization_id"])
        op.create_index("ix_teams_created_by_user_id", "teams", ["created_by_user_id"])
    if "team_memberships" not in existing:
        op.create_table(
            "team_memberships",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("membership_role", sa.String(length=32), nullable=False),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("team_id", "user_id", name="uq_team_membership"),
        )
        op.create_index("ix_team_memberships_team_id", "team_memberships", ["team_id"])
        op.create_index("ix_team_memberships_user_id", "team_memberships", ["user_id"])
    if "generation_runs" not in existing:
        op.create_table(
            "generation_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=True),
            sa.Column("concept_id", sa.Integer(), sa.ForeignKey("concepts.id"), nullable=True),
            sa.Column("provider", sa.String(length=100), nullable=False),
            sa.Column("model", sa.String(length=160), nullable=False),
            sa.Column("prompt_version", sa.String(length=80), nullable=False),
            sa.Column("request_json", sa.JSON(), nullable=False),
            sa.Column("result_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_generation_runs_actor_user_id", "generation_runs", ["actor_user_id"])
        op.create_index("ix_generation_runs_event_id", "generation_runs", ["event_id"])
        op.create_index("ix_generation_runs_concept_id", "generation_runs", ["concept_id"])


def downgrade():
    op.drop_table("generation_runs")
    op.drop_table("team_memberships")
    op.drop_table("teams")
