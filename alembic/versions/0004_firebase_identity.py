"""firebase identity mapping

Revision ID: 0004_firebase_identity
Revises: 0003_jobs_assignments
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_firebase_identity"
down_revision = "0003_jobs_assignments"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "firebase_uid" not in columns:
        op.add_column("users", sa.Column("firebase_uid", sa.String(length=128), nullable=True))
        op.create_index("ix_users_firebase_uid", "users", ["firebase_uid"], unique=True)
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("password_hash", existing_type=sa.String(length=255), nullable=True)


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("password_hash", existing_type=sa.String(length=255), nullable=False)
    if "firebase_uid" in columns:
        op.drop_index("ix_users_firebase_uid", table_name="users")
        op.drop_column("users", "firebase_uid")
