from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math
import secrets
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from jose import JWTError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.models.entities import (
    AccommodationChange, AccommodationProfile, Assignment, Attempt, AttemptStatus, AuditLog,
    Concept, ContentChallenge, ContentChallengeEvent, Event, Exam, ExamItem, GuardianConsent,
    GenerationRun, Lesson, LessonProgress, LessonVersion, MasteryState, PracticeSession,
    PracticeSet, PracticeSetVersion, Question, QuestionCalibration, QuestionReview, RemediationCase, Response, ResponseRevision, RightsStatus,
    EventSourceMap, EventTaxonScope, RawArtifact, ScientificClaim, Source, SourceSnapshot, SpecimenAsset, Taxon,
    Team, TeamMembership, TransferAttempt, TutorMessage, TutorSession, User, UserNotification,
)
from app.schemas.api import (
    AccommodationUpdateRequest, AdminUserUpdate, AnswerKeyUpdate, ClaimCreateRequest, ClaimExtractionRequest,
    ContentChallengeCreateRequest, ContentChallengeResolveRequest, ContentChallengeTriageRequest,
    ExamCreateRequest,
    FirebaseBootstrapRequest,
    GuardianConsentRequest, LoginRequest,
    LessonCheckpointRequest, LessonProgressRequest, MockExamRequest, PracticeAnswerRequest,
    PracticeStartRequest, QuestionCalibrationRequest, QuestionGenerateRequest, QuestionReviewRequest, ReflectionRequest, RegisterRequest,
    ResponseSaveRequest,
    SourceCreate, TeamCreateRequest, TeamMemberRequest, TransferAnswerRequest,
    TutorMessageRequest, TutorSessionCreateRequest,
)
from app.services.crawler import CrawlError, crawl_source
from app.services.generation import generate_questions
from app.services.claim_extraction import extract_claims
from app.services.scoring import finalize_attempt, score_response, is_gradeable, _question_from_snapshot
from app.services.answer_grading import grade_attempt_overrides, grade_single
from app.services.model_provider import ModelProviderError
from app.services.mock_exam import assemble_mock_exam, event_question_pool
from app.services.blueprint import blueprint_for
from app.services.remediation import build_delayed_review, build_transfer_question, grade_delayed_review, grade_transfer
from app.services.firebase_identity import FirebaseIdentityError, verify_firebase_id_token
from app.services.validation import build_similarity_report
from app.services.source_coverage import event_source_coverage
from app.services.calibration import calculate_item_calibration
from app.services.content_corrections import apply_score_correction
from app.services.notifications import create_notification
from app.services.daily_plan import build_daily_plan
from app.services.tutor import TutorAccessError, create_tutor_session, respond_to_tutor

router = APIRouter(prefix="/api")
_log = logging.getLogger("soplat.api")

# Answer keys / answer sheets are ingested for exam grading, never exposed as
# browsable study materials (a student could otherwise just read the key).
WITHHELD_MATERIAL_PURPOSES = {"answer_key", "answer_sheet"}


def _public_material_url(url: str) -> str:
    return url if url.startswith(("http://", "https://")) else ""


RELEASE_LABELS = {
    "competition_ready": "Competition Ready",
    "foundational_practice": "Foundational Practice",
    "reviewed_practice": "Reviewed Practice",
    "past_test": "Past Test",
    "mock_shuffled": "Mock Exam",
}


def _finalize_graded(db: Session, attempt, submission_kind: str = "system"):
    """Finalize an attempt, applying best-effort LLM grading for short-answer
    responses on EVERY submit path (manual and deadline) so scoring is consistent."""
    try:
        overrides = grade_attempt_overrides(db, attempt)
    except Exception:  # noqa: BLE001 — LLM grading is best-effort; fall back to deterministic
        _log.warning("llm_grading_failed_fell_back_to_deterministic",
                     exc_info=True, extra={"attempt_id": attempt.id})
        overrides = None
    return finalize_attempt(db, attempt, submission_kind=submission_kind, overrides=overrides)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _aware(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalized_evidence(value: str) -> str:
    return " ".join(value.casefold().split())


def _audit(db: Session, actor: User | None, action: str, entity_type: str, entity_id, **details):
    db.add(AuditLog(
        actor_user_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=details,
    ))


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.split(" ", 1)[1]


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    token = _bearer_token(authorization)
    if get_settings().auth_provider == "firebase":
        try:
            claims = verify_firebase_id_token(token)
        except FirebaseIdentityError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        user = db.scalar(select(User).where(User.firebase_uid == claims["uid"]))
    else:
        try:
            user_id = int(decode_access_token(token))
        except (ValueError, JWTError):
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User profile not found or inactive")
    return user


def require_content_staff(user: User = Depends(current_user)) -> User:
    if user.role not in {"admin", "editor", "sme", "calibrator"}:
        raise HTTPException(status_code=403, detail="Content staff role required")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
    return user


def require_exam_manager(user: User = Depends(current_user)) -> User:
    if user.role not in {"admin", "editor", "coach"}:
        raise HTTPException(status_code=403, detail="Exam manager role required")
    return user


def _effective_accommodation(db: Session, user: User, now: datetime | None = None) -> AccommodationProfile | None:
    now = now or datetime.now(timezone.utc)
    profile = db.scalar(select(AccommodationProfile).where(
        AccommodationProfile.user_id == user.id,
        AccommodationProfile.active.is_(True),
    ))
    if not profile:
        return None
    if _aware(profile.effective_from) > now:
        return None
    if profile.effective_until and _aware(profile.effective_until) <= now:
        return None
    return profile


def _accommodation_response(profile: AccommodationProfile | None) -> dict:
    return {
        "active": profile.active if profile else False,
        "time_multiplier": profile.time_multiplier if profile else 1.0,
        "reduced_distraction": profile.reduced_distraction if profile else False,
        "screen_reader_alternative": profile.screen_reader_alternative if profile else False,
        "breaks_allowed": profile.breaks_allowed if profile else False,
        "effective_from": _iso_utc(profile.effective_from) if profile else None,
        "effective_until": _iso_utc(profile.effective_until) if profile else None,
    }


def _managed_student(db: Session, actor: User, student_id: int) -> User:
    student = db.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(status_code=404, detail="Student not found")
    if actor.role == "admin":
        return student
    if not actor.organization_id or student.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Student not found")
    actor_team_ids = set(db.scalars(select(TeamMembership.team_id).where(
        TeamMembership.user_id == actor.id,
        TeamMembership.membership_role == "coach",
    )).all())
    shares_team = db.scalar(select(TeamMembership.id).where(
        TeamMembership.user_id == student.id,
        TeamMembership.team_id.in_(actor_team_ids),
    )) if actor_team_ids else None
    if not shares_team:
        raise HTTPException(status_code=403, detail="Coach must share a team with the student")
    return student


@router.get("/health")
def health():
    return {"status": "ok", "service": get_settings().app_name}


@router.get("/auth/config")
def auth_config():
    settings = get_settings()
    return {
        "provider": settings.auth_provider,
        "firebase_project_id": settings.firebase_project_id
        if settings.auth_provider == "firebase" else None,
        "firebase_web_api_key": settings.firebase_web_api_key
        if settings.auth_provider == "firebase" else None,
    }


@router.get("/auth/me")
def auth_me(user: User = Depends(current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "division": user.division,
    }


@router.get("/me/accommodations")
def my_accommodations(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _accommodation_response(_effective_accommodation(db, user))


@router.put("/students/{student_id}/accommodations")
def update_student_accommodations(
    student_id: int,
    payload: AccommodationUpdateRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_exam_manager),
):
    student = _managed_student(db, actor, student_id)
    profile = db.scalar(select(AccommodationProfile).where(
        AccommodationProfile.user_id == student.id
    ))
    previous = _accommodation_response(profile) if profile else {}
    values = {
        "time_multiplier": payload.time_multiplier,
        "active": payload.active,
        "effective_from": payload.effective_from or datetime.now(timezone.utc),
        "effective_until": payload.effective_until,
        "approved_by_user_id": actor.id,
    }
    if profile:
        for key, value in values.items():
            setattr(profile, key, value)
    else:
        profile = AccommodationProfile(user_id=student.id, **values)
        db.add(profile)
        db.flush()
    new_values = _accommodation_response(profile)
    db.add(AccommodationChange(
        profile_id=profile.id,
        student_user_id=student.id,
        actor_user_id=actor.id,
        previous_values=previous,
        new_values=new_values,
        reason=payload.reason,
    ))
    _audit(db, actor, "accommodation.update", "accommodation_profile", profile.id,
           student_user_id=student.id, previous=previous, current=new_values)
    db.commit()
    db.refresh(profile)
    return {"student_id": student.id, **_accommodation_response(_effective_accommodation(db, student))}


@router.get("/students/{student_id}/accommodations")
def get_student_accommodations(
    student_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_exam_manager),
):
    student = _managed_student(db, actor, student_id)
    profile = db.scalar(select(AccommodationProfile).where(
        AccommodationProfile.user_id == student.id
    ))
    return {"student_id": student.id, "student_name": student.full_name,
            **_accommodation_response(profile)}


@router.post("/auth/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if get_settings().auth_provider != "local":
        raise HTTPException(status_code=404, detail="Use Firebase Authentication to create an account")
    if db.scalar(select(User).where(User.email == payload.email.lower())):
        raise HTTPException(status_code=409, detail="Email already registered")
    requires_consent = payload.age_years is not None and payload.age_years < 13
    if requires_consent and not payload.guardian_email:
        raise HTTPException(status_code=422, detail="Guardian email is required for students under 13")
    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role="student",
        division=payload.division,
        is_active=not requires_consent,
    )
    db.add(user)
    db.flush()
    consent_token = None
    if requires_consent:
        consent_token = secrets.token_urlsafe(32)
        db.add(GuardianConsent(
            student_user_id=user.id,
            guardian_email=str(payload.guardian_email).lower(),
            consent_token_hash=hashlib.sha256(consent_token.encode()).hexdigest(),
        ))
    _audit(db, user, "auth.register", "user", user.id, assigned_role="student", pending_guardian_consent=requires_consent)
    db.commit()
    db.refresh(user)
    result = {
        "access_token": None if requires_consent else create_access_token(str(user.id)),
        "pending_guardian_consent": requires_consent,
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role, "division": user.division},
    }
    if consent_token and get_settings().environment in {"development", "test"}:
        result["development_consent_token"] = consent_token
    return result


@router.post("/auth/guardian-consent")
def guardian_consent(payload: GuardianConsentRequest, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    consent = db.scalar(select(GuardianConsent).where(GuardianConsent.consent_token_hash == token_hash))
    if not consent or consent.status != "pending":
        raise HTTPException(status_code=404, detail="Consent request not found or already used")
    user = db.get(User, consent.student_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Student account not found")
    consent.status = "granted"
    consent.consented_at = datetime.now(timezone.utc)
    user.is_active = True
    _audit(db, user, "guardian.consent", "guardian_consent", consent.id)
    db.commit()
    return {"status": "granted", "student_user_id": user.id}


@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    if get_settings().auth_provider != "local":
        raise HTTPException(status_code=404, detail="Use Firebase Authentication to sign in")
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.password_hash or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _audit(db, user, "auth.login", "user", user.id)
    db.commit()
    return {
        "access_token": create_access_token(str(user.id)),
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role, "division": user.division},
    }


@router.post("/auth/firebase/bootstrap")
def bootstrap_firebase_profile(
    payload: FirebaseBootstrapRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if get_settings().auth_provider != "firebase":
        raise HTTPException(status_code=404, detail="Firebase Authentication is not enabled")
    try:
        claims = verify_firebase_id_token(_bearer_token(authorization))
    except FirebaseIdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    email = str(claims.get("email") or "").strip().lower()
    if not email or not claims.get("email_verified"):
        raise HTTPException(status_code=403, detail="Verify your email with Firebase before creating a profile")
    existing = db.scalar(select(User).where(User.firebase_uid == claims["uid"]))
    if existing:
        return {
            "pending_guardian_consent": not existing.is_active,
            "user": {
                "id": existing.id, "email": existing.email, "full_name": existing.full_name,
                "role": existing.role, "division": existing.division,
            },
        }
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(
            status_code=409,
            detail="An account already uses this email. Ask an administrator to link the identity safely.",
        )
    requires_consent = payload.age_years is not None and payload.age_years < 13
    if requires_consent and not payload.guardian_email:
        raise HTTPException(status_code=422, detail="Guardian email is required for students under 13")
    user = User(
        email=email,
        full_name=payload.full_name,
        password_hash=None,
        firebase_uid=claims["uid"],
        role="student",
        division=payload.division,
        is_active=not requires_consent,
    )
    db.add(user)
    db.flush()
    consent_token = None
    if requires_consent:
        consent_token = secrets.token_urlsafe(32)
        db.add(GuardianConsent(
            student_user_id=user.id,
            guardian_email=str(payload.guardian_email).lower(),
            consent_token_hash=hashlib.sha256(consent_token.encode()).hexdigest(),
        ))
    _audit(db, user, "auth.firebase_bootstrap", "user", user.id, pending_guardian_consent=requires_consent)
    db.commit()
    result = {
        "pending_guardian_consent": requires_consent,
        "user": {
            "id": user.id, "email": user.email, "full_name": user.full_name,
            "role": user.role, "division": user.division,
        },
    }
    if consent_token and get_settings().environment in {"development", "test"}:
        result["development_consent_token"] = consent_token
    return result


@router.get("/events")
def list_events(db: Session = Depends(get_db)):
    events = db.scalars(select(Event).where(Event.active.is_(True)).order_by(Event.name)).all()
    lesson_counts = dict(db.execute(
        select(Lesson.event_id, func.count(Lesson.id))
        .where(Lesson.status == "published").group_by(Lesson.event_id)
    ).all())
    exam_counts = dict(db.execute(
        select(Exam.event_id, func.count(Exam.id))
        .where(Exam.published.is_(True)).group_by(Exam.event_id)
    ).all())
    return [{
        "id": e.id, "slug": e.slug, "name": e.name, "division": e.division,
        "season": e.season, "season_status": e.season_status,
        "modality": e.modality, "description": e.description,
        "category": e.category, "topic_focus": e.topic_focus,
        "official_url": e.official_url,
        "lesson_count": lesson_counts.get(e.id, 0),
        "exam_count": exam_counts.get(e.id, 0),
    } for e in events]


@router.get("/events/{event_id}/concepts")
def list_concepts(event_id: int, db: Session = Depends(get_db)):
    concepts = db.scalars(select(Concept).where(Concept.event_id == event_id).order_by(Concept.name)).all()
    return [{"id": c.id, "name": c.name, "description": c.description, "prerequisites": c.prerequisites} for c in concepts]


@router.get("/events/{event_id}/taxonomy")
def event_taxonomy(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    scopes = db.scalars(select(EventTaxonScope).where(
        EventTaxonScope.event_id == event.id,
    ).order_by(EventTaxonScope.designation, EventTaxonScope.id)).all()
    taxa = db.scalars(select(Taxon).where(
        Taxon.id.in_([scope.taxon_id for scope in scopes])
    )).all() if scopes else []
    taxon_by_id = {taxon.id: taxon for taxon in taxa}
    assets = db.scalars(select(SpecimenAsset).where(
        SpecimenAsset.taxon_id.in_(taxon_by_id),
    )).all() if taxa else []
    assets_by_taxon: dict[int, list[SpecimenAsset]] = {}
    for asset in assets:
        assets_by_taxon.setdefault(asset.taxon_id, []).append(asset)
    approved_rights = {
        RightsStatus.PUBLIC_DOMAIN.value,
        RightsStatus.APPROVED_WITH_ATTRIBUTION.value,
        RightsStatus.DERIVATIVE_GENERATION_ALLOWED.value,
    }
    entries = []
    for scope in scopes:
        taxon = taxon_by_id.get(scope.taxon_id)
        if not taxon:
            continue
        taxon_assets = assets_by_taxon.get(taxon.id, [])
        ready_assets = [asset for asset in taxon_assets if (
            asset.review_status == "approved"
            and asset.rights_status in approved_rights
            and asset.taxon_verified
            and bool(asset.alt_text.strip())
            and bool(asset.long_description.strip())
            and bool(asset.attribution.strip())
        )]
        entries.append({
            "taxon_id": taxon.id,
            "scientific_name": taxon.scientific_name,
            "common_name": taxon.common_name,
            "rank": taxon.rank,
            "parent_id": taxon.parent_id,
            "nomenclatural_status": taxon.nomenclatural_status,
            "taxonomy_authority": taxon.taxonomy_authority,
            "taxonomy_version": taxon.taxonomy_version,
            "diagnostic_traits": taxon.diagnostic_traits,
            "designation": scope.designation,
            "list_version": scope.list_version,
            "reviewed": taxon.reviewed and scope.reviewed,
            "asset_count": len(taxon_assets),
            "ready_asset_count": len(ready_assets),
        })
    official_entries = [entry for entry in entries if entry["designation"] == "official"]
    return {
        "event_id": event.id,
        "event": event.name,
        "season": event.season,
        "scope_status": "official" if official_entries else "foundational",
        "official_list_verified": bool(official_entries) and all(entry["reviewed"] for entry in official_entries),
        "image_release_ready": bool(official_entries) and all(entry["ready_asset_count"] > 0 for entry in official_entries),
        "entries": entries,
    }


def _lesson_version_for_user(db: Session, lesson: Lesson, user: User) -> tuple[LessonVersion, LessonProgress | None]:
    progress = db.scalar(select(LessonProgress).where(
        LessonProgress.lesson_id == lesson.id,
        LessonProgress.user_id == user.id,
    ))
    version_number = progress.lesson_version if progress else lesson.current_version
    version = db.scalar(select(LessonVersion).where(
        LessonVersion.lesson_id == lesson.id,
        LessonVersion.version == version_number,
    ))
    if not version:
        raise HTTPException(status_code=409, detail="Published lesson version is unavailable")
    return version, progress


def _block_id(block: dict, index: int) -> str:
    """Stable id for a lesson block. Only checkpoints are authored with an id;
    every other block type gets a deterministic position id so the reader can
    track completion for it too. Used identically on the serve and validate
    paths so the client's ids always match what the server accepts."""
    return str(block.get("id") or f"b{index}")


def _student_lesson_content(content: list) -> list:
    safe_blocks = []
    for index, block in enumerate(content):
        safe = {key: value for key, value in block.items() if key not in {
            "correct_index", "explanation", "misconception_by_choice",
        }}
        safe["id"] = _block_id(block, index)
        safe_blocks.append(safe)
    return safe_blocks


def _lesson_response(lesson: Lesson, version: LessonVersion, progress: LessonProgress | None) -> dict:
    return {
        "id": lesson.id,
        "event_id": lesson.event_id,
        "concept_id": lesson.concept_id,
        "slug": lesson.slug,
        "title": lesson.title,
        "summary": lesson.summary,
        "estimated_minutes": lesson.estimated_minutes,
        "version": version.version,
        "review_status": version.review_status,
        "content": _student_lesson_content(version.content),
        "citations": version.citations,
        "progress": {
            "status": progress.status if progress else "not_started",
            "current_block": progress.current_block if progress else 0,
            "completed_block_ids": progress.completed_block_ids if progress else [],
            "checkpoint_results": progress.checkpoint_results if progress else {},
        },
    }


@router.get("/events/{event_id}/lessons")
def list_event_lessons(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not db.get(Event, event_id):
        raise HTTPException(status_code=404, detail="Event not found")
    lessons = db.scalars(select(Lesson).where(
        Lesson.event_id == event_id,
        Lesson.status == "published",
    ).order_by(Lesson.sequence, Lesson.id)).all()
    progress_rows = db.scalars(select(LessonProgress).where(
        LessonProgress.user_id == user.id,
        LessonProgress.lesson_id.in_([lesson.id for lesson in lessons]),
    )).all() if lessons else []
    progress_by_lesson = {row.lesson_id: row for row in progress_rows}
    return [{
        "id": lesson.id,
        "slug": lesson.slug,
        "title": lesson.title,
        "summary": lesson.summary,
        "concept_id": lesson.concept_id,
        "sequence": lesson.sequence,
        "estimated_minutes": lesson.estimated_minutes,
        "version": lesson.current_version,
        "progress": {
            "status": progress_by_lesson[lesson.id].status,
            "current_block": progress_by_lesson[lesson.id].current_block,
        } if lesson.id in progress_by_lesson else {"status": "not_started", "current_block": 0},
    } for lesson in lessons]


@router.get("/events/{event_id}/materials")
def list_event_materials(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """List the downloaded reference materials (rules, handouts, sample tests, …)
    linked to an event, with an excerpt of each one's extracted text."""
    if not db.get(Event, event_id):
        raise HTTPException(status_code=404, detail="Event not found")
    mappings = db.scalars(select(EventSourceMap).where(
        EventSourceMap.event_id == event_id,
    ).order_by(EventSourceMap.purpose, EventSourceMap.id)).all()
    materials = []
    for mapping in mappings:
        if mapping.purpose in WITHHELD_MATERIAL_PURPOSES:
            continue
        source = db.get(Source, mapping.source_id)
        if source is None:
            continue
        snapshot = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_id == source.id,
        ).order_by(SourceSnapshot.created_at.desc(), SourceSnapshot.id.desc()))
        artifact = db.scalar(select(RawArtifact).where(
            RawArtifact.snapshot_id == snapshot.id,
        )) if snapshot else None
        text = (snapshot.extracted_text if snapshot else "") or ""
        materials.append({
            "source_id": source.id,
            "title": source.title,
            "url": _public_material_url(source.url),
            "purpose": mapping.purpose,
            "publisher": source.publisher,
            "content_type": snapshot.content_type if snapshot else "",
            "media_type": artifact.detected_media_type if artifact else "",
            "byte_count": artifact.byte_count if artifact else (snapshot.byte_count if snapshot else 0),
            "text_chars": len(text),
            "excerpt": text[:1200],
            "has_text": bool(text.strip()),
            "fetched_at": source.last_successful_crawl_at,
        })
    return {
        "event_id": event_id,
        "material_count": len(materials),
        "materials": materials,
    }


@router.get("/materials/{source_id}")
def get_material_text(
    source_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Return the full extracted text of a single downloaded material."""
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Material not found")
    if (source.metadata_json or {}).get("role") in WITHHELD_MATERIAL_PURPOSES:
        raise HTTPException(status_code=403, detail="This material is not available")
    snapshot = db.scalar(select(SourceSnapshot).where(
        SourceSnapshot.source_id == source.id,
    ).order_by(SourceSnapshot.created_at.desc(), SourceSnapshot.id.desc()))
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Material has no retained content")
    return {
        "source_id": source.id,
        "title": source.title,
        "url": _public_material_url(source.url),
        "final_url": _public_material_url(snapshot.final_url),
        "content_type": snapshot.content_type,
        "text_chars": len(snapshot.extracted_text or ""),
        "extracted_text": snapshot.extracted_text or "",
        "fetched_at": source.last_successful_crawl_at,
    }


@router.post("/lessons/{lesson_id}/start")
def start_lesson(lesson_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    lesson = db.get(Lesson, lesson_id)
    if not lesson or lesson.status != "published":
        raise HTTPException(status_code=404, detail="Lesson not found")
    version, progress = _lesson_version_for_user(db, lesson, user)
    now = datetime.now(timezone.utc)
    if not progress:
        progress = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            lesson_version=version.version,
            status="in_progress",
            started_at=now,
            last_viewed_at=now,
        )
        db.add(progress)
    else:
        if progress.status == "not_started":
            progress.status = "in_progress"
            progress.started_at = now
        progress.last_viewed_at = now
    _audit(db, user, "lesson.start", "lesson", lesson.id, version=version.version)
    db.commit()
    db.refresh(progress)
    return _lesson_response(lesson, version, progress)


@router.put("/lessons/{lesson_id}/progress")
def save_lesson_progress(
    lesson_id: int,
    payload: LessonProgressRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    lesson = db.get(Lesson, lesson_id)
    if not lesson or lesson.status != "published":
        raise HTTPException(status_code=404, detail="Lesson not found")
    version, progress = _lesson_version_for_user(db, lesson, user)
    if not progress:
        raise HTTPException(status_code=409, detail="Start the lesson before saving progress")
    if payload.current_block >= len(version.content):
        raise HTTPException(status_code=422, detail="Lesson block is out of range")
    valid_ids = {_block_id(block, index) for index, block in enumerate(version.content)}
    completed_ids = list(dict.fromkeys(payload.completed_block_ids))
    if not set(completed_ids).issubset(valid_ids):
        raise HTTPException(status_code=422, detail="Completed lesson block is invalid")
    checkpoint_ids = {
        str(block.get("id")) for block in version.content
        if block.get("type") == "checkpoint" and block.get("id")
    }
    invalid_checkpoints = {
        block_id for block_id in completed_ids
        if block_id in checkpoint_ids
        and not (progress.checkpoint_results or {}).get(block_id, {}).get("correct")
    }
    if invalid_checkpoints:
        raise HTTPException(
            status_code=422,
            detail="A checkpoint can be completed only after a correct response",
        )
    progress.current_block = payload.current_block
    progress.completed_block_ids = completed_ids
    progress.last_viewed_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "saved": True,
        "status": progress.status,
        "current_block": progress.current_block,
        "completed_block_ids": progress.completed_block_ids,
    }


@router.post("/lessons/{lesson_id}/checkpoint")
def submit_lesson_checkpoint(
    lesson_id: int,
    payload: LessonCheckpointRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    lesson = db.get(Lesson, lesson_id)
    if not lesson or lesson.status != "published":
        raise HTTPException(status_code=404, detail="Lesson not found")
    version, progress = _lesson_version_for_user(db, lesson, user)
    if not progress:
        raise HTTPException(status_code=409, detail="Start the lesson before answering checkpoints")
    checkpoint = next((block for block in version.content
                       if block.get("type") == "checkpoint" and block.get("id") == payload.checkpoint_id), None)
    if not checkpoint:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    choices = checkpoint.get("choices", [])
    if payload.selected_index >= len(choices):
        raise HTTPException(status_code=422, detail="Checkpoint answer is out of range")
    correct = payload.selected_index == checkpoint.get("correct_index")
    results = dict(progress.checkpoint_results or {})
    previous = results.get(payload.checkpoint_id, {})
    results[payload.checkpoint_id] = {
        "correct": correct,
        "attempts": int(previous.get("attempts", 0)) + 1,
        "selected_index": payload.selected_index,
    }
    progress.checkpoint_results = results
    progress.last_viewed_at = datetime.now(timezone.utc)
    checkpoint_ids = [block["id"] for block in version.content if block.get("type") == "checkpoint"]
    completed = bool(checkpoint_ids) and all(results.get(checkpoint_id, {}).get("correct") for checkpoint_id in checkpoint_ids)
    if completed:
        progress.status = "completed"
        progress.completed_at = datetime.now(timezone.utc)
        if lesson.concept_id:
            mastery = db.scalar(select(MasteryState).where(
                MasteryState.user_id == user.id,
                MasteryState.concept_id == lesson.concept_id,
            ))
            if not mastery:
                mastery = MasteryState(
                    user_id=user.id,
                    concept_id=lesson.concept_id,
                    mastery_probability=0.25,
                    evidence_count=0,
                    misconception_risk=0.5,
                )
            mastery.mastery_probability = max(mastery.mastery_probability, 0.45)
            mastery.evidence_count += 1
            mastery.last_practiced_at = datetime.now(timezone.utc)
            db.add(mastery)
    _audit(db, user, "lesson.checkpoint", "lesson", lesson.id,
           checkpoint_id=payload.checkpoint_id, correct=correct)
    db.commit()
    return {
        "correct": correct,
        "correct_index": checkpoint.get("correct_index"),
        "explanation": checkpoint.get("explanation", ""),
        "misconception": (checkpoint.get("misconception_by_choice") or {}).get(str(payload.selected_index)),
        "lesson_status": progress.status,
        "attempts": results[payload.checkpoint_id]["attempts"],
    }


@router.get("/student/dashboard")
def student_dashboard(
    event_slug: str | None = None,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    mastery_rows = db.scalars(
        select(MasteryState).where(MasteryState.user_id == user.id)
    ).all()
    mastery_by_concept = {row.concept_id: row for row in mastery_rows}
    concepts = db.scalars(
        select(Concept).join(Event).where(Event.active.is_(True)).order_by(Event.name, Concept.name)
    ).all()
    open_cases = db.scalars(
        select(RemediationCase).where(
            RemediationCase.user_id == user.id,
            RemediationCase.status.not_in(["resolved"]),
        ).order_by(RemediationCase.created_at.desc())
    ).all()
    team_ids = db.scalars(
        select(TeamMembership.team_id).where(TeamMembership.user_id == user.id)
    ).all()
    assignments = db.scalars(
        select(Assignment).where(Assignment.team_id.in_(team_ids)).order_by(Assignment.due_at)
    ).all() if team_ids else []
    question_ids = [case.question_id for case in open_cases if case.question_id]
    questions = db.scalars(select(Question).where(Question.id.in_(question_ids))).all() if question_ids else []
    question_by_id = {question.id: question for question in questions}
    return {
        "student": {
            "id": user.id,
            "full_name": user.full_name,
            "division": user.division,
        },
        "concepts": [
            {
                "id": concept.id,
                "event_id": concept.event_id,
                "name": concept.name,
                "description": concept.description,
                "mastery_probability": mastery_by_concept[concept.id].mastery_probability
                if concept.id in mastery_by_concept else 0.0,
                "evidence_count": mastery_by_concept[concept.id].evidence_count
                if concept.id in mastery_by_concept else 0,
                "misconception_risk": mastery_by_concept[concept.id].misconception_risk
                if concept.id in mastery_by_concept else 0.0,
            }
            for concept in concepts
        ],
        "open_remediation": [
            {
                "id": case.id,
                "status": case.status,
                "error_type": case.error_type,
                "question_stem": question_by_id[case.question_id].stem
                if case.question_id in question_by_id
                else (case.diagnosis or {}).get("question_stem", ""),
                "next_action": (case.plan or {}).get("next_step", "Continue guided practice"),
                "source_type": case.source_type,
                "diagnosis": case.diagnosis,
                "plan": case.plan,
                "student_reflection": case.student_reflection,
                "next_review_at": (case.plan or {}).get("next_review_at"),
            }
            for case in open_cases
        ],
        "assignments": [
            {
                "id": assignment.id,
                "title": assignment.title,
                "exam_id": assignment.exam_id,
                "due_at": assignment.due_at,
            }
            for assignment in assignments
        ],
        "daily_plan": build_daily_plan(db, user, event_slug),
    }


def _tutor_message_payload(message: TutorMessage) -> dict:
    return {
        "id": message.id, "role": message.role, "content": message.content,
        "citations": message.citations, "verification": message.verification,
        "created_at": _iso_utc(message.created_at),
    }


@router.post("/tutor/sessions")
def start_tutor_session(
    payload: TutorSessionCreateRequest,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    try:
        session = create_tutor_session(
            db, user, payload.context_type, payload.context_id, payload.mode
        )
    except TutorAccessError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(db, user, "tutor.session_start", "tutor_session", session.id,
           context_type=session.context_type, context_id=session.context_id, mode=session.mode)
    db.commit()
    return {
        "id": session.id, "context_type": session.context_type,
        "context_id": session.context_id, "context_version": session.context_version,
        "mode": session.mode, "status": session.status,
    }


@router.get("/tutor/sessions/{session_id}")
def get_tutor_session(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    session = db.get(TutorSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Tutor session not found")
    messages = db.scalars(select(TutorMessage).where(
        TutorMessage.session_id == session.id
    ).order_by(TutorMessage.id)).all()
    return {
        "id": session.id, "context_type": session.context_type,
        "context_id": session.context_id, "mode": session.mode,
        "status": session.status,
        "messages": [_tutor_message_payload(message) for message in messages],
    }


@router.post("/tutor/sessions/{session_id}/messages")
def send_tutor_message(
    session_id: int, payload: TutorMessageRequest,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    session = db.get(TutorSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Tutor session not found")
    try:
        message = respond_to_tutor(db, user, session, payload.message)
    except TutorAccessError as exc:
        status = 429 if "limit reached" in str(exc).lower() else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    _audit(db, user, "tutor.message", "tutor_session", session.id,
           assistant_message_id=message.id, provider=message.provider,
           claim_ids=(message.verification or {}).get("claim_ids", []))
    db.commit()
    return _tutor_message_payload(message)


def _practice_version(db: Session, practice_set: PracticeSet, version: int) -> PracticeSetVersion:
    row = db.scalar(select(PracticeSetVersion).where(
        PracticeSetVersion.practice_set_id == practice_set.id,
        PracticeSetVersion.version == version,
    ))
    if not row:
        raise HTTPException(status_code=409, detail="Practice set version is unavailable")
    return row


def _safe_practice_item(item: dict | None) -> dict | None:
    if not item:
        return None
    return {
        key: value for key, value in item.items()
        if key not in {"correct_index", "explanation", "misconception_by_choice"}
    }


def _practice_item_by_id(version: PracticeSetVersion, item_id: str) -> dict | None:
    return next((item for item in version.items if item.get("id") == item_id), None)


def _practice_session_response(
    practice_set: PracticeSet,
    version: PracticeSetVersion,
    session: PracticeSession,
) -> dict:
    current_id = (
        session.item_order[session.current_index]
        if session.current_index < len(session.item_order) else None
    )
    current_item = _practice_item_by_id(version, current_id) if current_id else None
    return {
        "session_id": session.id,
        "practice_set": {
            "id": practice_set.id,
            "title": practice_set.title,
            "summary": practice_set.summary,
            "practice_type": practice_set.practice_type,
            "version": version.version,
            "review_status": version.review_status,
            "citations": version.citations,
        },
        "status": session.status,
        "mode": session.mode,
        "time_multiplier": session.time_multiplier,
        "accommodation_applied": session.time_multiplier > 1.0,
        "base_seconds_per_item": session.base_seconds_per_item,
        "seconds_per_item": session.seconds_per_item,
        "item_deadline_at": _iso_utc(
            _aware(session.item_started_at) + timedelta(seconds=session.seconds_per_item)
        ) if session.mode == "station" and session.seconds_per_item and current_item else None,
        "current_index": session.current_index,
        "total_items": len(session.item_order),
        "score": session.score,
        "current_item": _safe_practice_item(current_item),
    }


@router.get("/events/{event_id}/practice-sets")
def list_practice_sets(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not db.get(Event, event_id):
        raise HTTPException(status_code=404, detail="Event not found")
    sets = db.scalars(select(PracticeSet).where(
        PracticeSet.event_id == event_id,
        PracticeSet.status == "published",
    ).order_by(PracticeSet.id)).all()
    sessions = db.scalars(select(PracticeSession).where(
        PracticeSession.user_id == user.id,
        PracticeSession.practice_set_id.in_([row.id for row in sets]),
    ).order_by(PracticeSession.id.desc())).all() if sets else []
    latest = {}
    for session in sessions:
        latest.setdefault(session.practice_set_id, session)
    return [{
        "id": row.id,
        "slug": row.slug,
        "title": row.title,
        "summary": row.summary,
        "practice_type": row.practice_type,
        "estimated_minutes": row.estimated_minutes,
        "version": row.current_version,
        "latest_session": {
            "id": latest[row.id].id,
            "status": latest[row.id].status,
            "score": latest[row.id].score,
            "current_index": latest[row.id].current_index,
            "total_items": len(latest[row.id].item_order),
            "mode": latest[row.id].mode,
        } if row.id in latest else None,
    } for row in sets]


@router.post("/practice-sets/{practice_set_id}/start")
def start_practice_set(
    practice_set_id: int,
    payload: PracticeStartRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    practice_set = db.get(PracticeSet, practice_set_id)
    if not practice_set or practice_set.status != "published":
        raise HTTPException(status_code=404, detail="Practice set not found")
    requested = payload or PracticeStartRequest()
    accommodation = _effective_accommodation(db, user)
    time_multiplier = accommodation.time_multiplier if accommodation else 1.0
    base_seconds_per_item = (requested.seconds_per_item or 45) if requested.mode == "station" else None
    seconds_per_item = (
        math.ceil(base_seconds_per_item * time_multiplier)
        if base_seconds_per_item is not None else None
    )
    session = db.scalar(select(PracticeSession).where(
        PracticeSession.user_id == user.id,
        PracticeSession.practice_set_id == practice_set.id,
        PracticeSession.status == "in_progress",
        PracticeSession.mode == requested.mode,
        PracticeSession.base_seconds_per_item == base_seconds_per_item,
    ).order_by(PracticeSession.id.desc()))
    if session:
        version = _practice_version(db, practice_set, session.practice_set_version)
        session.last_active_at = datetime.now(timezone.utc)
    else:
        version = _practice_version(db, practice_set, practice_set.current_version)
        if version.review_status not in {"sme_approved", "calibrated"}:
            raise HTTPException(status_code=409, detail="Practice set has not completed review")
        item_ids = [str(item["id"]) for item in version.items if item.get("id")]
        if not item_ids:
            raise HTTPException(status_code=409, detail="Practice set contains no items")
        session = PracticeSession(
            user_id=user.id,
            practice_set_id=practice_set.id,
            practice_set_version=version.version,
            mode=requested.mode,
            time_multiplier=time_multiplier,
            base_seconds_per_item=base_seconds_per_item,
            seconds_per_item=seconds_per_item,
            item_started_at=datetime.now(timezone.utc),
            item_order=item_ids,
            status="in_progress",
            current_index=0,
            results={},
            score=0,
        )
        db.add(session)
        db.flush()
        _audit(db, user, "practice.start", "practice_session", session.id,
               practice_set_id=practice_set.id, version=version.version, mode=requested.mode,
               time_multiplier=time_multiplier, base_seconds_per_item=base_seconds_per_item)
    db.commit()
    db.refresh(session)
    return _practice_session_response(practice_set, version, session)


@router.post("/practice/sessions/{session_id}/answer")
def answer_practice_item(
    session_id: int,
    payload: PracticeAnswerRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    session = db.get(PracticeSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Practice session not found")
    practice_set = db.get(PracticeSet, session.practice_set_id)
    version = _practice_version(db, practice_set, session.practice_set_version)
    existing = (session.results or {}).get(payload.item_id)
    if existing:
        return {**existing, "duplicate": True, **_practice_session_response(
            practice_set, version, session
        )}
    if session.status != "in_progress":
        raise HTTPException(status_code=409, detail="Practice session is already complete")
    expected_id = session.item_order[session.current_index]
    if payload.item_id != expected_id:
        raise HTTPException(status_code=409, detail="Answer the current practice item first")
    item = _practice_item_by_id(version, payload.item_id)
    if not item:
        raise HTTPException(status_code=409, detail="Practice item is unavailable")
    deadline = (
        _aware(session.item_started_at) + timedelta(seconds=session.seconds_per_item)
        if session.mode == "station" and session.seconds_per_item else None
    )
    now = datetime.now(timezone.utc)
    expired = bool(deadline and now >= deadline)
    if payload.timed_out and not expired:
        raise HTTPException(status_code=409, detail="Station time has not expired")
    timed_out = expired or payload.timed_out
    choices = item.get("choices", [])
    if not timed_out and payload.selected_index is not None and payload.selected_index >= len(choices):
        raise HTTPException(status_code=422, detail="Practice answer is out of range")
    correct = False if timed_out else payload.selected_index == item.get("correct_index")
    remediation_case = None
    if not correct:
        source_ref = f"practice:{session.id}:{payload.item_id}"
        remediation_case = db.scalar(select(RemediationCase).where(
            RemediationCase.user_id == user.id,
            RemediationCase.source_type == "practice",
            RemediationCase.source_ref == source_ref,
        ))
        if not remediation_case:
            remediation_case = RemediationCase(
                attempt_id=None,
                user_id=user.id,
                question_id=None,
                concept_id=practice_set.concept_id,
                source_type="practice",
                source_ref=source_ref,
                error_type="time_management" if timed_out else (
                    "data_reasoning" if practice_set.practice_type == "data_interpretation"
                    else "misidentification"
                ),
                diagnosis={
                    "question_stem": item.get("prompt", "Identify the specimen."),
                    "student_answer": None if timed_out else choices[payload.selected_index],
                    "correct_answer": choices[item.get("correct_index", 0)],
                    "timed_out": timed_out,
                    "evidence_profile": item.get("property_profile", []),
                    "transfer_source": {
                        "question_type": "single_choice",
                        "stem": item.get("prompt", "Identify the specimen."),
                        "choices": choices,
                        "answer_spec": {"correct_index": item.get("correct_index", 0)},
                        "explanation": item.get("explanation", ""),
                        "concept_id": practice_set.concept_id,
                    },
                },
                plan={
                    "steps": [
                        "Name the diagnostic evidence you overlooked",
                        "Compare your choice with the keyed specimen",
                        "Complete an unseen identification check",
                        "Return for a delayed retention check",
                    ],
                    "explanation": item.get("explanation", ""),
                    "citations": version.citations,
                    "next_step": "Explain which clue should drive your next identification",
                    "resolution_requires": "delayed_unseen_check",
                },
            )
            db.add(remediation_case)
            db.flush()
    result = {
        "item_id": payload.item_id,
        "selected_index": None if timed_out else payload.selected_index,
        "timed_out": timed_out,
        "correct": correct,
        "correct_index": item.get("correct_index"),
        "explanation": item.get("explanation", ""),
        "misconception": "Station time expired before an identification was committed."
        if timed_out else (item.get("misconception_by_choice") or {}).get(
            str(payload.selected_index)
        ),
        "remediation_case_id": remediation_case.id if remediation_case else None,
    }
    results = dict(session.results or {})
    results[payload.item_id] = result
    session.results = results
    session.score += 1 if correct else 0
    session.current_index += 1
    session.last_active_at = now
    session.item_started_at = now
    if session.current_index >= len(session.item_order):
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        if practice_set.concept_id:
            mastery = db.scalar(select(MasteryState).where(
                MasteryState.user_id == user.id,
                MasteryState.concept_id == practice_set.concept_id,
            ))
            if not mastery:
                mastery = MasteryState(
                    user_id=user.id,
                    concept_id=practice_set.concept_id,
                    mastery_probability=0.25,
                    evidence_count=0,
                    misconception_risk=0.5,
                )
            accuracy = session.score / len(session.item_order)
            mastery.mastery_probability = max(
                mastery.mastery_probability,
                min(0.75, 0.3 + accuracy * 0.45),
            )
            mastery.misconception_risk = max(0.0, 1.0 - accuracy)
            mastery.evidence_count += len(session.item_order)
            mastery.last_practiced_at = datetime.now(timezone.utc)
            db.add(mastery)
    _audit(db, user, "practice.answer", "practice_session", session.id,
           item_id=payload.item_id, correct=correct, timed_out=timed_out)
    db.commit()
    db.refresh(session)
    response = _practice_session_response(practice_set, version, session)
    return {**result, "duplicate": False, **response}


@router.post("/sources")
def create_source(payload: SourceCreate, db: Session = Depends(get_db), actor: User = Depends(require_content_staff)):
    if db.scalar(select(Source).where(Source.url == payload.url)):
        raise HTTPException(status_code=409, detail="Source already exists")
    valid_rights = {status.value for status in RightsStatus}
    if payload.rights_status not in valid_rights:
        raise HTTPException(status_code=422, detail="Unknown rights status")
    source = Source(
        url=payload.url, title=payload.title or payload.url, publisher=payload.publisher,
        rights_status=payload.rights_status, license_name=payload.license_name,
    )
    db.add(source)
    db.flush()
    _audit(db, actor, "source.create", "source", source.id, rights_status=source.rights_status)
    db.commit()
    db.refresh(source)
    return {"id": source.id, "url": source.url, "rights_status": source.rights_status, "approved": source.approved}


@router.post("/sources/{source_id}/approve")
def approve_source(source_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.rights_status in {RightsStatus.BLOCKED.value, RightsStatus.QUARANTINED.value}:
        raise HTTPException(status_code=400, detail="Blocked sources cannot be approved")
    source.approved = True
    _audit(db, actor, "source.approve", "source", source.id, rights_status=source.rights_status)
    db.commit()
    return {"id": source.id, "approved": True}


@router.post("/sources/{source_id}/crawl")
def crawl(source_id: int, db: Session = Depends(get_db), actor: User = Depends(require_content_staff)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        result = crawl_source(db, source)
    except (CrawlError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(db, actor, "source.crawl", "source", source.id, content_hash=result.content_hash)
    db.commit()
    return {
        "id": result.id, "content_hash": result.content_hash, "fetched_at": result.fetched_at,
        "characters": len(result.extracted_text or ""), "final_url": result.metadata_json.get("final_url"),
    }




@router.post("/sources/{source_id}/extract-claims")
def extract_source_claims(source_id: int, payload: ClaimExtractionRequest, db: Session = Depends(get_db), actor: User = Depends(require_content_staff)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if payload.concept_id and not db.get(Concept, payload.concept_id):
        raise HTTPException(status_code=404, detail="Concept not found")
    try:
        rows = extract_claims(db, source, payload.concept_id, payload.limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(db, actor, "claim.extract", "source", source.id, claim_count=len(rows))
    db.commit()
    return [{"id": row.id, "claim_text": row.claim_text, "confidence": row.confidence, "approved": row.approved} for row in rows]


@router.post("/claims")
def create_claim(payload: ClaimCreateRequest, db: Session = Depends(get_db), actor: User = Depends(require_content_staff)):
    source = db.get(Source, payload.source_id)
    if not source or not source.approved:
        raise HTTPException(status_code=400, detail="Claim source must be approved")
    if payload.concept_id and not db.get(Concept, payload.concept_id):
        raise HTTPException(status_code=404, detail="Concept not found")
    snapshot = db.get(SourceSnapshot, payload.source_snapshot_id)
    if not snapshot or snapshot.source_id != source.id:
        raise HTTPException(status_code=400, detail="Claim snapshot must belong to the approved source")
    claim = ScientificClaim(
        source_id=source.id, source_snapshot_id=snapshot.id,
        concept_id=payload.concept_id, claim_text=payload.claim_text,
        evidence_excerpt=payload.evidence_excerpt, locator=payload.locator,
        confidence=payload.confidence, approved=False,
    )
    db.add(claim)
    db.flush()
    _audit(db, actor, "claim.create", "scientific_claim", claim.id, source_id=source.id, source_snapshot_id=snapshot.id)
    db.commit()
    db.refresh(claim)
    return {"id": claim.id, "approved": claim.approved, "claim_text": claim.claim_text}


@router.post("/claims/{claim_id}/approve")
def approve_claim(claim_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    claim = db.get(ScientificClaim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    source = db.get(Source, claim.source_id)
    if not source or not source.approved:
        raise HTTPException(status_code=400, detail="Claim source must remain approved")
    snapshot = db.get(SourceSnapshot, claim.source_snapshot_id) if claim.source_snapshot_id else None
    if not snapshot or snapshot.source_id != source.id:
        raise HTTPException(status_code=400, detail="Claim requires an immutable snapshot from its source")
    excerpt = _normalized_evidence(claim.evidence_excerpt)
    snapshot_text = _normalized_evidence(snapshot.extracted_text)
    if len(excerpt) < 12 or excerpt not in snapshot_text:
        raise HTTPException(status_code=400, detail="Evidence excerpt must quote text present in the linked snapshot")
    if not claim.locator.strip():
        raise HTTPException(status_code=400, detail="Claim requires a human-readable evidence locator")
    claim.approved = True
    _audit(db, actor, "claim.approve", "scientific_claim", claim.id)
    db.commit()
    return {"id": claim.id, "approved": True}


@router.post("/questions/generate")
def generate(payload: QuestionGenerateRequest, db: Session = Depends(get_db), actor: User = Depends(require_content_staff)):
    event = db.get(Event, payload.event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    concept = db.get(Concept, payload.concept_id) if payload.concept_id else None
    if concept and concept.event_id != event.id:
        raise HTTPException(status_code=400, detail="Concept does not belong to event")
    questions = generate_questions(db, event, concept, payload.count, payload.difficulty, payload.cognitive_level, payload.question_type)
    run = GenerationRun(
        actor_user_id=actor.id, event_id=event.id, concept_id=concept.id if concept else None,
        provider=questions[0].generation_provenance.get("provider", "unknown") if questions else "unknown",
        model=questions[0].generation_provenance.get("model", "") if questions else "",
        prompt_version="question-generation-v3",
        request_json=payload.model_dump(),
        result_json={"question_ids": [q.id for q in questions]},
        status="completed",
    )
    db.add(run)
    for question in questions:
        _audit(db, actor, "question.generate", "question", question.id, event_id=event.id)
    db.commit()
    return [{
        "id": q.id, "stem": q.stem, "choices": q.choices, "status": q.status,
        "validation_report": q.validation_report,
    } for q in questions]


def _snapshot_question(q: Question) -> dict:
    return {
        "question_id": q.id, "question_version": q.version, "concept_id": q.concept_id,
        "question_type": q.question_type, "stem": q.stem, "choices": q.choices,
        "assets": q.assets or [],
        "answer_spec": q.answer_spec, "explanation": q.explanation, "citations": q.citations,
        "difficulty": q.difficulty, "cognitive_level": q.cognitive_level,
        "estimated_seconds": q.estimated_seconds,
    }


REVIEW_CHECKS = {
    "editor": {"clear_language", "single_best_answer", "distractors_plausible", "age_appropriate", "original_wording"},
    "sme": {"factually_supported", "answer_key_verified", "citations_verified", "no_material_ambiguity"},
}


def _citation_evidence(db: Session, question: Question) -> list[dict]:
    evidence = []
    for citation in question.citations or []:
        claim = db.get(ScientificClaim, citation.get("claim_id")) if citation.get("claim_id") else None
        source = db.get(Source, claim.source_id) if claim else None
        snapshot = db.get(SourceSnapshot, claim.source_snapshot_id) if claim and claim.source_snapshot_id else None
        evidence.append({
            "claim_id": claim.id if claim else citation.get("claim_id"),
            "claim_text": claim.claim_text if claim else "",
            "evidence_excerpt": claim.evidence_excerpt if claim else "",
            "locator": claim.locator if claim else "",
            "approved": bool(claim and claim.approved),
            "source_id": source.id if source else citation.get("source_id"),
            "source_title": source.title if source else "Missing source",
            "source_url": source.url if source else "",
            "snapshot_id": snapshot.id if snapshot else None,
            "snapshot_hash": snapshot.content_hash if snapshot else "",
        })
    return evidence


@router.get("/content/questions/review-queue")
def question_review_queue(db: Session = Depends(get_db), actor: User = Depends(require_content_staff)):
    allowed = ["machine_validated"] if actor.role == "editor" else ["machine_validated", "editor_reviewed", "sme_approved"]
    questions = db.scalars(select(Question).where(Question.status.in_(allowed)).order_by(Question.created_at)).all()
    return [{
        "id": q.id, "version": q.version, "status": q.status, "event_id": q.event_id,
        "stem": q.stem, "choices": q.choices, "answer_spec": q.answer_spec,
        "explanation": q.explanation, "citations": q.citations,
        "citation_evidence": _citation_evidence(db, q),
        "validation_report": q.validation_report, "similarity_report": q.similarity_report,
    } for q in questions]


@router.post("/content/questions/{question_id}/reviews")
def review_question(question_id: int, payload: QuestionReviewRequest, db: Session = Depends(get_db), actor: User = Depends(require_content_staff)):
    question = db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if payload.stage == "editor" and actor.role not in {"editor", "admin"}:
        raise HTTPException(status_code=403, detail="Editor or administrator role required")
    if payload.stage == "sme" and actor.role not in {"sme", "admin"}:
        raise HTTPException(status_code=403, detail="SME or administrator role required")
    expected_status = "machine_validated" if payload.stage == "editor" else "editor_reviewed"
    if question.status != expected_status:
        raise HTTPException(status_code=409, detail=f"{payload.stage} review requires question status {expected_status}")
    missing = sorted(REVIEW_CHECKS[payload.stage] - {key for key, passed in payload.checklist.items() if passed})
    if payload.decision == "approved" and missing:
        raise HTTPException(status_code=422, detail={"message": "Required review checks are incomplete", "missing_checks": missing})
    if payload.stage == "sme":
        editor = db.scalar(select(QuestionReview).where(
            QuestionReview.question_id == question.id,
            QuestionReview.question_version == question.version,
            QuestionReview.stage == "editor",
            QuestionReview.decision == "approved",
        ).order_by(QuestionReview.created_at.desc()))
        if not editor:
            raise HTTPException(status_code=409, detail="An editor approval for this version is required")
        if editor.reviewer_user_id == actor.id:
            raise HTTPException(status_code=409, detail="SME approval must be independent from editor approval")
    review = QuestionReview(
        question_id=question.id, question_version=question.version, stage=payload.stage,
        decision=payload.decision, reviewer_user_id=actor.id,
        checklist=payload.checklist, notes=payload.notes,
    )
    db.add(review)
    if payload.decision == "approved":
        question.status = "editor_reviewed" if payload.stage == "editor" else "sme_approved"
    else:
        question.status = "draft"
    _audit(db, actor, "question.review", "question", question.id, stage=payload.stage, decision=payload.decision, version=question.version)
    db.commit()
    db.refresh(review)
    return {"review_id": review.id, "question_id": question.id, "version": question.version, "status": question.status}


@router.post("/content/questions/{question_id}/publish")
def publish_question(question_id: int, db: Session = Depends(get_db), actor: User = Depends(require_content_staff)):
    if actor.role not in {"sme", "admin"}:
        raise HTTPException(status_code=403, detail="SME or administrator role required")
    question = db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if question.status != "sme_approved":
        raise HTTPException(status_code=409, detail="Current question version requires editor and independent SME approval")
    blockers = []
    if not (question.validation_report or {}).get("passed"):
        blockers.append("machine_validation_not_passed")
    if not question.citations:
        blockers.append("citations_required")
    similarity = question.similarity_report or build_similarity_report(
        db, question.stem, question.choices or [], exclude_question_id=question.id
    )
    question.similarity_report = similarity
    if similarity.get("outcome") == "blocked":
        blockers.append("similarity_blocked")
    claim_ids = {citation.get("claim_id") for citation in question.citations if citation.get("claim_id")}
    approved_claims = db.scalars(select(ScientificClaim).where(
        ScientificClaim.id.in_(claim_ids), ScientificClaim.approved.is_(True),
        ScientificClaim.source_snapshot_id.is_not(None),
    )).all() if claim_ids else []
    if len(approved_claims) != len(claim_ids):
        blockers.append("approved_claim_evidence_required")
    claims_by_id = {claim.id: claim for claim in approved_claims}
    for citation in question.citations:
        claim = claims_by_id.get(citation.get("claim_id"))
        if claim and citation.get("source_id") != claim.source_id:
            blockers.append("citation_source_claim_mismatch")
            break
    if blockers:
        db.rollback()
        raise HTTPException(status_code=409, detail={"message": "Question is not release-ready", "blockers": blockers})
    question.status = "published"
    _audit(db, actor, "question.publish", "question", question.id, version=question.version)
    db.commit()
    return {"question_id": question.id, "version": question.version, "status": question.status}


@router.get("/content/questions/calibration-queue")
def calibration_queue(db: Session = Depends(get_db), actor: User = Depends(require_content_staff)):
    questions = db.scalars(select(Question).where(
        Question.status == "published"
    ).order_by(Question.created_at)).all()
    return [{
        "id": question.id, "version": question.version, "event_id": question.event_id,
        "stem": question.stem, "choices": question.choices,
        **calculate_item_calibration(db, question),
    } for question in questions]


@router.post("/content/questions/{question_id}/calibration")
def calibrate_question(
    question_id: int, payload: QuestionCalibrationRequest,
    db: Session = Depends(get_db), actor: User = Depends(require_content_staff),
):
    if actor.role not in {"calibrator", "admin"}:
        raise HTTPException(status_code=403, detail="Calibrator or administrator role required")
    question = db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if question.status != "published":
        raise HTTPException(status_code=409, detail="Calibration requires a published practice question version")
    prior_reviewers = set(db.scalars(select(QuestionReview.reviewer_user_id).where(
        QuestionReview.question_id == question.id,
        QuestionReview.question_version == question.version,
        QuestionReview.decision == "approved",
    )).all())
    if actor.id in prior_reviewers:
        raise HTTPException(status_code=409, detail="Calibration review must be independent from editorial and SME approval")
    result = calculate_item_calibration(db, question)
    if payload.decision == "accepted" and not result["passed"]:
        raise HTTPException(status_code=409, detail={
            "message": "Pilot evidence does not meet calibration thresholds",
            "failures": result["failures"], "metrics": result["metrics"],
        })
    record = QuestionCalibration(
        question_id=question.id, question_version=question.version,
        sample_size=result["metrics"]["sample_size"], metrics=result["metrics"],
        thresholds=result["thresholds"], deterministic_passed=result["passed"],
        decision=payload.decision, reviewer_user_id=actor.id, notes=payload.notes,
    )
    db.add(record)
    if payload.decision == "accepted":
        question.status = "calibrated"
    _audit(db, actor, "question.calibrate", "question", question.id,
           version=question.version, decision=payload.decision, sample_size=record.sample_size)
    db.commit()
    db.refresh(record)
    return {
        "calibration_id": record.id, "question_id": question.id,
        "version": question.version, "status": question.status,
        "decision": record.decision, "metrics": record.metrics,
    }


@router.get("/events/{event_id}/blueprint")
def get_event_blueprint(event_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The event's test blueprint (LLM-analyzed if available, else derived from
    its question pool) plus how many questions are available to draw from."""
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    pool = event_question_pool(db, event)
    if not pool:
        raise HTTPException(status_code=409, detail="No questions available for this event yet")
    return {"event_id": event.id, "slug": event.slug, "pool_size": len(pool),
            "blueprint": blueprint_for(db, event, pool)}


@router.post("/exams/mock")
def create_mock_exam(
    payload: MockExamRequest, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    """Assemble a fresh shuffled mock exam from an event's past-test question pool.
    Any signed-in student can generate one; each call is a new randomized draw."""
    event = db.get(Event, payload.event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    try:
        exam = assemble_mock_exam(
            db, event, size=payload.size, feedback_mode=payload.feedback_mode,
            shuffle_choices=payload.shuffle_choices, title=payload.title,
            use_blueprint=payload.use_blueprint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _audit(db, user, "exam.mock_create", "exam", exam.id,
           event_id=event.id, size=len(exam.question_ids))
    db.commit()
    return {
        "exam_id": exam.id,
        "title": exam.title,
        "question_count": len(exam.question_ids),
        "duration_minutes": exam.duration_minutes,
        "feedback_mode": payload.feedback_mode,
        "release_class": exam.release_class,
    }


@router.post("/exams")
def create_exam(payload: ExamCreateRequest, db: Session = Depends(get_db), actor: User = Depends(require_exam_manager)):
    event = db.get(Event, payload.event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    coverage = event_source_coverage(db, event)
    if payload.release_class == "competition_ready":
        blockers = []
        if event.season_status != "current":
            blockers.append("event_is_not_current_season")
        if not coverage["summary"]["competition_release_ready"]:
            blockers.append("event_source_coverage_not_release_ready")
        if blockers:
            raise HTTPException(status_code=409, detail={
                "message": "Competition-ready release is blocked",
                "blockers": blockers,
                "coverage": coverage["summary"],
                "next_step": "Resolve the event source-map and freshness gaps before release",
            })
    allowed_statuses = ["calibrated"] if payload.release_class == "competition_ready" else ["published", "calibrated"]
    questions = db.scalars(
        select(Question).where(
            Question.event_id == event.id,
            Question.status.in_(allowed_statuses),
        ).limit(payload.question_count)
    ).all()
    if len(questions) < payload.question_count:
        raise HTTPException(status_code=409, detail={
            "message": "Not enough published questions for this exam",
            "requested": payload.question_count,
            "available": len(questions),
            "next_step": "Generate, validate, independently review, publish, and calibrate questions required for this release class",
        })
    selected = questions[:payload.question_count]
    if payload.release_class == "competition_ready":
        missing_calibration = []
        for question in selected:
            calibration = db.scalar(select(QuestionCalibration).where(
                QuestionCalibration.question_id == question.id,
                QuestionCalibration.question_version == question.version,
                QuestionCalibration.decision == "accepted",
                QuestionCalibration.deterministic_passed.is_(True),
            ).order_by(QuestionCalibration.created_at.desc(), QuestionCalibration.id.desc()))
            if not calibration:
                missing_calibration.append(question.id)
        if missing_calibration:
            raise HTTPException(status_code=409, detail={
                "message": "Competition-ready release requires accepted calibration evidence",
                "blockers": ["calibration_evidence_missing"],
                "question_ids": missing_calibration,
            })
    release_class = payload.release_class
    if release_class == "reviewed_practice" and event.season_status != "current":
        release_class = "foundational_practice"
    coverage_snapshot = {
        "captured_at": _iso_utc(datetime.now(timezone.utc)),
        "event": coverage["event"],
        "summary": coverage["summary"],
        "sources": [{
            "source_id": row["source_id"], "coverage_state": row["coverage_state"],
            "source_universe_version": row["source_universe_version"],
        } for row in coverage["sources"]],
    }
    exam = Exam(
        event_id=event.id, organization_id=actor.organization_id, title=payload.title,
        duration_minutes=payload.duration_minutes, question_ids=[q.id for q in selected],
        published=payload.published,
        release_class=release_class, coverage_snapshot=coverage_snapshot,
        published_by_user_id=actor.id if payload.published else None,
        published_at=datetime.now(timezone.utc) if payload.published else None,
        blueprint={"question_count": payload.question_count, "event": event.slug, "snapshot_schema": 1,
                   "requested_release_class": payload.release_class},
    )
    db.add(exam)
    db.flush()
    for position, question in enumerate(selected):
        db.add(ExamItem(
            exam_id=exam.id, question_id=question.id, question_version=question.version,
            position=position, snapshot=_snapshot_question(question),
        ))
    _audit(db, actor, "exam.create", "exam", exam.id, published=exam.published, question_count=len(selected))
    db.commit()
    db.refresh(exam)
    return {
        "id": exam.id, "title": exam.title, "duration_minutes": exam.duration_minutes,
        "question_count": len(selected), "published": exam.published,
        "release_class": exam.release_class,
    }


@router.get("/exams")
def list_exams(db: Session = Depends(get_db), user: User = Depends(current_user)):
    # Ephemeral, per-student shuffled mock exams are not part of the shared catalog;
    # they are taken immediately after generation, not browsed here.
    query = select(Exam).where(Exam.published.is_(True), Exam.release_class != "mock_shuffled")
    if user.organization_id is not None:
        query = query.where((Exam.organization_id.is_(None)) | (Exam.organization_id == user.organization_id))
    else:
        query = query.where(Exam.organization_id.is_(None))
    exams = db.scalars(query.order_by(Exam.created_at.desc())).all()
    accommodation = _effective_accommodation(db, user)
    multiplier = accommodation.time_multiplier if accommodation else 1.0
    return [{
        "id": e.id, "title": e.title, "duration_minutes": e.duration_minutes,
        "effective_duration_minutes": math.ceil(e.duration_minutes * multiplier),
        "time_multiplier": multiplier,
        "accommodation_applied": multiplier > 1.0,
        "event_id": e.event.id, "event_slug": e.event.slug,
        "event": e.event.name, "event_division": e.event.division,
        "question_count": len(e.question_ids),
        "event_season": e.event.season, "season_status": e.event.season_status,
        "release_class": e.release_class,
        "release_label": RELEASE_LABELS.get(e.release_class, "Reviewed Practice"),
    } for e in exams]


@router.post("/exams/{exam_id}/start")
def start_exam(
    exam_id: int, x_exam_client_session: str | None = Header(default=None),
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    if x_exam_client_session and (
        not 8 <= len(x_exam_client_session) <= 80
        or not all(character.isalnum() or character in {"-", "_"} for character in x_exam_client_session)
    ):
        raise HTTPException(status_code=422, detail="Invalid exam client session identifier")
    exam = db.get(Exam, exam_id)
    held_attempt = db.scalar(select(Attempt).where(
        Attempt.exam_id == exam_id, Attempt.user_id == user.id,
        Attempt.status == "content_hold",
    ))
    if held_attempt:
        raise HTTPException(status_code=409, detail="This attempt is temporarily paused while a reported content issue is reviewed; your saved responses are preserved")
    if not exam or not exam.published:
        raise HTTPException(status_code=404, detail="Published exam not found")
    if exam.organization_id is not None and exam.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    existing = db.scalar(select(Attempt).where(
        Attempt.exam_id == exam.id, Attempt.user_id == user.id,
        Attempt.status == AttemptStatus.IN_PROGRESS.value,
    ))
    if existing:
        if existing.deadline_at and datetime.now(timezone.utc) > _aware(existing.deadline_at):
            _finalize_graded(db, existing, submission_kind="deadline_expired")
            raise HTTPException(status_code=409, detail="The prior attempt reached its deadline and was submitted automatically; reopen the exam to begin a permitted new attempt")
        lease_fresh = bool(
            existing.client_lease_at
            and datetime.now(timezone.utc) - _aware(existing.client_lease_at) < timedelta(seconds=90)
        )
        if (x_exam_client_session and existing.active_client_session_id
                and existing.active_client_session_id != x_exam_client_session and lease_fresh):
            raise HTTPException(status_code=409, detail="This exam is already active in another browser tab or device; close it or wait 90 seconds before recovering here")
        if x_exam_client_session:
            existing.active_client_session_id = x_exam_client_session
            existing.client_lease_at = datetime.now(timezone.utc)
            db.commit()
        attempt = existing
    else:
        now = datetime.now(timezone.utc)
        accommodation = _effective_accommodation(db, user, now)
        time_multiplier = accommodation.time_multiplier if accommodation else 1.0
        attempt = Attempt(
            exam_id=exam.id, user_id=user.id, started_at=now,
            deadline_at=now + timedelta(minutes=exam.duration_minutes * time_multiplier),
            time_multiplier=time_multiplier,
            active_client_session_id=x_exam_client_session,
            client_lease_at=now if x_exam_client_session else None,
        )
        db.add(attempt)
        db.flush()
        _audit(db, user, "attempt.start", "attempt", attempt.id, exam_id=exam.id,
               time_multiplier=time_multiplier)
        db.commit()
        db.refresh(attempt)
    items = db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id).order_by(ExamItem.position)).all()
    responses = db.scalars(select(Response).where(Response.attempt_id == attempt.id)).all()
    response_by_question = {response.question_id: response for response in responses}
    return {
        "attempt_id": attempt.id, "title": exam.title,
        "release_class": exam.release_class,
        "feedback_mode": (exam.blueprint or {}).get("feedback_mode", "after_submit"),
        "release_label": RELEASE_LABELS.get(exam.release_class, "Reviewed Practice"),
        "duration_minutes": math.ceil(exam.duration_minutes * attempt.time_multiplier),
        "base_duration_minutes": exam.duration_minutes,
        "time_multiplier": attempt.time_multiplier,
        "accommodation_applied": attempt.time_multiplier > 1.0,
        "started_at": _iso_utc(attempt.started_at), "deadline_at": _iso_utc(attempt.deadline_at),
        "questions": [{
            "id": item.question_id, "stem": item.snapshot["stem"],
            "choices": item.snapshot.get("choices", []),
            "assets": item.snapshot.get("assets", []),
            "figure_missing": bool(item.snapshot.get("figure_missing")),
            "question_type": item.snapshot["question_type"],
            "estimated_seconds": item.snapshot.get("estimated_seconds", 90),
            "version": item.question_version,
            "saved_answer": response_by_question[item.question_id].answer if item.question_id in response_by_question else None,
            "saved_confidence": response_by_question[item.question_id].confidence if item.question_id in response_by_question else None,
            "saved_sequence_number": response_by_question[item.question_id].sequence_number if item.question_id in response_by_question else 0,
            "saved_time_spent_seconds": response_by_question[item.question_id].time_spent_seconds if item.question_id in response_by_question else 0,
        } for item in items],
        "restored_response_count": len(responses),
    }


def _ensure_editable(db: Session, attempt: Attempt) -> None:
    if attempt.status == "content_hold":
        raise HTTPException(status_code=409, detail="This attempt is paused for content review; your prior responses remain saved")
    if attempt.status != AttemptStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=409, detail="Attempt is not editable")
    if attempt.deadline_at and datetime.now(timezone.utc) > _aware(attempt.deadline_at):
        _finalize_graded(db, attempt)
        raise HTTPException(status_code=409, detail="Exam time expired; attempt was automatically submitted")


@router.put("/attempts/{attempt_id}/responses")
def save_response(attempt_id: int, payload: ResponseSaveRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    _ensure_editable(db, attempt)
    item = db.scalar(select(ExamItem).where(ExamItem.exam_id == attempt.exam_id, ExamItem.question_id == payload.question_id))
    if not item:
        raise HTTPException(status_code=400, detail="Question not in exam")
    serialized_answer = json.dumps(payload.answer, sort_keys=True, separators=(",", ":"))
    if len(serialized_answer.encode()) > 10_000:
        raise HTTPException(status_code=422, detail="Answer payload is too large")
    allowed_metadata = {"offline_replay", "client_session_id", "connection", "user_agent_family"}
    if set(payload.client_metadata) - allowed_metadata:
        raise HTTPException(status_code=422, detail="Unsupported client metadata")
    client_metadata = {
        key: (str(value)[:160] if not isinstance(value, bool) else value)
        for key, value in payload.client_metadata.items()
    }
    client_session_id = client_metadata.get("client_session_id")
    if (attempt.active_client_session_id and client_session_id != attempt.active_client_session_id):
        raise HTTPException(status_code=409, detail="This save came from a browser tab that no longer owns the active exam session")
    if client_session_id:
        attempt.client_lease_at = datetime.now(timezone.utc)
    duplicate_revision = db.scalar(select(ResponseRevision).where(
        ResponseRevision.idempotency_key == payload.idempotency_key,
        ResponseRevision.attempt_id == attempt.id,
        ResponseRevision.question_id == payload.question_id,
    ))
    if duplicate_revision:
        response = db.get(Response, duplicate_revision.response_id)
        return {
            "saved": True, "duplicate": True,
            "sequence_number": duplicate_revision.sequence_number,
            "revision_id": duplicate_revision.id, "updated_at": response.updated_at,
        }
    response = db.scalar(select(Response).where(
        Response.attempt_id == attempt.id, Response.question_id == payload.question_id
    ))
    if response and payload.sequence_number <= response.sequence_number:
        raise HTTPException(status_code=409, detail="Stale response update")
    if not response:
        response = Response(attempt_id=attempt.id, question_id=payload.question_id)
        db.add(response)
        db.flush()
    previous = db.scalar(select(ResponseRevision).where(
        ResponseRevision.response_id == response.id
    ).order_by(ResponseRevision.sequence_number.desc(), ResponseRevision.id.desc()))
    response.answer = payload.answer
    response.confidence = payload.confidence
    response.time_spent_seconds = payload.time_spent_seconds
    response.sequence_number = payload.sequence_number
    response.idempotency_key = payload.idempotency_key
    db.add(response)
    revision_state = {
        "answer": payload.answer, "confidence": payload.confidence,
        "time_spent_seconds": payload.time_spent_seconds,
        "sequence_number": payload.sequence_number,
    }
    revision_hash = hashlib.sha256(json.dumps(
        revision_state, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    revision = ResponseRevision(
        response_id=response.id, attempt_id=attempt.id, question_id=payload.question_id,
        previous_revision_id=previous.id if previous else None,
        answer=payload.answer, confidence=payload.confidence,
        time_spent_seconds=payload.time_spent_seconds,
        sequence_number=payload.sequence_number,
        idempotency_key=payload.idempotency_key, content_hash=revision_hash,
        client_metadata=client_metadata,
    )
    db.add(revision)
    db.flush()
    _audit(db, user, "response.revision_accept", "response_revision", revision.id,
           attempt_id=attempt.id, question_id=payload.question_id,
           sequence_number=payload.sequence_number, offline_replay=bool(client_metadata.get("offline_replay")))
    db.commit()
    db.refresh(response)
    return {"saved": True, "duplicate": False, "sequence_number": response.sequence_number,
            "revision_id": revision.id, "content_hash": revision.content_hash, "updated_at": response.updated_at}


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(
    attempt_id: int, x_exam_client_session: str | None = Header(default=None),
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if (attempt.active_client_session_id and
            x_exam_client_session != attempt.active_client_session_id):
        raise HTTPException(status_code=409, detail="Only the browser session that owns this exam may submit it")
    if attempt.status == AttemptStatus.IN_PROGRESS.value:
        attempt = _finalize_graded(db, attempt, submission_kind="manual")
        _audit(db, user, "attempt.submit", "attempt", attempt.id, score=attempt.score, max_score=attempt.max_score)
        db.commit()
    return {"id": attempt.id, "status": attempt.status, "score": attempt.score, "max_score": attempt.max_score}


@router.get("/attempts/{attempt_id}/review")
def review_attempt(attempt_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    cases = db.scalars(select(RemediationCase).where(RemediationCase.attempt_id == attempt.id)).all()
    items = db.scalars(select(ExamItem).where(
        ExamItem.exam_id == attempt.exam_id
    ).order_by(ExamItem.position)).all()
    challenges = db.scalars(select(ContentChallenge).where(
        ContentChallenge.user_id == user.id, ContentChallenge.attempt_id == attempt.id,
    )).all()
    challenge_by_question = {challenge.question_id: challenge for challenge in challenges}
    return {
        "attempt": {"id": attempt.id, "score": attempt.score, "max_score": attempt.max_score, "status": attempt.status},
        "remediation_cases": [{
            "id": c.id, "question_id": c.question_id, "error_type": c.error_type,
            "status": c.status, "diagnosis": c.diagnosis, "plan": c.plan,
            "student_reflection": c.student_reflection,
        } for c in cases],
        "challengeable_items": [{
            "question_id": item.question_id,
            "question_version": item.question_version,
            "position": item.position + 1,
            "stem": item.snapshot["stem"],
            "challenge": ({
                "id": challenge_by_question[item.question_id].id,
                "status": challenge_by_question[item.question_id].status,
                "category": challenge_by_question[item.question_id].category,
                "public_note": (challenge_by_question[item.question_id].resolution or {}).get("public_note", ""),
            } if item.question_id in challenge_by_question else None),
        } for item in items],
    }


def _reference_answer(snapshot: dict) -> str:
    spec = snapshot.get("answer_spec", {}) or {}
    if snapshot.get("question_type") == "single_choice":
        idx = spec.get("correct_index")
        choices = snapshot.get("choices", []) or []
        return str(choices[idx]) if isinstance(idx, int) and 0 <= idx < len(choices) else ""
    answer = str(spec.get("answer", "")).strip()
    accepted = [str(a) for a in (spec.get("accepted") or []) if str(a).strip() and str(a).strip() != answer]
    if accepted:
        answer = f"{answer} (also accepted: {', '.join(accepted)})" if answer else ", ".join(accepted)
    rubric = str(spec.get("rubric", "")).strip()
    return f"{answer} — {rubric}" if rubric else answer


@router.post("/attempts/{attempt_id}/questions/{question_id}/check")
def check_response(
    attempt_id: int, question_id: int,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    """Per-question immediate feedback (mode 2). Grades the currently saved answer
    and reveals the reference answer. Only allowed on per_question exams."""
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    exam = db.get(Exam, attempt.exam_id)
    if (exam.blueprint or {}).get("feedback_mode") != "per_question":
        raise HTTPException(status_code=409, detail="This exam does not provide per-question feedback")
    item = db.scalar(select(ExamItem).where(
        ExamItem.exam_id == attempt.exam_id, ExamItem.question_id == question_id,
    ))
    if not item:
        raise HTTPException(status_code=404, detail="Question not part of this exam")
    response = db.scalar(select(Response).where(
        Response.attempt_id == attempt.id, Response.question_id == question_id,
    ))
    if not response:
        raise HTTPException(status_code=409, detail="Answer this question before checking it")
    question = _question_from_snapshot(item)
    correct, points, diagnostic = grade_single(item.snapshot, response.answer or {})
    return {
        "question_id": question_id,
        "correct": correct,
        "points_awarded": points,
        "max_points": float(question.answer_spec.get("points", 1)),
        "your_answer": response.answer,
        "reference_answer": _reference_answer(item.snapshot),
        "explanation": item.snapshot.get("explanation", ""),
        "diagnostic": diagnostic,
    }


@router.get("/attempts/{attempt_id}/answers")
def attempt_answers(attempt_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """End-of-exam answer key (mode 1): per-question correctness + reference answers,
    available only once the attempt has been submitted/scored."""
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.status not in {AttemptStatus.SUBMITTED.value, AttemptStatus.SCORED.value,
                              "remediation_open", "remediation_complete"}:
        raise HTTPException(status_code=409, detail="Answers are revealed after you submit the exam")
    exam = db.get(Exam, attempt.exam_id)
    if exam and exam.release_class == "competition_ready":
        raise HTTPException(status_code=403, detail="The answer key is not released for competition-ready exams")
    items = db.scalars(select(ExamItem).where(
        ExamItem.exam_id == attempt.exam_id
    ).order_by(ExamItem.position)).all()
    responses = {r.question_id: r for r in db.scalars(select(Response).where(
        Response.attempt_id == attempt.id
    )).all()}
    questions = []
    for item in items:
        question = _question_from_snapshot(item)
        response = responses.get(item.question_id)
        if response and response.is_correct is None:
            # Intentionally excluded by finalize (ungradeable / figure-missing):
            # show it as "not scored", never re-score it into a wrong answer.
            correct, points, scored = None, 0.0, False
        elif response:
            correct, points, scored = response.is_correct, response.points_awarded, True
        else:
            correct, points, _ = score_response(question, {})
            scored = True
        # Surface the specific misconception behind the student's wrong choice.
        selected = (response.answer or {}).get("selected_index") if response else None
        misconception = None
        if correct is False and isinstance(selected, int):
            misconception = ((item.snapshot.get("answer_spec") or {}).get(
                "misconception_by_choice") or {}).get(str(selected))
        questions.append({
            "misconception": misconception,
            "question_id": item.question_id,
            "position": item.position + 1,
            "stem": item.snapshot["stem"],
            "question_type": item.snapshot["question_type"],
            "your_answer": response.answer if response else None,
            "correct": correct,
            "scored": scored,
            "points_awarded": points,
            "max_points": float(question.answer_spec.get("points", 1)) if scored else 0.0,
            "reference_answer": _reference_answer(item.snapshot),
            "explanation": item.snapshot.get("explanation", ""),
            "grader": (response.diagnostic or {}).get("grader", "deterministic") if response else "deterministic",
            "rationale": (response.diagnostic or {}).get("rationale", "") if response else "",
        })
    return {
        "attempt_id": attempt.id,
        "feedback_mode": (exam.blueprint or {}).get("feedback_mode", "after_submit"),
        "score": attempt.score,
        "max_score": attempt.max_score,
        "questions": questions,
    }


@router.post("/attempts/{attempt_id}/challenges")
def submit_content_challenge(
    attempt_id: int, payload: ContentChallengeCreateRequest,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.user_id != user.id or not attempt.submitted_at:
        raise HTTPException(status_code=404, detail="Completed attempt not found")
    item = db.scalar(select(ExamItem).where(
        ExamItem.exam_id == attempt.exam_id, ExamItem.question_id == payload.question_id,
    ))
    if not item:
        raise HTTPException(status_code=400, detail="Question does not belong to this attempt")
    existing = db.scalar(select(ContentChallenge).where(
        ContentChallenge.user_id == user.id, ContentChallenge.attempt_id == attempt.id,
        ContentChallenge.question_id == item.question_id,
    ))
    if existing:
        raise HTTPException(status_code=409, detail="You already reported this question; track its status in your exam review")
    challenge = ContentChallenge(
        user_id=user.id, attempt_id=attempt.id, exam_id=attempt.exam_id,
        question_id=item.question_id, question_version=item.question_version,
        category=payload.category, description=payload.description,
    )
    db.add(challenge)
    db.flush()
    db.add(ContentChallengeEvent(
        challenge_id=challenge.id, actor_user_id=user.id, event_type="submitted",
        from_status=None, to_status="submitted", details={"category": challenge.category},
    ))
    _audit(db, user, "content_challenge.submit", "content_challenge", challenge.id,
           attempt_id=attempt.id, question_id=item.question_id, question_version=item.question_version)
    db.commit()
    return {"id": challenge.id, "status": challenge.status, "question_id": challenge.question_id}


@router.get("/me/challenges")
def my_content_challenges(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(ContentChallenge).where(
        ContentChallenge.user_id == user.id
    ).order_by(ContentChallenge.created_at.desc())).all()
    return [{
        "id": row.id, "attempt_id": row.attempt_id, "question_id": row.question_id,
        "category": row.category, "status": row.status, "severity": row.severity,
        "public_note": (row.resolution or {}).get("public_note", ""),
        "created_at": _iso_utc(row.created_at), "resolved_at": _iso_utc(row.resolved_at),
    } for row in rows]


@router.get("/notifications")
def list_notifications(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(UserNotification).where(
        UserNotification.user_id == user.id
    ).order_by(UserNotification.created_at.desc(), UserNotification.id.desc()).limit(50)).all()
    unread = db.scalar(select(func.count(UserNotification.id)).where(
        UserNotification.user_id == user.id, UserNotification.read_at.is_(None),
    )) or 0
    return {
        "unread_count": int(unread),
        "notifications": [{
            "id": row.id, "type": row.notification_type, "title": row.title,
            "body": row.body, "action_url": row.action_url,
            "read": row.read_at is not None, "created_at": _iso_utc(row.created_at),
            "metadata": row.metadata_json,
        } for row in rows],
    }


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    notification = db.get(UserNotification, notification_id)
    if not notification or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not notification.read_at:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
    return {"id": notification.id, "read": True}


@router.post("/notifications/read-all")
def read_all_notifications(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(UserNotification).where(
        UserNotification.user_id == user.id, UserNotification.read_at.is_(None),
    )).all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.read_at = now
    db.commit()
    return {"read": len(rows)}


@router.get("/content/challenges")
def list_content_challenges(db: Session = Depends(get_db), actor: User = Depends(require_content_staff)):
    rows = db.scalars(select(ContentChallenge).order_by(
        ContentChallenge.resolved_at.is_not(None), ContentChallenge.created_at
    ).limit(50)).all()
    result = []
    for row in rows:
        item = db.scalar(select(ExamItem).where(
            ExamItem.exam_id == row.exam_id, ExamItem.question_id == row.question_id,
            ExamItem.question_version == row.question_version,
        ))
        duplicate_count = db.scalar(select(func.count(ContentChallenge.id)).where(
            ContentChallenge.question_id == row.question_id,
            ContentChallenge.question_version == row.question_version,
        )) or 0
        result.append({
            "id": row.id, "question_id": row.question_id, "question_version": row.question_version,
            "attempt_id": row.attempt_id, "exam_id": row.exam_id, "category": row.category,
            "description": row.description, "status": row.status, "severity": row.severity,
            "stem": item.snapshot["stem"] if item else "Question snapshot unavailable",
            "choices": item.snapshot.get("choices", []) if item else [],
            "original_answer_spec": item.snapshot.get("answer_spec", {}) if item else {},
            "report_count_for_version": int(duplicate_count),
            "resolution": row.resolution, "created_at": _iso_utc(row.created_at),
        })
    return result


@router.post("/content/challenges/{challenge_id}/triage")
def triage_content_challenge(
    challenge_id: int, payload: ContentChallengeTriageRequest,
    db: Session = Depends(get_db), actor: User = Depends(require_content_staff),
):
    if actor.role not in {"editor", "sme", "admin"}:
        raise HTTPException(status_code=403, detail="Editor, SME, or administrator role required")
    challenge = db.get(ContentChallenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if challenge.status != "submitted":
        raise HTTPException(status_code=409, detail="Only submitted challenges can be triaged")
    question = db.get(Question, challenge.question_id)
    items = db.scalars(select(ExamItem).where(
        ExamItem.question_id == challenge.question_id,
        ExamItem.question_version == challenge.question_version,
    )).all()
    exams = [db.get(Exam, exam_id) for exam_id in {item.exam_id for item in items}]
    hold = {
        "question_status_before_hold": question.status if question else None,
        "exam_publication_before_hold": {str(exam.id): exam.published for exam in exams if exam},
        "attempt_status_before_hold": {},
    }
    active_attempts = []
    if payload.severity in {"high", "critical"}:
        if question:
            question.status = "quarantined"
        for exam in exams:
            if exam:
                exam.published = False
        active_attempts = db.scalars(select(Attempt).where(
            Attempt.exam_id.in_([exam.id for exam in exams if exam]),
            Attempt.status == AttemptStatus.IN_PROGRESS.value,
        )).all() if exams else []
        for attempt in active_attempts:
            hold["attempt_status_before_hold"][str(attempt.id)] = attempt.status
            attempt.status = "content_hold"
    create_notification(
        db, user_id=challenge.user_id, notification_type="challenge_triaged",
        title="Your content report is under review",
        body=f"Content staff classified your report as {payload.severity} severity. You will receive the final decision here.",
        action_url="/#errors", dedupe_key=f"challenge:{challenge.id}:triaged:{challenge.user_id}",
        metadata={"challenge_id": challenge.id, "status": "triaged"},
    )
    for attempt in active_attempts:
        create_notification(
            db, user_id=attempt.user_id, notification_type="exam_content_hold",
            title="Your exam is temporarily paused",
            body="A potential content problem is under review. Your saved responses are preserved and no further action is needed yet.",
            action_url="/#overview", dedupe_key=f"challenge:{challenge.id}:hold:{attempt.user_id}",
            metadata={"challenge_id": challenge.id, "attempt_id": attempt.id},
        )
    challenge.status = "triaged"
    challenge.severity = payload.severity
    challenge.triaged_by_user_id = actor.id
    challenge.resolution = {"triage_note": payload.notes, "hold": hold}
    db.add(ContentChallengeEvent(
        challenge_id=challenge.id, actor_user_id=actor.id, event_type="triaged",
        from_status="submitted", to_status="triaged",
        details={"severity": payload.severity, "notes": payload.notes, "hold": hold},
    ))
    _audit(db, actor, "content_challenge.triage", "content_challenge", challenge.id,
           severity=payload.severity, exams_paused=sum(1 for exam in exams if exam and not exam.published))
    db.commit()
    return {"id": challenge.id, "status": challenge.status, "severity": challenge.severity}


@router.post("/content/challenges/{challenge_id}/resolve")
def resolve_content_challenge(
    challenge_id: int, payload: ContentChallengeResolveRequest,
    db: Session = Depends(get_db), actor: User = Depends(require_admin),
):
    challenge = db.get(ContentChallenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if challenge.status != "triaged":
        raise HTTPException(status_code=409, detail="Challenge must be triaged before resolution")
    if challenge.triaged_by_user_id == actor.id:
        raise HTTPException(status_code=409, detail="A different administrator must resolve the triaged challenge")
    question = db.get(Question, challenge.question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if payload.correction_type == "correct_key":
        correct_index = (payload.corrected_answer_spec or {}).get("correct_index")
        if not isinstance(correct_index, int) or not 0 <= correct_index < len(question.choices or []):
            raise HTTPException(status_code=422, detail="Corrected answer specification requires a valid correct_index")
    impact = {"affected_attempts": 0, "changed_scores": 0, "voided_remediation_cases": 0, "opened_remediation_cases": 0, "affected_user_ids": []}
    if payload.decision == "upheld" and payload.correction_type in {"exclude_item", "correct_key"}:
        impact = apply_score_correction(
            db, challenge_id=challenge.id, question=question,
            question_version=challenge.question_version,
            correction_type=payload.correction_type,
            corrected_answer_spec=payload.corrected_answer_spec,
            reason=payload.public_note, actor_user_id=actor.id,
        )
    hold = (challenge.resolution or {}).get("hold", {})
    if payload.decision == "upheld":
        question.status = "withdrawn"
        affected_items = db.scalars(select(ExamItem).where(
            ExamItem.question_id == challenge.question_id,
            ExamItem.question_version == challenge.question_version,
        )).all()
        for exam_id in {item.exam_id for item in affected_items}:
            exam = db.get(Exam, exam_id)
            if exam:
                exam.published = False
        for attempt_id in hold.get("attempt_status_before_hold", {}):
            attempt = db.get(Attempt, int(attempt_id))
            if attempt and attempt.status == "content_hold":
                attempt.status = "cancelled_content_correction"
    else:
        other_hold = db.scalar(select(ContentChallenge.id).where(
            ContentChallenge.id != challenge.id,
            ContentChallenge.question_id == challenge.question_id,
            ContentChallenge.question_version == challenge.question_version,
            ContentChallenge.status == "triaged",
            ContentChallenge.severity.in_(["high", "critical"]),
        ))
        if not other_hold and hold.get("question_status_before_hold"):
            question.status = hold["question_status_before_hold"]
            for exam_id, was_published in hold.get("exam_publication_before_hold", {}).items():
                exam = db.get(Exam, int(exam_id))
                if exam:
                    exam.published = bool(was_published)
            for attempt_id, prior_status in hold.get("attempt_status_before_hold", {}).items():
                attempt = db.get(Attempt, int(attempt_id))
                if attempt and attempt.status == "content_hold":
                    attempt.status = prior_status
    previous = challenge.status
    challenge.status = payload.decision
    challenge.resolved_by_user_id = actor.id
    challenge.resolved_at = datetime.now(timezone.utc)
    challenge.resolution = {
        **(challenge.resolution or {}), "decision": payload.decision,
        "correction_type": payload.correction_type,
        "corrected_answer_spec": payload.corrected_answer_spec,
        "public_note": payload.public_note, "internal_note": payload.internal_note,
        "impact": impact,
    }
    reporter_title = "Your content report was upheld" if payload.decision == "upheld" else "Your content report review is complete"
    create_notification(
        db, user_id=challenge.user_id, notification_type="challenge_resolved",
        title=reporter_title, body=payload.public_note, action_url="/#errors",
        dedupe_key=f"challenge:{challenge.id}:resolved:{challenge.user_id}",
        metadata={"challenge_id": challenge.id, "decision": payload.decision},
    )
    for user_id in impact.get("affected_user_ids", []):
        create_notification(
            db, user_id=user_id, notification_type="score_correction",
            title="A completed exam was corrected", body=payload.public_note,
            action_url="/#errors", dedupe_key=f"challenge:{challenge.id}:score:{user_id}",
            metadata={"challenge_id": challenge.id, "question_id": challenge.question_id},
        )
    for attempt_id in hold.get("attempt_status_before_hold", {}):
        held_attempt = db.get(Attempt, int(attempt_id))
        if held_attempt:
            create_notification(
                db, user_id=held_attempt.user_id,
                notification_type="exam_cancelled" if payload.decision == "upheld" else "exam_resumed",
                title="Your paused exam was cancelled" if payload.decision == "upheld" else "Your paused exam is ready to resume",
                body=("The item issue was upheld, so this attempt will not be scored. Your saved work remains in the audit record."
                      if payload.decision == "upheld" else "The content review confirmed the form. Resume from your saved responses when you are ready."),
                action_url="/#practice" if payload.decision == "not_upheld" else "/#overview",
                dedupe_key=f"challenge:{challenge.id}:attempt-resolution:{held_attempt.user_id}",
                metadata={"challenge_id": challenge.id, "attempt_id": held_attempt.id},
            )
    db.add(ContentChallengeEvent(
        challenge_id=challenge.id, actor_user_id=actor.id, event_type="resolved",
        from_status=previous, to_status=challenge.status,
        details={"decision": payload.decision, "correction_type": payload.correction_type, "impact": impact},
    ))
    _audit(db, actor, "content_challenge.resolve", "content_challenge", challenge.id,
           decision=payload.decision, correction_type=payload.correction_type, **impact)
    db.commit()
    return {"id": challenge.id, "status": challenge.status, "impact": impact}


@router.put("/remediation/{case_id}/reflection")
def save_reflection(case_id: int, payload: ReflectionRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    case = db.get(RemediationCase, case_id)
    if not case or case.user_id != user.id:
        raise HTTPException(status_code=404, detail="Remediation case not found")
    case.student_reflection = payload.reflection
    case.status = "guided_practice"
    _audit(db, user, "remediation.reflect", "remediation_case", case.id)
    db.commit()
    return {"id": case.id, "status": case.status}


@router.post("/remediation/{case_id}/resolve")
def resolve_case_compat(case_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    case = db.get(RemediationCase, case_id)
    if not case or case.user_id != user.id:
        raise HTTPException(status_code=404, detail="Remediation case not found")
    if len(case.student_reflection.strip()) < 10:
        raise HTTPException(status_code=400, detail="Complete a meaningful reflection before continuing")
    case.status = "delayed_review"
    case.plan = {**case.plan, "resolution_note": "Reflection complete; unseen transfer item remains required."}
    db.commit()
    return {"id": case.id, "status": case.status, "next_step": "unseen_transfer_item"}


@router.post("/remediation/{case_id}/transfer")
def create_transfer(case_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    case = db.get(RemediationCase, case_id)
    if not case or case.user_id != user.id:
        raise HTTPException(status_code=404, detail="Remediation case not found")
    if len(case.student_reflection.strip()) < 10:
        raise HTTPException(status_code=400, detail="Complete a meaningful reflection before transfer practice")
    try:
        transfer = build_transfer_question(db, case)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    payload = transfer.question_payload
    return {
        "transfer_id": transfer.id, "status": case.status,
        "question": {"stem": payload["stem"], "choices": payload.get("choices", []), "question_type": payload["question_type"]},
    }


@router.post("/remediation/transfer/{transfer_id}/submit")
def submit_transfer(transfer_id: int, payload: TransferAnswerRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    transfer = db.get(TransferAttempt, transfer_id)
    if not transfer or transfer.user_id != user.id:
        raise HTTPException(status_code=404, detail="Transfer attempt not found")
    if transfer.completed_at is not None:
        raise HTTPException(status_code=409, detail="Transfer attempt already completed")
    transfer = grade_transfer(db, transfer, payload.answer)
    case = db.get(RemediationCase, transfer.remediation_case_id)
    _audit(db, user, "remediation.transfer_submit", "transfer_attempt", transfer.id, correct=transfer.is_correct)
    db.commit()
    return {
        "transfer_id": transfer.id, "correct": transfer.is_correct,
        "diagnostic": transfer.diagnostic, "remediation_status": case.status if case else "unknown",
        "next_step": "delayed_review" if transfer.is_correct else "guided_practice",
    }




@router.get("/remediation/due")
def due_remediation(db: Session = Depends(get_db), user: User = Depends(current_user)):
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(RemediationCase).where(RemediationCase.user_id == user.id, RemediationCase.status == "delayed_review")).all()
    due = []
    for row in rows:
        due_text = (row.plan or {}).get("next_review_at")
        if due_text and datetime.fromisoformat(due_text).replace(tzinfo=datetime.fromisoformat(due_text).tzinfo or timezone.utc) <= now:
            due.append({"id": row.id, "question_id": row.question_id, "error_type": row.error_type, "next_review_at": due_text})
    return due


@router.post("/remediation/{case_id}/delayed-review")
def create_delayed_review(case_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    case = db.get(RemediationCase, case_id)
    if not case or case.user_id != user.id:
        raise HTTPException(status_code=404, detail="Remediation case not found")
    try:
        transfer = build_delayed_review(db, case)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    payload = transfer.question_payload
    return {"transfer_id": transfer.id, "question": {"stem": payload["stem"], "choices": payload.get("choices", []), "question_type": payload["question_type"]}}


@router.post("/remediation/delayed-review/{transfer_id}/submit")
def submit_delayed_review(transfer_id: int, payload: TransferAnswerRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    transfer = db.get(TransferAttempt, transfer_id)
    if not transfer or transfer.user_id != user.id:
        raise HTTPException(status_code=404, detail="Delayed review not found")
    if transfer.completed_at is not None:
        raise HTTPException(status_code=409, detail="Delayed review already completed")
    try:
        transfer = grade_delayed_review(db, transfer, payload.answer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    case = db.get(RemediationCase, transfer.remediation_case_id)
    _audit(db, user, "remediation.delayed_submit", "transfer_attempt", transfer.id, correct=transfer.is_correct)
    db.commit()
    return {"transfer_id": transfer.id, "correct": transfer.is_correct, "remediation_status": case.status if case else "unknown"}


@router.get("/mastery")
def list_mastery(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(MasteryState).where(MasteryState.user_id == user.id)).all()
    return [{
        "concept_id": row.concept_id, "mastery_probability": row.mastery_probability,
        "evidence_count": row.evidence_count, "misconception_risk": row.misconception_risk,
        "last_practiced_at": row.last_practiced_at, "next_review_at": row.next_review_at,
    } for row in rows]


@router.post("/teams")
def create_team(payload: TeamCreateRequest, db: Session = Depends(get_db), actor: User = Depends(require_exam_manager)):
    if not actor.organization_id:
        raise HTTPException(status_code=400, detail="An organization is required to create a team")
    existing = db.scalar(select(Team).where(Team.organization_id == actor.organization_id, Team.name == payload.name))
    if existing:
        raise HTTPException(status_code=409, detail="Team already exists")
    team = Team(organization_id=actor.organization_id, name=payload.name, division=payload.division, season=payload.season, created_by_user_id=actor.id)
    db.add(team)
    db.flush()
    db.add(TeamMembership(team_id=team.id, user_id=actor.id, membership_role="coach"))
    _audit(db, actor, "team.create", "team", team.id)
    db.commit()
    return {"id": team.id, "name": team.name, "division": team.division, "season": team.season}


@router.post("/teams/{team_id}/members")
def add_team_member(team_id: int, payload: TeamMemberRequest, db: Session = Depends(get_db), actor: User = Depends(require_exam_manager)):
    team = db.get(Team, team_id)
    if not team or team.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Team not found")
    member = db.scalar(select(User).where(User.email == payload.user_email.lower()))
    if not member or member.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="User not found in your organization")
    existing = db.scalar(select(TeamMembership).where(TeamMembership.team_id == team.id, TeamMembership.user_id == member.id))
    if existing:
        return {"id": existing.id, "team_id": team.id, "user_id": member.id, "membership_role": existing.membership_role}
    row = TeamMembership(team_id=team.id, user_id=member.id, membership_role=payload.membership_role)
    db.add(row)
    _audit(db, actor, "team.member_add", "team", team.id, user_id=member.id)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "team_id": team.id, "user_id": member.id, "membership_role": row.membership_role}


@router.get("/teams")
def list_teams(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not user.organization_id:
        return []
    rows = db.scalars(select(Team).where(Team.organization_id == user.organization_id).order_by(Team.name)).all()
    return [{"id": row.id, "name": row.name, "division": row.division, "season": row.season} for row in rows]


# --- Platform administration (user & role management) ---------------------

def _admin_user_view(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role,
        "division": u.division, "is_active": u.is_active,
        "organization_id": u.organization_id, "created_at": _iso_utc(u.created_at),
    }


@router.get("/admin/users")
def admin_list_users(
    q: str | None = None,
    role: str | None = None,
    active: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    stmt = select(User)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.full_name.ilike(like)))
    if role:
        stmt = stmt.where(User.role == role)
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
    ).all()
    by_role = dict(db.execute(select(User.role, func.count()).group_by(User.role)).all())
    return {
        "total": total, "limit": limit, "offset": offset,
        "role_counts": by_role,
        "users": [_admin_user_view(u) for u in rows],
    }


@router.patch("/admin/users/{user_id}")
def admin_update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # An admin can't lock themselves out or strip their own admin rights — that
    # is the only path back into this console.
    if user.id == admin.id and payload.role is not None and payload.role != "admin":
        raise HTTPException(status_code=400, detail="You cannot change your own admin role")
    if user.id == admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    # Never remove the last remaining active admin. Lock the other active-admin
    # rows FOR UPDATE so two simultaneous demotions can't each see the other as
    # "still an admin" and both commit, leaving zero admins (TOCTOU).
    if user.role == "admin" and (payload.role not in (None, "admin") or payload.is_active is False):
        other_admins = db.scalars(select(User.id).where(
            User.role == "admin", User.is_active.is_(True), User.id != user.id
        ).with_for_update()).all()
        if not other_admins:
            raise HTTPException(status_code=400, detail="At least one active administrator must remain")
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    _audit(db, admin, "admin.user_update", "user", user.id,
           role=user.role, is_active=user.is_active)
    db.commit()
    db.refresh(user)
    return _admin_user_view(user)


@router.get("/me/attempts")
def my_attempts(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """A student's own past exam results, most recent first, so results stay
    revisitable and progress is visible over time."""
    rows = db.scalars(
        select(Attempt).where(
            Attempt.user_id == user.id, Attempt.submitted_at.isnot(None)
        ).order_by(Attempt.submitted_at.desc()).limit(limit)
    ).all()
    # Batch the exam/event lookups (avoid an N+1 across the page of attempts).
    exams = {e.id: e for e in db.scalars(
        select(Exam).where(Exam.id.in_({a.exam_id for a in rows})))} if rows else {}
    event_names = dict(db.execute(select(Event.id, Event.name).where(
        Event.id.in_({e.event_id for e in exams.values()}))).all()) if exams else {}
    out = []
    for a in rows:
        exam = exams.get(a.exam_id)
        out.append({
            "attempt_id": a.id,
            "exam_title": exam.title if exam else "Exam",
            "event": event_names.get(exam.event_id, "") if exam else "",
            "score": a.score, "max_score": a.max_score,
            "ratio": (a.score / a.max_score) if a.max_score else None,
            "submitted_at": _iso_utc(a.submitted_at), "status": a.status,
        })
    return {"attempts": out}


# --- Answer-key authoring (fix ungradeable short-answer questions) ---------

@router.get("/content/questions/needs-key")
def questions_needing_key(
    event_id: int | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    staff: User = Depends(require_content_staff),
):
    """Short-answer questions with no usable reference answer — the queue of
    items a student could never be graded on until an editor supplies a key."""
    # Gradeability is a JSON-shape check that can't be pushed to SQL portably, so
    # we still scan short-answer rows — but select only the 4 columns needed
    # instead of hydrating full Question ORM objects for the whole table.
    stmt = select(Question.id, Question.stem, Question.event_id, Question.answer_spec).where(
        Question.question_type == "short_answer")
    if event_id:
        stmt = stmt.where(Question.event_id == event_id)
    rows = db.execute(stmt.order_by(Question.event_id, Question.id)).all()
    ungradeable = [r for r in rows if not is_gradeable("short_answer", r.answer_spec or {})]
    events = dict(db.execute(select(Event.id, Event.name)).all())
    page = ungradeable[offset:offset + limit]
    return {
        "total": len(ungradeable), "limit": limit, "offset": offset,
        "questions": [{
            "id": r.id, "stem": r.stem, "event": events.get(r.event_id, ""),
            "event_id": r.event_id, "answer_spec": r.answer_spec or {},
        } for r in page],
    }


@router.patch("/content/questions/{question_id}/answer-key")
def set_answer_key(
    question_id: int,
    payload: AnswerKeyUpdate,
    db: Session = Depends(get_db),
    staff: User = Depends(require_content_staff),
):
    question = db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if question.question_type != "short_answer":
        raise HTTPException(status_code=422, detail="Answer keys apply to short-answer questions")
    spec = dict(question.answer_spec or {})
    spec["answer"] = payload.answer.strip()
    spec["accepted"] = [a.strip() for a in payload.accepted if a.strip()]
    if payload.rubric is not None:
        spec["rubric"] = payload.rubric.strip()
    spec.setdefault("points", 1.0)
    question.answer_spec = spec
    _audit(db, staff, "question.answer_key_set", "question", question.id)
    db.commit()
    return {"id": question.id, "answer_spec": spec,
            "gradeable": is_gradeable(question.question_type, spec)}
