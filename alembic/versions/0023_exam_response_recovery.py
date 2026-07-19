"""immutable response revisions and submission manifests

Revision ID: 0023_exam_response_recovery
Revises: 0022_grounded_tutor
"""
from alembic import op
import sqlalchemy as sa
from app.core.database import Base
import app.models.entities  # noqa: F401

revision = "0023_exam_response_recovery"
down_revision = "0022_grounded_tutor"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("response_revisions", "attempt_submissions"):
        if name not in tables:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)
    columns = {column["name"] for column in sa.inspect(bind).get_columns("attempts")}
    with op.batch_alter_table("attempts") as batch:
        if "active_client_session_id" not in columns:
            batch.add_column(sa.Column("active_client_session_id", sa.String(80), nullable=True))
        if "client_lease_at" not in columns:
            batch.add_column(sa.Column("client_lease_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("attempt_submissions", "response_revisions"):
        if name in tables:
            Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
    columns = {column["name"] for column in sa.inspect(bind).get_columns("attempts")}
    with op.batch_alter_table("attempts") as batch:
        if "client_lease_at" in columns:
            batch.drop_column("client_lease_at")
        if "active_client_session_id" in columns:
            batch.drop_column("active_client_session_id")
