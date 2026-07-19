"""versioned human review workflow for generated questions

Revision ID: 0016_question_editorial
Revises: 0015_metadata_monitoring
"""
from alembic import op
import sqlalchemy as sa
from app.core.database import Base
import app.models.entities  # noqa: F401

revision = "0016_question_editorial"
down_revision = "0015_metadata_monitoring"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("questions")}
    if "similarity_report" not in columns:
        op.add_column("questions", sa.Column("similarity_report", sa.JSON(), nullable=True))
    if "question_reviews" not in set(inspector.get_table_names()):
        Base.metadata.tables["question_reviews"].create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    if "question_reviews" in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["question_reviews"].drop(bind=bind, checkfirst=True)
    if "similarity_report" in {c["name"] for c in sa.inspect(bind).get_columns("questions")}:
        op.drop_column("questions", "similarity_report")
