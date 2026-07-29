"""Scope parent consent to an explicitly approved team when supplied."""
from alembic import op
import sqlalchemy as sa


revision = "0035_parent_relationship_teams"
down_revision = "0034_parent_student_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("parent_student_links") as batch_op:
        batch_op.add_column(sa.Column("team_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_parent_student_links_team_id_teams",
            "teams",
            ["team_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_parent_student_links_team_id", "parent_student_links", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_parent_student_links_team_id", table_name="parent_student_links")
    with op.batch_alter_table("parent_student_links") as batch_op:
        batch_op.drop_constraint("fk_parent_student_links_team_id_teams", type_="foreignkey")
        batch_op.drop_column("team_id")
