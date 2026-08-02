"""Pin the lesson version a disposition was granted for.

`Lesson.disposition` recorded *that* an exposure decision was made, never *what* it was made
about. Eight pilot lessons kept their `unreviewed_practice` grandfather through a split that
cut them to "Part 1 of N" and introduced model-written blocks, so students were served
rewritten content under an exemption granted for the original.

Existing rows are backfilled to their current version: those decisions were made about the
content as it stands at migration time, and assuming otherwise would withdraw legitimately
grandfathered content from students without anyone deciding to.
"""
from alembic import op
import sqlalchemy as sa

from app.core.migration_guards import add_column_if_absent

revision = "0040_lesson_disposition_version"
down_revision = "0039_lesson_disposition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_absent("lessons", sa.Column("disposition_version", sa.Integer(), nullable=True))
    op.execute("UPDATE lessons SET disposition_version = current_version "
               "WHERE disposition_version IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("lessons") as batch:
        batch.drop_column("disposition_version")
