"""durable in-app notifications and external delivery outbox

Revision ID: 0021_notifications_outbox
Revises: 0020_content_challenges
"""
from alembic import op
import sqlalchemy as sa
from app.core.database import Base
import app.models.entities  # noqa: F401

revision = "0021_notifications_outbox"
down_revision = "0020_content_challenges"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("user_notifications", "notification_outbox"):
        if name not in tables:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("notification_outbox", "user_notifications"):
        if name in tables:
            Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
