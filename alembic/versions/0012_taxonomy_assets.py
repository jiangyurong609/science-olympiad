"""versioned taxonomy and rights-aware specimen assets

Revision ID: 0012_taxonomy_assets
Revises: 0011_general_remediation
"""

from alembic import op
import sqlalchemy as sa

from app.core.database import Base
import app.models.entities  # noqa: F401


revision = "0012_taxonomy_assets"
down_revision = "0011_general_remediation"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name in ("taxa", "event_taxon_scopes", "specimen_assets"):
        if name not in existing:
            Base.metadata.tables[name].create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name in ("specimen_assets", "event_taxon_scopes", "taxa"):
        if name in existing:
            Base.metadata.tables[name].drop(bind=op.get_bind(), checkfirst=True)
