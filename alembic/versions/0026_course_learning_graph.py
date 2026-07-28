"""Add versioned course, unit, skill, passage, and release graph.

Revision ID: 0026_course_learning_graph
Revises: 0025_question_assets
"""
from alembic import op
import sqlalchemy as sa


revision = "0026_course_learning_graph"
down_revision = "0025_question_assets"
branch_labels = None
depends_on = None


def upgrade():
    # The original 0001 migration calls Base.metadata.create_all(), so a brand
    # new database created from today's model metadata already contains every
    # table below. Existing deployed databases do not. Treat the fully-created
    # state as equivalent, but reject a partial state instead of silently
    # stamping an incomplete schema.
    expected_tables = {
        "courses", "course_versions", "course_units", "skills", "lesson_skills",
        "source_passages", "assessment_blueprints", "content_releases",
        "review_decisions", "content_migration_maps",
    }
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    already_created = expected_tables & existing_tables
    if already_created:
        if already_created != expected_tables:
            missing = ", ".join(sorted(expected_tables - already_created))
            raise RuntimeError(f"Partial course learning graph schema; missing: {missing}")
        return

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(140), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_course_event"),
        sa.UniqueConstraint("slug", name="uq_courses_slug"),
    )
    op.create_index("ix_courses_event_id", "courses", ["event_id"])
    op.create_index("ix_courses_slug", "courses", ["slug"])
    op.create_index("ix_courses_status", "courses", ["status"])

    op.create_table(
        "course_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("objectives", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("release_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("review_status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("course_id", "version", name="uq_course_version"),
    )
    op.create_index("ix_course_versions_course_id", "course_versions", ["course_id"])
    op.create_index("ix_course_versions_review_status", "course_versions", ["review_status"])

    op.create_table(
        "course_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(140), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("objectives", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("prerequisites", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("course_id", "slug", name="uq_course_unit_slug"),
    )
    op.create_index("ix_course_units_course_id", "course_units", ["course_id"])
    op.create_index("ix_course_units_status", "course_units", ["status"])

    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("course_units.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.Integer(), sa.ForeignKey("concepts.id"), nullable=True),
        sa.Column("slug", sa.String(140), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("prerequisites", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("course_id", "slug", name="uq_skill_course_slug"),
    )
    op.create_index("ix_skills_course_id", "skills", ["course_id"])
    op.create_index("ix_skills_unit_id", "skills", ["unit_id"])
    op.create_index("ix_skills_concept_id", "skills", ["concept_id"])
    op.create_index("ix_skills_status", "skills", ["status"])

    op.create_table(
        "lesson_skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("lesson_id", "skill_id", name="uq_lesson_skill"),
    )
    op.create_index("ix_lesson_skills_lesson_id", "lesson_skills", ["lesson_id"])
    op.create_index("ix_lesson_skills_skill_id", "lesson_skills", ["skill_id"])

    op.create_table(
        "source_passages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_snapshot_id", sa.Integer(), sa.ForeignKey("source_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locator", sa.String(255), nullable=False),
        sa.Column("heading", sa.String(500), nullable=False, server_default=""),
        sa.Column("passage_type", sa.String(64), nullable=False, server_default="text"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_snapshot_id", "locator", "content_hash", name="uq_source_passage_locator"),
    )
    op.create_index("ix_source_passages_source_id", "source_passages", ["source_id"])
    op.create_index("ix_source_passages_source_snapshot_id", "source_passages", ["source_snapshot_id"])
    op.create_index("ix_source_passages_passage_type", "source_passages", ["passage_type"])
    op.create_index("ix_source_passages_content_hash", "source_passages", ["content_hash"])

    op.create_table(
        "assessment_blueprints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("course_units.id", ondelete="CASCADE"), nullable=True),
        sa.Column("assessment_type", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("specification", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("course_id", "unit_id", "assessment_type", "version", name="uq_assessment_blueprint_version"),
    )
    op.create_index("ix_assessment_blueprints_course_id", "assessment_blueprints", ["course_id"])
    op.create_index("ix_assessment_blueprints_unit_id", "assessment_blueprints", ["unit_id"])
    op.create_index("ix_assessment_blueprints_assessment_type", "assessment_blueprints", ["assessment_type"])
    op.create_index("ix_assessment_blueprints_status", "assessment_blueprints", ["status"])

    op.create_table(
        "content_releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("manifest", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("release_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("course_id", "version", name="uq_content_release_version"),
    )
    op.create_index("ix_content_releases_course_id", "content_releases", ["course_id"])
    op.create_index("ix_content_releases_status", "content_releases", ["status"])
    op.create_index("ix_content_releases_published_by_user_id", "content_releases", ["published_by_user_id"])

    op.create_table(
        "review_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("checklist", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_review_decisions_entity_type", "review_decisions", ["entity_type"])
    op.create_index("ix_review_decisions_entity_id", "review_decisions", ["entity_id"])
    op.create_index("ix_review_decisions_stage", "review_decisions", ["stage"])
    op.create_index("ix_review_decisions_decision", "review_decisions", ["decision"])
    op.create_index("ix_review_decisions_reviewer_user_id", "review_decisions", ["reviewer_user_id"])

    op.create_table(
        "content_migration_maps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("legacy_type", sa.String(64), nullable=False),
        sa.Column("legacy_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("migration_state", sa.String(64), nullable=False),
        sa.Column("redirect_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column("owner", sa.String(160), nullable=False, server_default="content operations"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legacy_type", "legacy_id", name="uq_content_migration_legacy"),
    )
    op.create_index("ix_content_migration_maps_legacy_type", "content_migration_maps", ["legacy_type"])
    op.create_index("ix_content_migration_maps_legacy_id", "content_migration_maps", ["legacy_id"])
    op.create_index("ix_content_migration_maps_target_id", "content_migration_maps", ["target_id"])
    op.create_index("ix_content_migration_maps_migration_state", "content_migration_maps", ["migration_state"])


def downgrade():
    op.drop_table("content_migration_maps")
    op.drop_table("review_decisions")
    op.drop_table("content_releases")
    op.drop_table("assessment_blueprints")
    op.drop_table("source_passages")
    op.drop_table("lesson_skills")
    op.drop_table("skills")
    op.drop_table("course_units")
    op.drop_table("course_versions")
    op.drop_table("courses")
