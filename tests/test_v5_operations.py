from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.security import create_access_token, hash_password
from app.models.entities import (
    Assignment, BackgroundJob, Event, Exam, Organization, Question,
    Team, TeamMembership, User,
)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_background_job_lifecycle(client, admin_token):
    created = client.post(
        "/api/jobs",
        headers=auth(admin_token),
        json={"job_type": "scan_delayed_reviews", "payload": {}},
    )
    assert created.status_code == 200
    job_id = created.json()["id"]
    ran = client.post("/api/jobs/run-next", headers=auth(admin_token))
    assert ran.status_code == 200
    assert ran.json()["ran"] is True
    assert ran.json()["status"] == "completed"
    fetched = client.get(f"/api/jobs/{job_id}", headers=auth(admin_token))
    assert fetched.status_code == 200
    assert fetched.json()["result"]["count"] == 0
    with SessionLocal() as db:
        assert db.get(BackgroundJob, job_id).attempts == 1


def test_model_generation_requires_configured_provider(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="model-test", name="Model Test", division="B", season=2026)
        db.add(event)
        db.commit()
        event_id = event.id
    result = client.post(
        "/api/questions/generate-model",
        headers=auth(admin_token),
        json={"event_id": event_id, "count": 1, "question_type": "single_choice"},
    )
    assert result.status_code == 503
    assert "provider" in result.json()["detail"].lower() or "claims" in result.json()["detail"].lower()


def test_team_assignment_and_dashboard(client):
    with SessionLocal() as db:
        org = Organization(name="Assignment School", slug="assignment-school")
        db.add(org)
        db.flush()
        coach = User(
            email="assignment-coach@example.com", full_name="Coach", password_hash=hash_password("password123"),
            role="coach", organization_id=org.id,
        )
        student = User(
            email="assignment-student@example.com", full_name="Student", password_hash=hash_password("password123"),
            role="student", organization_id=org.id,
        )
        db.add_all([coach, student])
        db.flush()
        team = Team(
            organization_id=org.id, name="Team A", division="B", season=2026,
            created_by_user_id=coach.id,
        )
        db.add(team)
        db.flush()
        db.add_all([
            TeamMembership(team_id=team.id, user_id=coach.id, membership_role="coach"),
            TeamMembership(team_id=team.id, user_id=student.id, membership_role="student"),
        ])
        event = Event(slug="assignment-event", name="Assignment Event", division="B", season=2026)
        db.add(event)
        db.flush()
        question = Question(
            event_id=event.id, status="machine_validated", stem="Which answer is correct?",
            choices=["A", "B"], answer_spec={"correct_index": 0, "points": 1}, explanation="A",
        )
        db.add(question)
        db.flush()
        exam = Exam(
            event_id=event.id, organization_id=org.id, title="Assigned Exam", duration_minutes=20,
            question_ids=[question.id], published=True,
        )
        db.add(exam)
        db.commit()
        coach_token = create_access_token(str(coach.id))
        student_token = create_access_token(str(student.id))
        team_id, exam_id = team.id, exam.id
    created = client.post(
        "/api/assignments",
        headers=auth(coach_token),
        json={
            "team_id": team_id, "exam_id": exam_id, "title": "Week 1",
            "due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        },
    )
    assert created.status_code == 200
    listed = client.get("/api/assignments", headers=auth(student_token))
    assert listed.status_code == 200 and listed.json()[0]["title"] == "Week 1"
    notifications = client.get("/api/notifications", headers=auth(student_token))
    assert notifications.status_code == 200
    assert notifications.json()["notifications"][0]["type"] == "assignment_published"
    dashboard = client.get("/api/coach/dashboard", headers=auth(coach_token))
    assert dashboard.status_code == 200
    assert dashboard.json()["students"] == 1
    assert dashboard.json()["assignments"] == 1
    assert dashboard.json()["student_rows"][0]["full_name"] == "Student"
    assert dashboard.json()["student_rows"][0]["total_assignments"] == 1
    with SessionLocal() as db:
        assert db.scalar(select(Assignment)).title == "Week 1"


def test_rate_limit_headers_are_present(client):
    response = client.post("/api/auth/login", json={"email": "none@example.com", "password": "password123"})
    assert response.status_code == 401
    assert response.headers["X-RateLimit-Limit"]


def test_failed_job_backs_off_and_eventually_dead_letters(client, admin_token, monkeypatch):
    def fail_discovery(*args, **kwargs):
        raise ValueError("simulated discovery failure")

    monkeypatch.setattr("app.services.jobs.discover_sitemap", fail_discovery)
    created = client.post(
        "/api/jobs",
        headers=auth(admin_token),
        json={
            "job_type": "discover_sitemap",
            "payload": {"url": "https://science.nasa.gov/sitemap.xml"},
        },
    )
    job_id = created.json()["id"]
    first = client.post("/api/jobs/run-next", headers=auth(admin_token)).json()
    assert first["status"] == "queued"
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        assert job.scheduled_at > datetime.now(timezone.utc).replace(tzinfo=None)
        for expected_attempt in (2, 3):
            job.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
            result = client.post("/api/jobs/run-next", headers=auth(admin_token)).json()
            assert result["status"] == ("queued" if expected_attempt == 2 else "dead_letter")
