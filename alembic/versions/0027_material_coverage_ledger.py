"""Add course material coverage and explicit content-gap ledger.

Revision ID: 0027_material_coverage_ledger
Revises: 0026_course_learning_graph
"""
from alembic import op
import sqlalchemy as sa


revision = "0027_material_coverage_ledger"
down_revision = "0026_course_learning_graph"
branch_labels = None
depends_on = None


def upgrade():
    expected_tables = {"course_source_coverage", "content_gaps"}
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    already_created = expected_tables & existing_tables
    if already_created:
        if already_created != expected_tables:
            missing = ", ".join(sorted(expected_tables - already_created))
            raise RuntimeError(f"Partial material coverage schema; missing: {missing}")
        claim_columns = {column["name"] for column in inspector.get_columns("scientific_claims")}
        missing_columns = {"source_passage_id", "skill_id"} - claim_columns
        if missing_columns:
            raise RuntimeError(
                "Partial material coverage claim schema; missing: "
                + ", ".join(sorted(missing_columns))
            )
        return

    op.create_table(
        "course_source_coverage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_snapshot_id", sa.Integer(), sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("sheet_row", sa.String(64), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("authority_tier", sa.Integer(), nullable=True),
        sa.Column("instructional_role", sa.String(64), nullable=False),
        sa.Column("extraction_status", sa.String(32), nullable=False),
        sa.Column("rights_status", sa.String(32), nullable=False),
        sa.Column("passage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claim_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mapped_unit_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("mapped_skill_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("lesson_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("practice_set_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("question_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("review_status", sa.String(32), nullable=False, server_default="unreviewed"),
        sa.Column("student_destination", sa.String(1024), nullable=False, server_default=""),
        sa.Column("decision_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("withdrawal_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("course_id", "source_id", name="uq_course_source_coverage"),
    )
    for name, columns in (
        ("ix_course_source_coverage_course_id", ["course_id"]),
        ("ix_course_source_coverage_source_id", ["source_id"]),
        ("ix_course_source_coverage_source_snapshot_id", ["source_snapshot_id"]),
        ("ix_course_source_coverage_instructional_role", ["instructional_role"]),
        ("ix_course_source_coverage_extraction_status", ["extraction_status"]),
        ("ix_course_source_coverage_rights_status", ["rights_status"]),
        ("ix_course_source_coverage_review_status", ["review_status"]),
    ):
        op.create_index(name, "course_source_coverage", columns)

    op.create_table(
        "content_gaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("course_units.id", ondelete="CASCADE"), nullable=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gap_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("owner", sa.String(160), nullable=False, server_default="content operations"),
        sa.Column("resolution_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("skill_id", "gap_type", name="uq_skill_content_gap"),
    )
    for name, columns in (
        ("ix_content_gaps_course_id", ["course_id"]),
        ("ix_content_gaps_unit_id", ["unit_id"]),
        ("ix_content_gaps_skill_id", ["skill_id"]),
        ("ix_content_gaps_gap_type", ["gap_type"]),
        ("ix_content_gaps_status", ["status"]),
    ):
        op.create_index(name, "content_gaps", columns)

    with op.batch_alter_table("scientific_claims") as batch:
        batch.add_column(sa.Column("source_passage_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("skill_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_scientific_claims_source_passage",
            "source_passages", ["source_passage_id"], ["id"], ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_scientific_claims_skill",
            "skills", ["skill_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index(
            "ix_scientific_claims_source_passage_id", ["source_passage_id"]
        )
        batch.create_index("ix_scientific_claims_skill_id", ["skill_id"])


def downgrade():
    with op.batch_alter_table("scientific_claims") as batch:
        batch.drop_index("ix_scientific_claims_skill_id")
        batch.drop_index("ix_scientific_claims_source_passage_id")
        batch.drop_column("skill_id")
        batch.drop_column("source_passage_id")
    op.drop_table("content_gaps")
    op.drop_table("course_source_coverage")
