"""versioned psychometric calibration evidence

Revision ID: 0019_question_calibration
Revises: 0018_exam_release_classes
"""
from alembic import op
import sqlalchemy as sa
from app.core.database import Base
import app.models.entities  # noqa: F401

revision = "0019_question_calibration"
down_revision = "0018_exam_release_classes"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "question_calibrations" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["question_calibrations"].create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    if "question_calibrations" in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["question_calibrations"].drop(bind=bind, checkfirst=True)
