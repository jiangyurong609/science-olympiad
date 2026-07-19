"""background jobs and assignments

Revision ID: 0003_jobs_assignments
Revises: 0002_teams_generation
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_jobs_assignments"
down_revision = "0002_teams_generation"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "background_jobs" not in existing:
        op.create_table(
            "background_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_type", sa.String(length=80), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_background_jobs_job_type", "background_jobs", ["job_type"])
        op.create_index("ix_background_jobs_status", "background_jobs", ["status"])
        op.create_index("ix_background_jobs_scheduled_at", "background_jobs", ["scheduled_at"])
    if "assignments" not in existing:
        op.create_table(
            "assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
            sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("instructions", sa.Text(), nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_assignments_organization_id", "assignments", ["organization_id"])
        op.create_index("ix_assignments_team_id", "assignments", ["team_id"])
        op.create_index("ix_assignments_exam_id", "assignments", ["exam_id"])
        op.create_index("ix_assignments_due_at", "assignments", ["due_at"])


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "assignments" in existing:
        op.drop_table("assignments")
    if "background_jobs" in existing:
        op.drop_table("background_jobs")
