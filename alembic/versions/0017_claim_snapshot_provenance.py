"""bind scientific claims to immutable source snapshots

Revision ID: 0017_claim_snapshot_provenance
Revises: 0016_question_editorial
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_claim_snapshot_provenance"
down_revision = "0016_question_editorial"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("scientific_claims")}
    if "source_snapshot_id" not in columns:
        with op.batch_alter_table("scientific_claims") as batch:
            batch.add_column(sa.Column("source_snapshot_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_scientific_claim_snapshot", "source_snapshots", ["source_snapshot_id"], ["id"], ondelete="RESTRICT"
            )
            batch.create_index("ix_scientific_claims_source_snapshot_id", ["source_snapshot_id"])


def downgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("scientific_claims")}
    if "source_snapshot_id" in columns:
        with op.batch_alter_table("scientific_claims") as batch:
            batch.drop_index("ix_scientific_claims_source_snapshot_id")
            batch.drop_constraint("fk_scientific_claim_snapshot", type_="foreignkey")
            batch.drop_column("source_snapshot_id")
