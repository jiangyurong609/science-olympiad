"""body-free monitoring for metadata-only sources

Revision ID: 0015_metadata_monitoring
Revises: 0014_source_coverage
"""

from alembic import op
import sqlalchemy as sa

from app.core.database import Base
import app.models.entities  # noqa: F401


revision = "0015_metadata_monitoring"
down_revision = "0014_source_coverage"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "source_metadata_checks" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["source_metadata_checks"].create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    if "source_metadata_checks" in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["source_metadata_checks"].drop(bind=bind, checkfirst=True)
