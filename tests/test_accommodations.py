from datetime import datetime

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.entities import (
    AccommodationChange, Attempt, Concept, Event, Exam, ExamItem, Organization,
    PracticeSet, PracticeSetVersion, Question, Team, TeamMembership, User,
)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def configure_school_and_content():
    with SessionLocal() as db:
        student = db.scalar(select(User).where(User.email == "s@example.com"))
        coach = db.scalar(select(User).where(User.email == "coach@example.com"))
        organization = Organization(name="Accommodation School", slug="accommodation-school")
        db.add(organization)
        db.flush()
        student.organization_id = organization.id
        coach.organization_id = organization.id
        event = Event(slug="accessible-event", name="Accessible Event", division="B", season=2026)
        db.add(event)
        db.flush()
        concept = Concept(event_id=event.id, name="Accessible concept")
        db.add(concept)
        db.flush()
        question = Question(
            event_id=event.id,
            concept_id=concept.id,
            stem="Which answer is supported?",
            question_type="single_choice",
            choices=["Supported", "Unsupported"],
            answer_spec={"correct_index": 0},
            explanation="The first answer is keyed.",
            status="published",
            citations=[{"title": "Reviewed source"}],
        )
        db.add(question)
        db.flush()
        exams = []
        for index in range(2):
            exam = Exam(
                event_id=event.id,
                organization_id=organization.id,
                title=f"Accessible Mock {index + 1}",
                duration_minutes=20,
                question_ids=[question.id],
                published=True,
            )
            db.add(exam)
            db.flush()
            db.add(ExamItem(
                exam_id=exam.id,
                question_id=question.id,
                position=0,
                question_version=1,
                snapshot={
                    "stem": question.stem,
                    "question_type": "single_choice",
                    "choices": question.choices,
                    "answer_spec": question.answer_spec,
                },
            ))
            exams.append(exam)
        practice = PracticeSet(
            event_id=event.id,
            concept_id=concept.id,
            slug="accessible-practice",
            title="Accessible Practice",
            summary="Timed practice",
            status="published",
            current_version=1,
        )
        db.add(practice)
        db.flush()
        db.add(PracticeSetVersion(
            practice_set_id=practice.id,
            version=1,
            review_status="sme_approved",
            claim_ids=[1],
            citations=[{"title": "Reviewed source"}],
            items=[{
                "id": "one",
                "prompt": "Choose one.",
                "property_profile": [{"label": "Evidence", "value": "Supported"}],
                "choices": ["Supported", "Unsupported"],
                "correct_index": 0,
                "explanation": "Supported is correct.",
            }],
        ))
        team = Team(
            organization_id=organization.id,
            name="Access Team",
            division="B",
            season=2026,
            created_by_user_id=coach.id,
        )
        db.add(team)
        db.flush()
        db.add_all([
            TeamMembership(team_id=team.id, user_id=coach.id, membership_role="coach"),
            TeamMembership(team_id=team.id, user_id=student.id, membership_role="student"),
        ])
        db.commit()
        return student.id, organization.id, [exam.id for exam in exams], practice.id


def test_timed_accommodation_is_audited_and_snapshotted(
    client, student_token, coach_token
):
    student_id, _, exam_ids, practice_id = configure_school_and_content()
    default = client.get("/api/me/accommodations", headers=auth(student_token)).json()
    assert default == {
        "active": False,
        "time_multiplier": 1.0,
        "reduced_distraction": False,
        "screen_reader_alternative": False,
        "breaks_allowed": False,
        "effective_from": None,
        "effective_until": None,
    }
    forbidden = client.put(
        f"/api/students/{student_id}/accommodations",
        headers=auth(student_token),
        json={"time_multiplier": 3, "reason": "Student cannot approve their own plan."},
    )
    assert forbidden.status_code == 403

    first_plan = client.put(
        f"/api/students/{student_id}/accommodations",
        headers=auth(coach_token),
        json={
            "time_multiplier": 1.5,
            "active": True,
            "reason": "Approved school access plan for timed assessments.",
        },
    )
    assert first_plan.status_code == 200
    assert first_plan.json()["time_multiplier"] == 1.5
    own_view = client.get("/api/me/accommodations", headers=auth(student_token)).json()
    assert own_view["screen_reader_alternative"] is False
    assert "reason" not in own_view

    catalog = client.get("/api/exams", headers=auth(student_token)).json()
    assert {row["effective_duration_minutes"] for row in catalog} == {30}
    exam = client.post(f"/api/exams/{exam_ids[0]}/start", headers=auth(student_token)).json()
    assert exam["base_duration_minutes"] == 20
    assert exam["duration_minutes"] == 30
    assert exam["time_multiplier"] == 1.5
    exam_seconds = (
        datetime.fromisoformat(exam["deadline_at"].replace("Z", "+00:00"))
        - datetime.fromisoformat(exam["started_at"].replace("Z", "+00:00"))
    ).total_seconds()
    assert exam_seconds == 30 * 60

    station = client.post(
        f"/api/practice-sets/{practice_id}/start",
        headers=auth(student_token),
        json={"mode": "station", "seconds_per_item": 45},
    ).json()
    assert station["base_seconds_per_item"] == 45
    assert station["seconds_per_item"] == 68
    assert station["time_multiplier"] == 1.5

    updated = client.put(
        f"/api/students/{student_id}/accommodations",
        headers=auth(coach_token),
        json={
            "time_multiplier": 2,
            "active": True,
            "reason": "Updated approved plan for future timed sessions only.",
        },
    )
    assert updated.json()["time_multiplier"] == 2
    resumed_exam = client.post(
        f"/api/exams/{exam_ids[0]}/start", headers=auth(student_token)
    ).json()
    resumed_station = client.post(
        f"/api/practice-sets/{practice_id}/start",
        headers=auth(student_token),
        json={"mode": "station", "seconds_per_item": 45},
    ).json()
    assert resumed_exam["attempt_id"] == exam["attempt_id"]
    assert resumed_exam["time_multiplier"] == 1.5
    assert resumed_exam["deadline_at"] == exam["deadline_at"]
    assert resumed_station["session_id"] == station["session_id"]
    assert resumed_station["seconds_per_item"] == 68

    new_exam = client.post(
        f"/api/exams/{exam_ids[1]}/start", headers=auth(student_token)
    ).json()
    new_station = client.post(
        f"/api/practice-sets/{practice_id}/start",
        headers=auth(student_token),
        json={"mode": "station", "seconds_per_item": 60},
    ).json()
    assert new_exam["duration_minutes"] == 40
    assert new_exam["time_multiplier"] == 2
    assert new_station["seconds_per_item"] == 120
    assert new_station["time_multiplier"] == 2
    with SessionLocal() as db:
        assert len(db.scalars(select(AccommodationChange)).all()) == 2
        stored = db.get(Attempt, exam["attempt_id"])
        assert stored.time_multiplier == 1.5


def test_coach_cannot_manage_student_outside_shared_team(
    client, coach_token, student_token
):
    _, _, _, _ = configure_school_and_content()
    with SessionLocal() as db:
        other_org = Organization(name="Other School", slug="other-school")
        db.add(other_org)
        db.flush()
        outsider = User(
            email="outside@example.com",
            full_name="Outside Student",
            password_hash=hash_password("password123"),
            role="student",
            organization_id=other_org.id,
        )
        db.add(outsider)
        db.commit()
        outsider_id = outsider.id
    response = client.get(
        f"/api/students/{outsider_id}/accommodations", headers=auth(coach_token)
    )
    assert response.status_code == 404
