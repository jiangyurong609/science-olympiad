"""student content challenges and audited score corrections

Revision ID: 0020_content_challenges
Revises: 0019_question_calibration
"""
from alembic import op
import sqlalchemy as sa
from app.core.database import Base
import app.models.entities  # noqa: F401

revision = "0020_content_challenges"
down_revision = "0019_question_calibration"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("content_challenges", "content_challenge_events", "score_corrections"):
        if name not in tables:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("score_corrections", "content_challenge_events", "content_challenges"):
        if name in tables:
            Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
