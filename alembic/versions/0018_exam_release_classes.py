"""explicit exam release classes and publication evidence

Revision ID: 0018_exam_release_classes
Revises: 0017_claim_snapshot_provenance
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_exam_release_classes"
down_revision = "0017_claim_snapshot_provenance"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("exams")}
    with op.batch_alter_table("exams") as batch:
        if "release_class" not in columns:
            batch.add_column(sa.Column("release_class", sa.String(40), nullable=False, server_default="reviewed_practice"))
            batch.create_index("ix_exams_release_class", ["release_class"])
        if "coverage_snapshot" not in columns:
            batch.add_column(sa.Column("coverage_snapshot", sa.JSON(), nullable=True))
        if "published_by_user_id" not in columns:
            batch.add_column(sa.Column("published_by_user_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_exam_publisher", "users", ["published_by_user_id"], ["id"])
        if "published_at" not in columns:
            batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text(
        "UPDATE exams SET release_class = 'foundational_practice' "
        "WHERE event_id IN (SELECT id FROM events WHERE season_status <> 'current')"
    ))
    op.execute(sa.text(
        # `WHERE published` is truthy on both SQLite (0/1 integer) and
        # PostgreSQL (boolean); `published = 1` fails on PostgreSQL.
        "UPDATE exams SET published_at = created_at WHERE published AND published_at IS NULL"
    ))


def downgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("exams")}
    with op.batch_alter_table("exams") as batch:
        if "published_at" in columns:
            batch.drop_column("published_at")
        if "published_by_user_id" in columns:
            batch.drop_constraint("fk_exam_publisher", type_="foreignkey")
            batch.drop_column("published_by_user_id")
        if "coverage_snapshot" in columns:
            batch.drop_column("coverage_snapshot")
        if "release_class" in columns:
            batch.drop_index("ix_exams_release_class")
            batch.drop_column("release_class")
