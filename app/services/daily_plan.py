from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Assignment, Attempt, Concept, Event, Exam, Lesson, LessonProgress, MasteryState,
    PracticeSession, PracticeSet, RemediationCase, TeamMembership, User,
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse_due(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return _aware(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return _aware(parsed)
    except ValueError:
        return None


def build_daily_plan(db: Session, user: User, event_slug: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    event = db.scalar(select(Event).where(
        Event.slug == event_slug, Event.active.is_(True)
    ).order_by(Event.season.desc())) if event_slug else None
    candidates: list[dict] = []

    open_cases = db.scalars(select(RemediationCase).where(
        RemediationCase.user_id == user.id,
        RemediationCase.status.not_in(["resolved", "void_content_correction"]),
    ).order_by(RemediationCase.created_at)).all()
    if open_cases:
        case = min(open_cases, key=lambda row: _parse_due((row.plan or {}).get("next_review_at")) or _aware(row.created_at))
        due = _parse_due((case.plan or {}).get("next_review_at"))
        overdue = bool(due and due <= now)
        candidates.append({
            "type": "remediation", "entity_id": case.id,
            "title": "Resolve an Error You Already Found",
            "summary": (case.plan or {}).get("explanation") or "Repair the reasoning, then prove the correction on an unseen problem.",
            "why": "This review is due now." if overdue else "Finishing an open error loop has the highest expected learning value.",
            "estimated_minutes": 10, "priority": 100 if overdue else 94,
            "urgency": "overdue" if overdue else "high", "action_label": "Continue Error Repair",
            "route": "/#errors", "event_slug": event.slug if event else None,
        })

    team_ids = db.scalars(select(TeamMembership.team_id).where(
        TeamMembership.user_id == user.id
    )).all()
    assignments = db.scalars(select(Assignment).where(
        Assignment.team_id.in_(team_ids)
    ).order_by(Assignment.due_at)).all() if team_ids else []
    pending_assignment_count = 0
    for assignment in assignments:
        attempted = db.scalar(select(Attempt.id).where(
            Attempt.user_id == user.id, Attempt.exam_id == assignment.exam_id,
            Attempt.submitted_at.is_not(None),
        ))
        if attempted:
            continue
        exam = db.get(Exam, assignment.exam_id)
        if not exam or not exam.published:
            continue
        pending_assignment_count += 1
        due = _parse_due(assignment.due_at)
        hours = (due - now).total_seconds() / 3600 if due else None
        priority = 98 if hours is not None and hours <= 24 else 88 if hours is not None and hours <= 72 else 74
        candidates.append({
            "type": "assignment", "entity_id": assignment.id, "exam_id": exam.id,
            "title": assignment.title, "summary": exam.title,
            "why": "Due within 24 hours." if hours is not None and hours <= 24 else "Your coach assigned this practice.",
            "estimated_minutes": exam.duration_minutes, "priority": priority,
            "urgency": "overdue" if hours is not None and hours < 0 else "high" if hours is not None and hours <= 24 else "normal",
            "due_at": due.isoformat() if due else None, "action_label": "Start Coach Assignment",
            "route": f"/#practice?event={exam.event.slug}", "event_slug": exam.event.slug,
        })

    mastery_query = select(MasteryState).where(
        MasteryState.user_id == user.id, MasteryState.next_review_at.is_not(None),
        MasteryState.next_review_at <= now,
    )
    mastery_rows = db.scalars(mastery_query.order_by(
        MasteryState.misconception_risk.desc(), MasteryState.next_review_at
    )).all()
    if event:
        event_concept_ids = set(db.scalars(select(Concept.id).where(Concept.event_id == event.id)).all())
        mastery_rows = [row for row in mastery_rows if row.concept_id in event_concept_ids]
    if mastery_rows:
        mastery = mastery_rows[0]
        concept = db.get(Concept, mastery.concept_id)
        practice = db.scalar(select(PracticeSet).where(
            PracticeSet.concept_id == mastery.concept_id, PracticeSet.status == "published",
        ).order_by(PracticeSet.id))
        candidates.append({
            "type": "spaced_review", "entity_id": mastery.id,
            "practice_set_id": practice.id if practice else None,
            "title": f"Retrieve: {concept.name if concept else 'Due Concept'}",
            "summary": "Use retrieval before the idea becomes harder to recall.",
            "why": "Your spaced-review date has arrived.", "estimated_minutes": practice.estimated_minutes if practice else 8,
            "priority": 90, "urgency": "due", "action_label": "Start Due Review",
            "route": f"/#lab={practice.id}&mode=study" if practice else f"/#practice?event={concept.event.slug if concept else ''}",
            "event_slug": concept.event.slug if concept else None,
        })

    lesson_query = select(LessonProgress).join(Lesson).where(
        LessonProgress.user_id == user.id, LessonProgress.status == "in_progress",
        Lesson.status == "published",
    ).order_by(LessonProgress.last_viewed_at.desc())
    progress_rows = db.scalars(lesson_query).all()
    if event:
        progress_rows = [row for row in progress_rows if db.get(Lesson, row.lesson_id).event_id == event.id]
    if progress_rows:
        progress = progress_rows[0]
        lesson = db.get(Lesson, progress.lesson_id)
        candidates.append({
            "type": "lesson", "entity_id": lesson.id, "title": f"Resume: {lesson.title}",
            "summary": lesson.summary, "why": "You already started this lesson; finishing reduces context switching.",
            "estimated_minutes": max(4, lesson.estimated_minutes // 2), "priority": 82,
            "urgency": "normal", "action_label": "Resume Lesson", "route": f"/#lesson={lesson.id}",
            "event_slug": lesson.event.slug,
        })
    else:
        lesson_stmt = select(Lesson).where(Lesson.status == "published")
        if event:
            lesson_stmt = lesson_stmt.where(Lesson.event_id == event.id)
        lessons = db.scalars(lesson_stmt.order_by(Lesson.sequence, Lesson.id)).all()
        progress_by_lesson = {
            row.lesson_id: row for row in db.scalars(select(LessonProgress).where(
                LessonProgress.user_id == user.id,
            )).all()
        }
        lesson = next((row for row in lessons if progress_by_lesson.get(row.id) is None), None)
        if lesson:
            candidates.append({
                "type": "lesson", "entity_id": lesson.id, "title": lesson.title,
                "summary": lesson.summary, "why": "This is the next unfinished step in your learning path.",
                "estimated_minutes": lesson.estimated_minutes, "priority": 62,
                "urgency": "normal", "action_label": "Start Lesson", "route": f"/#lesson={lesson.id}",
                "event_slug": lesson.event.slug,
            })

    exam_stmt = select(Exam).join(Event).where(Exam.published.is_(True))
    if event:
        exam_stmt = exam_stmt.where(Exam.event_id == event.id)
    available_exams = db.scalars(exam_stmt.order_by(Exam.created_at.desc())).all()
    completed_exam_ids = set(db.scalars(select(Attempt.exam_id).where(
        Attempt.user_id == user.id, Attempt.submitted_at.is_not(None),
    )).all())
    exam = next((row for row in available_exams if row.id not in completed_exam_ids), None)
    if exam:
        candidates.append({
            "type": "timed_drill", "entity_id": exam.id, "exam_id": exam.id,
            "title": exam.title, "summary": "Practice retrieval, pacing, and confidence under a real timer.",
            "why": "You have not completed this reviewed form yet.",
            "estimated_minutes": exam.duration_minutes, "priority": 48,
            "urgency": "normal", "action_label": "Start Timed Drill",
            "route": f"/#practice?event={exam.event.slug}", "event_slug": exam.event.slug,
        })

    candidates.sort(key=lambda item: (-item["priority"], item["estimated_minutes"], item["title"]))
    selected = []
    used_types = set()
    minutes = 0
    for candidate in candidates:
        family = candidate["type"]
        if family in used_types:
            continue
        if selected and minutes + candidate["estimated_minutes"] > 35:
            continue
        selected.append(candidate)
        used_types.add(family)
        minutes += candidate["estimated_minutes"]
        if len(selected) == 3:
            break

    activity_dates = set()
    cutoff = now - timedelta(days=7)
    for progress in db.scalars(select(LessonProgress).where(
        LessonProgress.user_id == user.id, LessonProgress.last_viewed_at >= cutoff,
    )).all():
        activity_dates.add(_aware(progress.last_viewed_at).date())
    for attempt in db.scalars(select(Attempt).where(
        Attempt.user_id == user.id, Attempt.submitted_at >= cutoff,
    )).all():
        activity_dates.add(_aware(attempt.submitted_at).date())
    for session in db.scalars(select(PracticeSession).where(
        PracticeSession.user_id == user.id, PracticeSession.last_active_at >= cutoff,
    )).all():
        activity_dates.add(_aware(session.last_active_at).date())

    return {
        "generated_at": now.isoformat(), "focus_event": event.slug if event else None,
        "items": selected, "total_estimated_minutes": minutes,
        "signals": {
            "open_remediation": len(open_cases), "due_reviews": len(mastery_rows),
            "pending_assignments": pending_assignment_count,
            "active_days_last_7": len(activity_dates),
        },
        "policy": {"maximum_items": 3, "target_maximum_minutes": 35, "fixed_assessment_exception": True, "repeat_type_limit": 1, "version": "1.0"},
    }
