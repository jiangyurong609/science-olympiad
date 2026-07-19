"""persistent grounded learning tutor sessions

Revision ID: 0022_grounded_tutor
Revises: 0021_notifications_outbox
"""
from alembic import op
import sqlalchemy as sa
from app.core.database import Base
import app.models.entities  # noqa: F401

revision = "0022_grounded_tutor"
down_revision = "0021_notifications_outbox"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("tutor_sessions", "tutor_messages"):
        if name not in tables:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("tutor_messages", "tutor_sessions"):
        if name in tables:
            Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
