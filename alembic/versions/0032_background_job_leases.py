"""Add lease and heartbeat fields for recoverable ingestion workers."""
from alembic import op
import sqlalchemy as sa

revision = "0032_background_job_leases"
down_revision = "0031_parent_material_shares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("background_jobs", sa.Column("lease_token", sa.String(length=80), nullable=True))
    op.add_column("background_jobs", sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("background_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_background_jobs_lease_token", "background_jobs", ["lease_token"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_lease_token", table_name="background_jobs")
    op.drop_column("background_jobs", "heartbeat_at")
    op.drop_column("background_jobs", "leased_at")
    op.drop_column("background_jobs", "lease_token")
