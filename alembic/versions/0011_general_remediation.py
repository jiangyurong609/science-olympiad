"""generalize remediation origins for lessons and practice

Revision ID: 0011_general_remediation
Revises: 0010_station_practice
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_general_remediation"
down_revision = "0010_station_practice"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("remediation_cases")}
    indexes = {index["name"] for index in inspector.get_indexes("remediation_cases")}
    with op.batch_alter_table("remediation_cases") as batch_op:
        if "source_type" not in columns:
            batch_op.add_column(sa.Column("source_type", sa.String(length=32), nullable=False, server_default="exam"))
        if "source_ref" not in columns:
            batch_op.add_column(sa.Column("source_ref", sa.String(length=160), nullable=False, server_default=""))
        if "ix_remediation_cases_source_type" not in indexes:
            batch_op.create_index("ix_remediation_cases_source_type", ["source_type"])
    # SQLite rebuilds a table for nullable foreign-key changes. Separate stages
    # avoid Alembic's circular column-order dependency during a clean install.
    if not columns["attempt_id"]["nullable"]:
        with op.batch_alter_table("remediation_cases") as batch_op:
            batch_op.alter_column("attempt_id", existing_type=sa.Integer(), nullable=True)
    if not columns["question_id"]["nullable"]:
        with op.batch_alter_table("remediation_cases") as batch_op:
            batch_op.alter_column("question_id", existing_type=sa.Integer(), nullable=True)
    op.execute(
        "UPDATE remediation_cases SET source_ref = "
        "'exam:' || CAST(attempt_id AS TEXT) || ':' || CAST(question_id AS TEXT) "
        "WHERE source_ref = ''"
    )
    unique_names = {
        constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("remediation_cases")
    }
    if "uq_remediation_source" not in unique_names:
        with op.batch_alter_table("remediation_cases") as batch_op:
            batch_op.create_unique_constraint(
                "uq_remediation_source", ["user_id", "source_type", "source_ref"]
            )


def downgrade():
    with op.batch_alter_table("remediation_cases") as batch_op:
        batch_op.drop_constraint("uq_remediation_source", type_="unique")
        batch_op.drop_index("ix_remediation_cases_source_type")
        batch_op.drop_column("source_ref")
        batch_op.drop_column("source_type")
    with op.batch_alter_table("remediation_cases") as batch_op:
        batch_op.alter_column("question_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("remediation_cases") as batch_op:
        batch_op.alter_column("attempt_id", existing_type=sa.Integer(), nullable=False)
