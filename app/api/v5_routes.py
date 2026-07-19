from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.api.routes import _audit, _aware, current_user, require_admin, require_content_staff, require_exam_manager
from app.core.database import get_db
from app.models.entities import (
    AccommodationProfile, Assignment, Attempt, BackgroundJob, Concept, CrawlDomainPolicy,
    DiscoveredResource,
    Event, Exam, RemediationCase, RightsStatus, Source, SourceChange, Team,
    TeamMembership, User,
)
from app.schemas.api import (
    AssignmentCreateRequest, CrawlDomainPolicyRequest, DiscoverySeedRequest, JobCreateRequest,
    ModelQuestionGenerateRequest, PromoteDiscoveredResourceRequest, SitemapDiscoveryRequest,
    SourceChangeReviewRequest, SourceWithdrawalRequest,
)
from app.services.jobs import enqueue_job, run_next_job
from app.services.model_generation import generate_model_questions
from app.services.model_provider import ModelProviderError
from app.services.discovery import DiscoveryError, record_discovered_resource
from app.services.crawl_schedule import schedule_due_sources
from app.services.source_changes import quarantine_source_dependents
from app.services.rights import can_fetch_full_text
from app.services.source_coverage import event_source_coverage
from app.services.notifications import create_notification

router = APIRouter(prefix="/api")


@router.get("/content/source-coverage")
def source_coverage_scorecards(
    event_id: int | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_content_staff),
):
    query = select(Event).where(Event.active.is_(True))
    if event_id is not None:
        query = query.where(Event.id == event_id)
    events = db.scalars(query.order_by(Event.name)).all()
    if event_id is not None and not events:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"scorecards": [event_source_coverage(db, event) for event in events]}


@router.post("/discovery/domain-policies")
def upsert_domain_policy(
    payload: CrawlDomainPolicyRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    domain = payload.domain.strip().lower().rstrip(".")
    if "://" in domain or "/" in domain or " " in domain:
        raise HTTPException(status_code=422, detail="Enter a hostname without a scheme or path")
    if payload.default_rights_status not in {status.value for status in RightsStatus}:
        raise HTTPException(status_code=422, detail="Unknown default rights status")
    row = db.scalar(select(CrawlDomainPolicy).where(CrawlDomainPolicy.domain == domain))
    if not row:
        row = CrawlDomainPolicy(domain=domain)
    for key, value in payload.model_dump(exclude={"domain"}).items():
        setattr(row, key, value)
    row.reviewed_by_user_id = actor.id
    row.reviewed_at = datetime.now(timezone.utc)
    db.add(row)
    db.flush()
    _audit(db, actor, "discovery.domain_policy_upsert", "crawl_domain_policy", row.id,
           domain=domain, enabled=row.enabled)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id, "domain": row.domain, "enabled": row.enabled,
        "source_tier": row.source_tier,
        "default_rights_status": row.default_rights_status,
        "max_urls": row.max_urls, "crawl_delay_seconds": row.crawl_delay_seconds,
        "recrawl_minutes": row.recrawl_minutes,
    }


@router.get("/discovery/domain-policies")
def list_domain_policies(
    db: Session = Depends(get_db),
    actor: User = Depends(require_content_staff),
):
    rows = db.scalars(select(CrawlDomainPolicy).order_by(CrawlDomainPolicy.domain)).all()
    return [{
        "id": row.id, "domain": row.domain, "enabled": row.enabled,
        "source_tier": row.source_tier,
        "default_rights_status": row.default_rights_status,
        "max_urls": row.max_urls, "crawl_delay_seconds": row.crawl_delay_seconds,
        "recrawl_minutes": row.recrawl_minutes,
        "allow_paths": row.allow_paths, "deny_paths": row.deny_paths,
        "reviewed_at": row.reviewed_at,
    } for row in rows]


@router.post("/discovery/seeds")
def add_discovery_seeds(
    payload: DiscoverySeedRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_content_staff),
):
    rows = []
    errors = []
    for url in payload.urls:
        try:
            rows.append(record_discovered_resource(
                db, url, discovery_method=payload.discovery_method,
                source_tier=payload.source_tier,
            ))
        except (DiscoveryError, ValueError) as exc:
            errors.append({"url": url, "error": str(exc)})
    _audit(db, actor, "discovery.seeds_add", "discovered_resource", "batch",
           accepted=len(rows), rejected=len(errors))
    db.commit()
    return {
        "accepted": [{"id": row.id, "canonical_url": row.canonical_url} for row in rows],
        "rejected": errors,
    }


@router.get("/discovery/frontier")
def list_discovery_frontier(
    status: str | None = Query(default=None, max_length=32),
    domain: str | None = Query(default=None, max_length=253),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: User = Depends(require_content_staff),
):
    query = select(DiscoveredResource)
    if status:
        query = query.where(DiscoveredResource.status == status)
    if domain:
        query = query.where(DiscoveredResource.domain == domain.lower())
    rows = db.scalars(query.order_by(
        DiscoveredResource.source_tier.asc().nulls_last(),
        DiscoveredResource.last_discovered_at.desc(),
    ).limit(limit)).all()
    return [{
        "id": row.id, "canonical_url": row.canonical_url, "domain": row.domain,
        "referrer_url": row.referrer_url, "discovery_method": row.discovery_method,
        "source_tier": row.source_tier, "status": row.status,
        "discovery_count": row.discovery_count, "source_id": row.source_id,
        "last_discovered_at": row.last_discovered_at,
    } for row in rows]


@router.post("/discovery/sitemaps")
def enqueue_sitemap_discovery(
    payload: SitemapDiscoveryRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_content_staff),
):
    job = enqueue_job(db, "discover_sitemap", {"url": payload.url}, actor.id)
    return {"job_id": job.id, "status": job.status, "url": payload.url}


@router.post("/discovery/resources/{resource_id}/promote")
def promote_discovered_resource(
    resource_id: int,
    payload: PromoteDiscoveredResourceRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    resource = db.get(DiscoveredResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Discovered resource not found")
    if resource.source_id:
        source = db.get(Source, resource.source_id)
        return {"source_id": source.id, "status": resource.status, "already_promoted": True}
    policy = db.scalar(select(CrawlDomainPolicy).where(
        CrawlDomainPolicy.domain == resource.domain
    ))
    rights_status = payload.rights_status or (
        policy.default_rights_status if policy else RightsStatus.METADATA_ONLY.value
    )
    if rights_status not in {status.value for status in RightsStatus}:
        raise HTTPException(status_code=422, detail="Unknown rights status")
    source = db.scalar(select(Source).where(Source.url == resource.canonical_url))
    if not source:
        source = Source(
            url=resource.canonical_url,
            title=payload.title or resource.domain,
            publisher=payload.publisher,
            rights_status=rights_status,
            license_name=payload.license_name,
            approved=False,
        )
        db.add(source)
        db.flush()
    resource.source_id = source.id
    resource.status = "review_pending"
    _audit(db, actor, "discovery.resource_promote", "discovered_resource", resource.id,
           source_id=source.id, rights_status=rights_status)
    db.commit()
    return {"source_id": source.id, "status": resource.status, "already_promoted": False}


@router.get("/source-changes")
def list_source_changes(
    review_status: str | None = Query(default="pending", max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: User = Depends(require_content_staff),
):
    query = select(SourceChange)
    if review_status:
        query = query.where(SourceChange.review_status == review_status)
    rows = db.scalars(query.order_by(SourceChange.created_at.desc()).limit(limit)).all()
    return [{
        "id": row.id,
        "source_id": row.source_id,
        "previous_snapshot_id": row.previous_snapshot_id,
        "current_snapshot_id": row.current_snapshot_id,
        "change_kind": row.change_kind,
        "review_status": row.review_status,
        "summary": row.summary,
        "impact": row.impact,
        "created_at": row.created_at,
    } for row in rows]


@router.post("/source-changes/{change_id}/review")
def review_source_change(
    change_id: int,
    payload: SourceChangeReviewRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_content_staff),
):
    change = db.get(SourceChange, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Source change not found")
    if change.review_status != "pending":
        raise HTTPException(status_code=409, detail="Source change was already reviewed")
    change.review_status = payload.decision
    change.reviewed_by_user_id = actor.id
    change.reviewed_at = datetime.now(timezone.utc)
    change.summary = {**(change.summary or {}), "review_notes": payload.notes}
    source = db.get(Source, change.source_id)
    other_pending = db.scalar(select(func.count(SourceChange.id)).where(
        SourceChange.source_id == change.source_id,
        SourceChange.review_status == "pending",
        SourceChange.id != change.id,
    )) or 0
    if source and not other_pending:
        source.metadata_json = {
            **(source.metadata_json or {}),
            "impact_review_pending": False,
            "last_change_decision": payload.decision,
        }
    _audit(db, actor, "source_change.review", "source_change", change.id,
           decision=payload.decision, impact=change.impact)
    db.commit()
    return {
        "id": change.id,
        "review_status": change.review_status,
        "dependencies_remain_quarantined": bool(change.impact),
    }


@router.post("/discovery/schedule-due")
def schedule_due_crawls(
    db: Session = Depends(get_db),
    actor: User = Depends(require_content_staff),
):
    jobs = schedule_due_sources(db)
    _audit(db, actor, "discovery.schedule_due", "background_job", "batch", count=len(jobs))
    db.commit()
    return {
        "count": len(jobs),
        "job_ids": [job.id for job in jobs],
    }


@router.get("/discovery/coverage")
def discovery_coverage(
    db: Session = Depends(get_db),
    actor: User = Depends(require_content_staff),
):
    now = datetime.now(timezone.utc)
    policies = db.scalars(select(CrawlDomainPolicy)).all()
    resources = db.scalars(select(DiscoveredResource)).all()
    sources = db.scalars(select(Source)).all()
    changes = db.scalars(select(SourceChange)).all()
    jobs = db.scalars(select(BackgroundJob)).all()
    status_counts = {}
    for resource in resources:
        status_counts[resource.status] = status_counts.get(resource.status, 0) + 1
    source_health = {status: 0 for status in ("never", "queued", "healthy", "retrying", "failed", "withdrawn")}
    due_sources = 0
    for source in sources:
        source_health[source.crawl_status] = source_health.get(source.crawl_status, 0) + 1
        next_at = source.next_crawl_at
        if (
            source.approved
            and can_fetch_full_text(source.rights_status)
            and source.crawl_status not in {"queued", "withdrawn"}
            and (next_at is None or _parse_time(next_at.isoformat()) <= now)
        ):
            due_sources += 1
    tier_counts = {}
    for policy in policies:
        tier_counts[str(policy.source_tier)] = tier_counts.get(str(policy.source_tier), 0) + 1
    return {
        "generated_at": now,
        "domain_policies": {
            "total": len(policies),
            "enabled": sum(1 for policy in policies if policy.enabled),
            "by_tier": tier_counts,
        },
        "frontier": {"total": len(resources), "by_status": status_counts},
        "sources": {
            "total": len(sources),
            "approved": sum(1 for source in sources if source.approved),
            "due": due_sources,
            "by_health": source_health,
        },
        "change_review": {
            "pending": sum(1 for change in changes if change.review_status == "pending"),
            "total": len(changes),
        },
        "jobs": {
            "queued": sum(1 for job in jobs if job.status == "queued"),
            "running": sum(1 for job in jobs if job.status == "running"),
            "dead_letter": sum(1 for job in jobs if job.status == "dead_letter"),
        },
    }


@router.post("/sources/{source_id}/withdraw")
def withdraw_source(
    source_id: int,
    payload: SourceWithdrawalRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.crawl_status == "withdrawn":
        raise HTTPException(status_code=409, detail="Source is already withdrawn")
    impact = quarantine_source_dependents(db, source)
    source.approved = False
    source.rights_status = RightsStatus.QUARANTINED.value
    source.crawl_status = "withdrawn"
    source.next_crawl_at = None
    source.metadata_json = {
        **(source.metadata_json or {}),
        "withdrawn_at": datetime.now(timezone.utc).isoformat(),
        "withdrawal_reason": payload.reason,
        "impact_review_pending": False,
    }
    _audit(db, actor, "source.withdraw", "source", source.id,
           reason=payload.reason, impact=impact)
    db.commit()
    return {"id": source.id, "status": "withdrawn", "impact": impact}


def _parse_time(value: str | None):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid ISO-8601 datetime") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@router.post("/jobs")
def create_job(
    payload: JobCreateRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_content_staff),
):
    job = enqueue_job(db, payload.job_type, payload.payload, actor.id, _parse_time(payload.scheduled_at))
    return {"id": job.id, "job_type": job.job_type, "status": job.status, "scheduled_at": job.scheduled_at}


@router.get("/jobs/{job_id}")
def read_job(job_id: int, db: Session = Depends(get_db), actor: User = Depends(require_content_staff)):
    job = db.get(BackgroundJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id, "job_type": job.job_type, "status": job.status,
        "attempts": job.attempts, "result": job.result, "error": job.error,
        "scheduled_at": job.scheduled_at, "started_at": job.started_at, "completed_at": job.completed_at,
    }


@router.post("/jobs/run-next")
def run_job_now(db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    job = run_next_job(db)
    if not job:
        return {"ran": False}
    return {"ran": True, "id": job.id, "status": job.status, "result": job.result, "error": job.error}


@router.post("/questions/generate-model")
def generate_with_model(
    payload: ModelQuestionGenerateRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_content_staff),
):
    event = db.get(Event, payload.event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    concept = db.get(Concept, payload.concept_id) if payload.concept_id else None
    if concept and concept.event_id != event.id:
        raise HTTPException(status_code=400, detail="Concept does not belong to event")
    if payload.question_type != "single_choice":
        raise HTTPException(status_code=400, detail="Model pipeline currently supports single_choice")
    try:
        questions = generate_model_questions(
            db, actor, event, concept, payload.count, payload.difficulty, payload.cognitive_level
        )
    except (ModelProviderError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [{
        "id": q.id, "stem": q.stem, "choices": q.choices, "status": q.status,
        "validation_report": q.validation_report, "generation_provenance": q.generation_provenance,
    } for q in questions]


@router.post("/assignments")
def create_assignment(
    payload: AssignmentCreateRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_exam_manager),
):
    if not actor.organization_id:
        raise HTTPException(status_code=400, detail="Organization membership is required")
    team = db.get(Team, payload.team_id)
    exam = db.get(Exam, payload.exam_id)
    if not team or team.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Team not found")
    if not exam or (exam.organization_id not in {None, actor.organization_id}):
        raise HTTPException(status_code=404, detail="Exam not found")
    if not exam.published:
        raise HTTPException(status_code=409, detail="Publish the reviewed exam before assigning it to students")
    assignment = Assignment(
        organization_id=actor.organization_id,
        team_id=team.id,
        exam_id=exam.id,
        title=payload.title,
        instructions=payload.instructions,
        due_at=_parse_time(payload.due_at),
        created_by_user_id=actor.id,
    )
    db.add(assignment)
    db.flush()
    student_ids = db.scalars(select(TeamMembership.user_id).where(
        TeamMembership.team_id == team.id, TeamMembership.membership_role == "student",
    )).all()
    for student_id in student_ids:
        create_notification(
            db, user_id=student_id, notification_type="assignment_published",
            title=f"New assignment: {assignment.title}",
            body=f"Your coach assigned {exam.title}. Open Practice & Exams to begin before the due date.",
            action_url="/#practice", dedupe_key=f"assignment:{assignment.id}:student:{student_id}",
            metadata={"assignment_id": assignment.id, "exam_id": exam.id, "team_id": team.id},
        )
    db.commit()
    db.refresh(assignment)
    return {
        "id": assignment.id, "title": assignment.title, "team_id": team.id,
        "exam_id": exam.id, "due_at": assignment.due_at,
        "exam_release_class": exam.release_class,
    }


@router.get("/assignments")
def list_assignments(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.role in {"coach", "admin", "editor"}:
        if not user.organization_id:
            return []
        rows = db.scalars(select(Assignment).where(Assignment.organization_id == user.organization_id)).all()
    else:
        team_ids = db.scalars(select(TeamMembership.team_id).where(TeamMembership.user_id == user.id)).all()
        if not team_ids:
            return []
        rows = db.scalars(select(Assignment).where(Assignment.team_id.in_(team_ids))).all()
    return [{
        "id": row.id, "title": row.title, "instructions": row.instructions,
        "team_id": row.team_id, "exam_id": row.exam_id, "due_at": row.due_at,
        "exam_release_class": row.exam.release_class if row.exam else "reviewed_practice",
    } for row in rows]


@router.get("/coach/dashboard")
def coach_dashboard(db: Session = Depends(get_db), actor: User = Depends(require_exam_manager)):
    if not actor.organization_id:
        raise HTTPException(status_code=400, detail="Organization membership is required")
    teams = db.scalars(select(Team).where(Team.organization_id == actor.organization_id)).all()
    team_ids = [team.id for team in teams]
    memberships = db.scalars(select(TeamMembership).where(TeamMembership.team_id.in_(team_ids))).all() if team_ids else []
    student_ids = sorted({m.user_id for m in memberships if m.membership_role == "student"})
    assignments = db.scalars(select(Assignment).where(Assignment.organization_id == actor.organization_id)).all()
    exam_ids = [a.exam_id for a in assignments]
    attempts = db.scalars(select(Attempt).where(Attempt.user_id.in_(student_ids), Attempt.exam_id.in_(exam_ids))).all() if student_ids and exam_ids else []
    attempt_by_pair = {(a.user_id, a.exam_id): a for a in attempts}
    completion_total = len(student_ids) * len(assignments)
    completed = sum(1 for student_id in student_ids for a in assignments if (student_id, a.exam_id) in attempt_by_pair and attempt_by_pair[(student_id, a.exam_id)].status != "in_progress")
    avg_score = db.scalar(
        select(func.avg(Attempt.score / Attempt.max_score)).where(
            Attempt.user_id.in_(student_ids), Attempt.exam_id.in_(exam_ids), Attempt.max_score > 0
        )
    ) if student_ids and exam_ids else None
    open_remediation = db.scalar(
        select(func.count(RemediationCase.id)).where(
            RemediationCase.user_id.in_(student_ids),
            RemediationCase.status.not_in(["resolved"]),
        )
    ) if student_ids else 0
    users = db.scalars(select(User).where(User.id.in_(student_ids)).order_by(User.full_name)).all() if student_ids else []
    student_rows = []
    for student in users:
        accommodation = db.scalar(select(AccommodationProfile).where(
            AccommodationProfile.user_id == student.id,
            AccommodationProfile.active.is_(True),
        ))
        now = datetime.now(timezone.utc)
        accommodation_active = bool(
            accommodation
            and _aware(accommodation.effective_from) <= now
            and (not accommodation.effective_until or _aware(accommodation.effective_until) > now)
        )
        student_attempts = [attempt for attempt in attempts if attempt.user_id == student.id]
        scored_attempts = [attempt for attempt in student_attempts if attempt.max_score and attempt.score is not None]
        student_open_cases = db.scalar(
            select(func.count(RemediationCase.id)).where(
                RemediationCase.user_id == student.id,
                RemediationCase.status.not_in(["resolved"]),
            )
        ) or 0
        score_ratio = (
            sum(float(attempt.score) / float(attempt.max_score) for attempt in scored_attempts)
            / len(scored_attempts)
            if scored_attempts else None
        )
        student_rows.append({
            "id": student.id,
            "full_name": student.full_name,
            "division": student.division,
            "completed_assignments": sum(
                1 for assignment in assignments
                if (student.id, assignment.exam_id) in attempt_by_pair
                and attempt_by_pair[(student.id, assignment.exam_id)].status != "in_progress"
            ),
            "total_assignments": len(assignments),
            "average_score_ratio": round(score_ratio, 4) if score_ratio is not None else None,
            "open_remediation_cases": int(student_open_cases),
            "accommodation_active": accommodation_active,
            "time_multiplier": accommodation.time_multiplier if accommodation_active else 1.0,
            "attention": bool(student_open_cases) or (
                score_ratio is not None and score_ratio < 0.7
            ),
        })
    return {
        "teams": len(teams),
        "students": len(student_ids),
        "assignments": len(assignments),
        "completed_assignment_attempts": completed,
        "expected_assignment_attempts": completion_total,
        "completion_rate": round(completed / completion_total, 4) if completion_total else 0.0,
        "average_score_ratio": round(float(avg_score), 4) if avg_score is not None else None,
        "open_remediation_cases": int(open_remediation or 0),
        "student_rows": student_rows,
        "assignment_rows": [
            {
                "id": assignment.id,
                "title": assignment.title,
                "team_id": assignment.team_id,
                "exam_id": assignment.exam_id,
                "due_at": assignment.due_at,
            }
            for assignment in assignments
        ],
    }
