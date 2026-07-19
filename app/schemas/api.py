from datetime import datetime, timezone
from typing import Annotated, Any
from pydantic import BaseModel, EmailStr, Field, StringConstraints, model_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    division: str | None = None
    age_years: int | None = Field(default=None, ge=5, le=100)
    guardian_email: EmailStr | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class FirebaseBootstrapRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    division: str = Field(pattern="^(B|C)$")
    age_years: int | None = Field(default=None, ge=5, le=100)
    guardian_email: EmailStr | None = None


class SourceCreate(BaseModel):
    url: str
    title: str | None = None
    publisher: str = ""
    rights_status: str = "metadata_only"
    license_name: str = "unknown"


class QuestionGenerateRequest(BaseModel):
    event_id: int
    concept_id: int | None = None
    count: int = Field(default=3, ge=1, le=20)
    difficulty: float = Field(default=0.5, ge=0.0, le=1.0)
    cognitive_level: str = "application"
    question_type: str = "single_choice"


class ExamCreateRequest(BaseModel):
    event_id: int
    title: str
    duration_minutes: int = Field(default=50, ge=1, le=240)
    question_count: int = Field(default=10, ge=1, le=100)
    published: bool = True
    release_class: str = Field(default="reviewed_practice", pattern="^(reviewed_practice|competition_ready)$")


class MockExamRequest(BaseModel):
    event_id: int
    size: int = Field(default=20, ge=1, le=100)
    feedback_mode: str = Field(default="after_submit", pattern="^(after_submit|per_question)$")
    shuffle_choices: bool = True
    use_blueprint: bool = True
    title: str | None = Field(default=None, max_length=255)


class QuestionReviewRequest(BaseModel):
    stage: str = Field(pattern="^(editor|sme)$")
    decision: str = Field(pattern="^(approved|rewrite_required|rejected)$")
    checklist: dict[str, bool] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=4000)


class QuestionCalibrationRequest(BaseModel):
    decision: str = Field(pattern="^(accepted|rejected)$")
    notes: str = Field(min_length=10, max_length=4000)


class ContentChallengeCreateRequest(BaseModel):
    question_id: int
    category: str = Field(pattern="^(wrong_key|ambiguity|factual_error|broken_asset|accessibility|other)$")
    description: str = Field(min_length=20, max_length=4000)


class ContentChallengeTriageRequest(BaseModel):
    severity: str = Field(pattern="^(low|medium|high|critical)$")
    notes: str = Field(min_length=10, max_length=4000)


class ContentChallengeResolveRequest(BaseModel):
    decision: str = Field(pattern="^(upheld|not_upheld)$")
    correction_type: str = Field(pattern="^(exclude_item|correct_key|no_score_change)$")
    corrected_answer_spec: dict[str, Any] | None = None
    public_note: str = Field(min_length=20, max_length=4000)
    internal_note: str = Field(min_length=10, max_length=4000)

    @model_validator(mode="after")
    def valid_resolution(self):
        if self.decision == "not_upheld" and self.correction_type != "no_score_change":
            raise ValueError("A challenge that is not upheld cannot change scores")
        if self.correction_type == "correct_key" and not self.corrected_answer_spec:
            raise ValueError("corrected_answer_spec is required for a key correction")
        return self


class TutorSessionCreateRequest(BaseModel):
    context_type: str = Field(pattern="^(lesson|remediation)$")
    context_id: int
    mode: str = Field(default="socratic_hint", pattern="^(explain|socratic_hint|diagnose_error|quiz_me)$")


class TutorMessageRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)


class AccommodationUpdateRequest(BaseModel):
    time_multiplier: float = Field(default=1.0, ge=1.0, le=3.0)
    active: bool = True
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    reason: str = Field(min_length=10, max_length=500)

    @model_validator(mode="after")
    def valid_effective_window(self):
        if self.effective_from and self.effective_until:
            start = self.effective_from
            end = self.effective_until
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if end <= start:
                raise ValueError("effective_until must be after effective_from")
        return self


class ResponseSaveRequest(BaseModel):
    question_id: int
    answer: dict[str, Any]
    confidence: int | None = Field(default=None, ge=1, le=5)
    time_spent_seconds: int = Field(default=0, ge=0, le=86_400)
    sequence_number: int = Field(default=1, ge=1, le=1_000_000)
    idempotency_key: str = Field(min_length=8, max_length=80)
    client_metadata: dict[str, Any] = Field(default_factory=dict)


class ReflectionRequest(BaseModel):
    reflection: str = Field(min_length=10, max_length=2000)


class ClaimCreateRequest(BaseModel):
    source_id: int
    source_snapshot_id: int
    concept_id: int | None = None
    claim_text: str = Field(min_length=12, max_length=4000)
    evidence_excerpt: str = Field(default="", max_length=4000)
    locator: str = Field(default="", max_length=255)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class TransferAnswerRequest(BaseModel):
    answer: dict[str, Any]


class GuardianRegistrationRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    division: str | None = None
    age_years: int | None = Field(default=None, ge=5, le=100)
    guardian_email: EmailStr | None = None


class GuardianConsentRequest(BaseModel):
    token: str = Field(min_length=24, max_length=200)

class ClaimExtractionRequest(BaseModel):
    concept_id: int | None = None
    limit: int = Field(default=10, ge=1, le=50)


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    division: str = Field(min_length=1, max_length=8)
    season: int = Field(ge=2020, le=2100)


class TeamMemberRequest(BaseModel):
    user_email: EmailStr
    membership_role: str = "student"

class JobCreateRequest(BaseModel):
    job_type: str = Field(
        pattern="^(crawl_source|check_source_metadata|extract_claims|scan_delayed_reviews|discover_sitemap|schedule_due_crawls|deliver_notification_outbox)$"
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: str | None = None


class AssignmentCreateRequest(BaseModel):
    team_id: int
    exam_id: int
    title: str = Field(min_length=2, max_length=255)
    instructions: str = Field(default="", max_length=4000)
    due_at: str | None = None


class ModelQuestionGenerateRequest(QuestionGenerateRequest):
    use_model: bool = True


class LessonProgressRequest(BaseModel):
    current_block: int = Field(ge=0, le=500)
    completed_block_ids: list[str] = Field(default_factory=list, max_length=500)


class LessonCheckpointRequest(BaseModel):
    checkpoint_id: str = Field(min_length=1, max_length=100)
    selected_index: int = Field(ge=0, le=20)


class CrawlDomainPolicyRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    enabled: bool = False
    source_tier: int = Field(default=3, ge=0, le=4)
    default_rights_status: str = "metadata_only"
    max_urls: int = Field(default=10_000, ge=1, le=1_000_000)
    crawl_delay_seconds: float = Field(default=2.0, ge=0.25, le=3600)
    recrawl_minutes: int = Field(default=43_200, ge=5, le=525_600)
    allow_paths: list[str] = Field(default_factory=list, max_length=100)
    deny_paths: list[str] = Field(default_factory=list, max_length=100)
    notes: str = Field(default="", max_length=4000)


class DiscoverySeedRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=500)
    discovery_method: str = Field(default="manual_seed", pattern="^[a-z_]{3,64}$")
    source_tier: int | None = Field(default=None, ge=0, le=4)


class SitemapDiscoveryRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2048)


class PromoteDiscoveredResourceRequest(BaseModel):
    title: str = Field(default="", max_length=500)
    publisher: str = Field(default="", max_length=255)
    rights_status: str | None = None
    license_name: str = Field(default="unknown", max_length=160)


class SourceChangeReviewRequest(BaseModel):
    decision: str = Field(pattern="^(confirmed|false_alarm)$")
    notes: str = Field(default="", max_length=4000)


class SourceWithdrawalRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=4000)


class PracticeAnswerRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=100)
    selected_index: int | None = Field(default=None, ge=0, le=20)
    timed_out: bool = False

    @model_validator(mode="after")
    def answer_or_timeout(self):
        if self.selected_index is None and not self.timed_out:
            raise ValueError("selected_index is required unless the station timed out")
        return self


class PracticeStartRequest(BaseModel):
    mode: str = Field(default="study", pattern="^(study|station)$")
    seconds_per_item: int | None = Field(default=None, ge=15, le=300)


class AdminUserUpdate(BaseModel):
    role: str | None = Field(
        default=None, pattern="^(student|coach|admin|editor|sme|calibrator)$")
    is_active: bool | None = None

    @model_validator(mode="after")
    def at_least_one(self):
        if self.role is None and self.is_active is None:
            raise ValueError("Provide role and/or is_active to update")
        return self


class AnswerKeyUpdate(BaseModel):
    answer: str = Field(min_length=1, max_length=500)
    accepted: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list, max_length=20)
    rubric: str | None = Field(default=None, max_length=2000)
