from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.entities import (
    Assignment, Concept, Event, Exam, Lesson, LessonProgress, MasteryState, Organization,
    PracticeSet, RemediationCase, Team, TeamMembership, User,
)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_daily_plan_prioritizes_error_due_retrieval_and_resume_without_fatigue(client, student_token):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        student = db.query(User).filter(User.email == "s@example.com").one()
        event = Event(slug="daily-rocks", name="Daily Rocks", division="B", season=2026)
        db.add(event)
        db.flush()
        concept = Concept(event_id=event.id, name="Diagnostic hardness")
        db.add(concept)
        db.flush()
        lesson = Lesson(
            event_id=event.id, concept_id=concept.id, slug="hardness-path",
            title="Read the Hardness Evidence", summary="Use scratch evidence to narrow candidates.",
            status="published", sequence=1, estimated_minutes=12,
        )
        practice = PracticeSet(
            event_id=event.id, concept_id=concept.id, slug="hardness-retrieval",
            title="Hardness Retrieval", status="published", estimated_minutes=8,
        )
        db.add_all([lesson, practice])
        db.flush()
        db.add(LessonProgress(
            user_id=student.id, lesson_id=lesson.id, lesson_version=1,
            status="in_progress", current_block=1, started_at=now - timedelta(days=1),
            last_viewed_at=now - timedelta(hours=2),
        ))
        db.add(MasteryState(
            user_id=student.id, concept_id=concept.id, mastery_probability=0.45,
            evidence_count=3, misconception_risk=0.8,
            last_practiced_at=now - timedelta(days=5), next_review_at=now - timedelta(hours=1),
        ))
        db.add(RemediationCase(
            user_id=student.id, question_id=None, concept_id=concept.id,
            source_type="practice", source_ref="daily-plan-case", error_type="property_confusion",
            status="delayed_review", diagnosis={}, plan={
                "explanation": "Separate hardness from streak before identifying the specimen.",
                "next_review_at": (now - timedelta(minutes=30)).isoformat(),
            },
        ))
        db.commit()

    response = client.get(
        "/api/student/dashboard?event_slug=daily-rocks", headers=auth(student_token)
    )
    assert response.status_code == 200
    plan = response.json()["daily_plan"]
    assert [item["type"] for item in plan["items"]] == [
        "remediation", "spaced_review", "lesson",
    ]
    assert plan["items"][0]["urgency"] == "overdue"
    assert all(item["why"] and item["action_label"] for item in plan["items"])
    assert plan["total_estimated_minutes"] <= 35
    assert plan["signals"]["due_reviews"] == 1
    assert plan["signals"]["active_days_last_7"] == 1
    assert len({item["type"] for item in plan["items"]}) == len(plan["items"])


def test_due_coach_assignment_outranks_new_lesson_and_plan_is_event_scoped(client, student_token):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        student = db.query(User).filter(User.email == "s@example.com").one()
        org = Organization(name="Daily Plan School", slug="daily-plan-school")
        db.add(org)
        db.flush()
        student.organization_id = org.id
        team = Team(
            organization_id=org.id, name="Daily Team", division="B", season=2026,
            created_by_user_id=student.id,
        )
        focused = Event(slug="daily-entomology", name="Daily Entomology", division="B", season=2026)
        other = Event(slug="other-subject", name="Other Subject", division="B", season=2026)
        db.add_all([team, focused, other])
        db.flush()
        db.add(TeamMembership(team_id=team.id, user_id=student.id, membership_role="student"))
        focused_lesson = Lesson(
            event_id=focused.id, slug="insect-lesson", title="Read the Insect Body Plan",
            status="published", sequence=1, estimated_minutes=10,
        )
        other_lesson = Lesson(
            event_id=other.id, slug="other-lesson", title="Unrelated Lesson",
            status="published", sequence=0, estimated_minutes=5,
        )
        exam = Exam(
            event_id=focused.id, organization_id=org.id, title="Coach Anatomy Check",
            duration_minutes=10, published=True,
        )
        db.add_all([focused_lesson, other_lesson, exam])
        db.flush()
        db.add(Assignment(
            organization_id=org.id, team_id=team.id, exam_id=exam.id,
            title="Anatomy Check Due Tomorrow", due_at=now + timedelta(hours=12),
            created_by_user_id=student.id,
        ))
        db.commit()

    plan = client.get(
        "/api/student/dashboard?event_slug=daily-entomology", headers=auth(student_token)
    ).json()["daily_plan"]
    assert plan["items"][0]["type"] == "assignment"
    assert plan["items"][0]["urgency"] == "high"
    assert any(item["type"] == "lesson" and item["title"] == "Read the Insect Body Plan" for item in plan["items"])
    assert all(item.get("event_slug") != "other-subject" for item in plan["items"])
    assert plan["signals"]["pending_assignments"] == 1
