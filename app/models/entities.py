from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, Enum):
    STUDENT = "student"
    COACH = "coach"
    ADMIN = "admin"
    EDITOR = "editor"
    SME = "sme"
    CALIBRATOR = "calibrator"


class RightsStatus(str, Enum):
    LINK_ONLY = "link_only"
    METADATA_ONLY = "metadata_only"
    PUBLIC_DOMAIN = "public_domain"
    APPROVED_WITH_ATTRIBUTION = "approved_with_attribution"
    FACT_GROUNDING_ALLOWED = "fact_grounding_allowed"
    DERIVATIVE_GENERATION_ALLOWED = "derivative_generation_allowed"
    BLOCKED = "blocked"
    QUARANTINED = "quarantined"


class QuestionStatus(str, Enum):
    DRAFT = "draft"
    MACHINE_VALIDATED = "machine_validated"
    EDITOR_REVIEWED = "editor_reviewed"
    SME_APPROVED = "sme_approved"
    CALIBRATED = "calibrated"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


class AttemptStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    SCORED = "scored"
    REMEDIATION_OPEN = "remediation_open"
    REMEDIATION_COMPLETE = "remediation_complete"


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    firebase_uid: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(32), default=Role.STUDENT.value)
    division: Mapped[str | None] = mapped_column(String(8), nullable=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AccommodationProfile(Base):
    __tablename__ = "accommodation_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_accommodation_user"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    time_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    reduced_distraction: Mapped[bool] = mapped_column(Boolean, default=False)
    screen_reader_alternative: Mapped[bool] = mapped_column(Boolean, default=False)
    breaks_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class AccommodationChange(Base):
    __tablename__ = "accommodation_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("accommodation_profiles.id", ondelete="CASCADE"), index=True
    )
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    previous_values: Mapped[dict] = mapped_column(JSON, default=dict)
    new_values: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("slug", "season", name="uq_event_slug_season"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(160))
    division: Mapped[str] = mapped_column(String(8))
    season: Mapped[int] = mapped_column(Integer)
    modality: Mapped[str] = mapped_column(String(64), default="written")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="")
    topic_focus: Mapped[str] = mapped_column(Text, default="")
    official_url: Mapped[str] = mapped_column(String(1024), default="")
    season_status: Mapped[str] = mapped_column(String(32), default="current", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class EventSourceMap(Base):
    __tablename__ = "event_source_maps"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "source_id", "purpose", "source_universe_version",
            name="uq_event_source_universe",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(64), index=True)
    source_tier: Mapped[int] = mapped_column(Integer)
    jurisdiction: Mapped[str] = mapped_column(String(80), default="national")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    required_artifact_types: Mapped[list] = mapped_column(JSON, default=list)
    source_universe_version: Mapped[str] = mapped_column(String(80), index=True)
    freshness_minutes: Mapped[int] = mapped_column(Integer, default=43_200)
    coverage_owner: Mapped[str] = mapped_column(String(160), default="content operations")
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Concept(Base):
    __tablename__ = "concepts"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    prerequisites: Mapped[list] = mapped_column(JSON, default=list)
    event: Mapped[Event] = relationship()


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("event_id", "slug", name="uq_lesson_event_slug"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(140))
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    event: Mapped[Event] = relationship()
    concept: Mapped[Concept | None] = relationship()


class LessonVersion(Base):
    __tablename__ = "lesson_versions"
    __table_args__ = (UniqueConstraint("lesson_id", "version", name="uq_lesson_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[list] = mapped_column(JSON, default=list)
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(32), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class LessonProgress(Base):
    __tablename__ = "lesson_progress"
    __table_args__ = (UniqueConstraint("user_id", "lesson_id", name="uq_lesson_progress_user"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    lesson_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="not_started", index=True)
    current_block: Mapped[int] = mapped_column(Integer, default=0)
    completed_block_ids: Mapped[list] = mapped_column(JSON, default=list)
    checkpoint_results: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PracticeSet(Base):
    __tablename__ = "practice_sets"
    __table_args__ = (UniqueConstraint("event_id", "slug", name="uq_practice_set_event_slug"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(140))
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text, default="")
    practice_type: Mapped[str] = mapped_column(String(64), default="identification")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PracticeSetVersion(Base):
    __tablename__ = "practice_set_versions"
    __table_args__ = (UniqueConstraint("practice_set_id", "version", name="uq_practice_set_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    practice_set_id: Mapped[int] = mapped_column(
        ForeignKey("practice_sets.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    items: Mapped[list] = mapped_column(JSON, default=list)
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(32), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    practice_set_id: Mapped[int] = mapped_column(
        ForeignKey("practice_sets.id", ondelete="CASCADE"), index=True
    )
    practice_set_version: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(32), default="study", index=True)
    time_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    base_seconds_per_item: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seconds_per_item: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    status: Mapped[str] = mapped_column(String(32), default="in_progress", index=True)
    item_order: Mapped[list] = mapped_column(JSON, default=list)
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    publisher: Mapped[str] = mapped_column(String(255), default="")
    rights_status: Mapped[str] = mapped_column(String(64), default=RightsStatus.METADATA_ONLY.value)
    license_name: Mapped[str] = mapped_column(String(160), default="unknown")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_crawl_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_crawl_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    consecutive_crawl_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_crawl_error: Mapped[str] = mapped_column(Text, default="")
    crawl_status: Mapped[str] = mapped_column(String(32), default="never", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    final_url: Mapped[str] = mapped_column(String(2048))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str] = mapped_column(String(160), default="")
    byte_count: Mapped[int] = mapped_column(Integer, default=0)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    previous_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_snapshots.id"), nullable=True
    )
    etag: Mapped[str] = mapped_column(String(500), default="")
    last_modified: Mapped[str] = mapped_column(String(500), default="")
    change_kind: Mapped[str] = mapped_column(String(32), default="initial")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SourceMetadataCheck(Base):
    __tablename__ = "source_metadata_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    final_url: Mapped[str] = mapped_column(String(2048))
    status_code: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(160), default="")
    content_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    etag: Mapped[str] = mapped_column(String(500), default="")
    last_modified: Mapped[str] = mapped_column(String(500), default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)


class Taxon(Base):
    __tablename__ = "taxa"
    __table_args__ = (
        UniqueConstraint(
            "scientific_name", "rank", "taxonomy_authority", "taxonomy_version",
            name="uq_taxon_authority_version",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    scientific_name: Mapped[str] = mapped_column(String(255), index=True)
    common_name: Mapped[str] = mapped_column(String(255), default="")
    rank: Mapped[str] = mapped_column(String(40), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("taxa.id"), nullable=True, index=True)
    accepted_taxon_id: Mapped[int | None] = mapped_column(ForeignKey("taxa.id"), nullable=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    taxonomy_authority: Mapped[str] = mapped_column(String(160))
    taxonomy_version: Mapped[str] = mapped_column(String(80))
    nomenclatural_status: Mapped[str] = mapped_column(String(32), default="accepted", index=True)
    diagnostic_traits: Mapped[list] = mapped_column(JSON, default=list)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EventTaxonScope(Base):
    __tablename__ = "event_taxon_scopes"
    __table_args__ = (
        UniqueConstraint("event_id", "taxon_id", "list_version", name="uq_event_taxon_scope"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    taxon_id: Mapped[int] = mapped_column(ForeignKey("taxa.id"), index=True)
    designation: Mapped[str] = mapped_column(String(32), default="foundational", index=True)
    division: Mapped[str] = mapped_column(String(8))
    season: Mapped[int] = mapped_column(Integer, index=True)
    list_version: Mapped[str] = mapped_column(String(80))
    official_source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SpecimenAsset(Base):
    __tablename__ = "specimen_assets"
    __table_args__ = (
        UniqueConstraint("taxon_id", "source_url", "content_hash", name="uq_specimen_asset_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    taxon_id: Mapped[int] = mapped_column(ForeignKey("taxa.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    source_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("source_snapshots.id"), nullable=True)
    source_url: Mapped[str] = mapped_column(String(2048))
    media_type: Mapped[str] = mapped_column(String(80), default="image")
    rights_status: Mapped[str] = mapped_column(String(64), default=RightsStatus.METADATA_ONLY.value, index=True)
    license_name: Mapped[str] = mapped_column(String(160), default="unknown")
    attribution: Mapped[str] = mapped_column(Text, default="")
    alt_text: Mapped[str] = mapped_column(String(1000), default="")
    long_description: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64))
    review_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    taxon_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class RawArtifact(Base):
    __tablename__ = "raw_artifacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="CASCADE"), unique=True, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    byte_count: Mapped[int] = mapped_column(Integer)
    detected_media_type: Mapped[str] = mapped_column(String(160), default="")
    scan_status: Mapped[str] = mapped_column(String(32), default="basic_pass")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SourceChange(Base):
    __tablename__ = "source_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    previous_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_snapshots.id"), nullable=True
    )
    current_snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"))
    change_kind: Mapped[str] = mapped_column(String(32), index=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    impact: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class CrawlDomainPolicy(Base):
    __tablename__ = "crawl_domain_policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(253), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_tier: Mapped[int] = mapped_column(Integer, default=3)
    default_rights_status: Mapped[str] = mapped_column(
        String(64), default=RightsStatus.METADATA_ONLY.value
    )
    max_urls: Mapped[int] = mapped_column(Integer, default=10_000)
    crawl_delay_seconds: Mapped[float] = mapped_column(Float, default=2.0)
    recrawl_minutes: Mapped[int] = mapped_column(Integer, default=43_200)
    allow_paths: Mapped[list] = mapped_column(JSON, default=list)
    deny_paths: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class DiscoveredResource(Base):
    __tablename__ = "discovered_resources"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_url: Mapped[str] = mapped_column(String(2048))
    canonical_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    discovered_url: Mapped[str] = mapped_column(String(2048))
    domain: Mapped[str] = mapped_column(String(253), index=True)
    referrer_url: Mapped[str] = mapped_column(String(2048), default="")
    discovery_method: Mapped[str] = mapped_column(String(64), index=True)
    source_tier: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="discovered", index=True)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    event_candidates: Mapped[list] = mapped_column(JSON, default=list)
    discovery_count: Mapped[int] = mapped_column(Integer, default=1)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    first_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class GuardianConsent(Base):
    __tablename__ = "guardian_consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    guardian_email: Mapped[str] = mapped_column(String(320), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    consent_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ScientificClaim(Base):
    __tablename__ = "scientific_claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    source_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True, index=True)
    claim_text: Mapped[str] = mapped_column(Text)
    evidence_excerpt: Mapped[str] = mapped_column(Text, default="")
    locator: Mapped[str] = mapped_column(String(255), default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default=QuestionStatus.DRAFT.value)
    question_type: Mapped[str] = mapped_column(String(32), default="single_choice")
    stem: Mapped[str] = mapped_column(Text)
    choices: Mapped[list] = mapped_column(JSON, default=list)
    assets: Mapped[list] = mapped_column(JSON, default=list)
    answer_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    difficulty: Mapped[float] = mapped_column(Float, default=0.5)
    cognitive_level: Mapped[str] = mapped_column(String(32), default="application")
    estimated_seconds: Mapped[int] = mapped_column(Integer, default=90)
    validation_report: Mapped[dict] = mapped_column(JSON, default=dict)
    similarity_report: Mapped[dict] = mapped_column(JSON, default=dict)
    generation_provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    event: Mapped[Event] = relationship()
    concept: Mapped[Concept | None] = relationship()


class QuestionReview(Base):
    """Append-only, version-specific human review evidence."""
    __tablename__ = "question_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    question_version: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    reviewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    checklist: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class QuestionCalibration(Base):
    """Immutable pilot statistics and an independent release decision."""
    __tablename__ = "question_calibrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    question_version: Mapped[int] = mapped_column(Integer)
    sample_size: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    deterministic_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    reviewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Exam(Base):
    __tablename__ = "exams"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=50)
    question_ids: Mapped[list] = mapped_column(JSON, default=list)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    release_class: Mapped[str] = mapped_column(String(40), default="reviewed_practice", index=True)
    coverage_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    published_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blueprint: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    event: Mapped[Event] = relationship()


class ExamItem(Base):
    __tablename__ = "exam_items"
    __table_args__ = (UniqueConstraint("exam_id", "position", name="uq_exam_item_position"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    question_version: Mapped[int] = mapped_column(Integer, default=1)
    position: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=AttemptStatus.IN_PROGRESS.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0)
    active_client_session_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    client_lease_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exam: Mapped[Exam] = relationship()


class Response(Base):
    __tablename__ = "responses"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_response_attempt_question"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    answer: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0)
    sequence_number: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    points_awarded: Mapped[float | None] = mapped_column(Float, nullable=True)
    diagnostic: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class ResponseRevision(Base):
    __tablename__ = "response_revisions"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", "sequence_number", name="uq_response_revision_sequence"),
        UniqueConstraint("idempotency_key", name="uq_response_revision_idempotency"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("responses.id", ondelete="CASCADE"), index=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    previous_revision_id: Mapped[int | None] = mapped_column(ForeignKey("response_revisions.id"), nullable=True)
    answer: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0)
    sequence_number: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(80), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    client_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)


class AttemptSubmission(Base):
    __tablename__ = "attempt_submissions"
    __table_args__ = (UniqueConstraint("attempt_id", name="uq_attempt_submission"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    submission_kind: Mapped[str] = mapped_column(String(32))
    response_manifest: Mapped[list] = mapped_column(JSON, default=list)
    manifest_hash: Mapped[str] = mapped_column(String(64), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ContentChallenge(Base):
    __tablename__ = "content_challenges"
    __table_args__ = (
        UniqueConstraint("user_id", "attempt_id", "question_id", name="uq_challenge_user_attempt_question"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    question_version: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(40), index=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="submitted", index=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    triaged_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution: Mapped[dict] = mapped_column(JSON, default=dict)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContentChallengeEvent(Base):
    __tablename__ = "content_challenge_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("content_challenges.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ScoreCorrection(Base):
    __tablename__ = "score_corrections"
    __table_args__ = (UniqueConstraint("challenge_id", "attempt_id", name="uq_correction_challenge_attempt"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("content_challenges.id"), index=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), index=True)
    response_id: Mapped[int | None] = mapped_column(ForeignKey("responses.id"), nullable=True)
    old_score: Mapped[float] = mapped_column(Float)
    old_max_score: Mapped[float] = mapped_column(Float)
    new_score: Mapped[float] = mapped_column(Float)
    new_max_score: Mapped[float] = mapped_column(Float)
    old_response_state: Mapped[dict] = mapped_column(JSON, default=dict)
    new_response_state: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class UserNotification(Base):
    __tablename__ = "user_notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notification_type: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    action_url: Mapped[str] = mapped_column(String(500), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (UniqueConstraint("notification_id", "channel", name="uq_notification_channel"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("user_notifications.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="email")
    recipient: Mapped[str] = mapped_column(String(320))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TutorSession(Base):
    __tablename__ = "tutor_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    context_type: Mapped[str] = mapped_column(String(24), index=True)
    context_id: Mapped[int] = mapped_column(Integer, index=True)
    context_version: Mapped[int] = mapped_column(Integer)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    grounding_claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class TutorMessage(Base):
    __tablename__ = "tutor_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("tutor_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    provider: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)


class RemediationCase(Base):
    __tablename__ = "remediation_cases"
    __table_args__ = (
        UniqueConstraint("user_id", "source_type", "source_ref", name="uq_remediation_source"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempts.id"), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"), nullable=True, index=True)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="exam", index=True)
    source_ref: Mapped[str] = mapped_column(String(160), default="")
    error_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="open")
    diagnosis: Mapped[dict] = mapped_column(JSON, default=dict)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    student_reflection: Mapped[str] = mapped_column(Text, default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TransferAttempt(Base):
    __tablename__ = "transfer_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    remediation_case_id: Mapped[int] = mapped_column(ForeignKey("remediation_cases.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    answer: Mapped[dict] = mapped_column(JSON, default=dict)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    diagnostic: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MasteryState(Base):
    __tablename__ = "mastery_states"
    __table_args__ = (UniqueConstraint("user_id", "concept_id", name="uq_mastery_user_concept"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    mastery_probability: Mapped[float] = mapped_column(Float, default=0.25)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    misconception_risk: Mapped[float] = mapped_column(Float, default=0.5)
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_team_org_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    division: Mapped[str] = mapped_column(String(8))
    season: Mapped[int] = mapped_column(Integer)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TeamMembership(Base):
    __tablename__ = "team_memberships"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_membership"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    membership_role: Mapped[str] = mapped_column(String(32), default="student")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class GenerationRun(Base):
    __tablename__ = "generation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), nullable=True, index=True)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(100), default="deterministic")
    model: Mapped[str] = mapped_column(String(160), default="")
    prompt_version: Mapped[str] = mapped_column(String(80), default="v1")
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    instructions: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    exam: Mapped[Exam] = relationship()
