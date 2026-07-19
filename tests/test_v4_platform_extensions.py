from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.security import create_access_token, hash_password
from app.models.entities import (
    Concept, Event, Organization, RemediationCase, ScientificClaim, Source, SourceSnapshot,
    TeamMembership, TransferAttempt, User,
)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_extract_claims_requires_crawled_approved_source(client, admin_token):
    with SessionLocal() as db:
        source = Source(
            url="https://science.nasa.gov/test-claims",
            title="Test source",
            rights_status="fact_grounding_allowed",
            approved=True,
            extracted_text=(
                "Atmospheric pressure is the force exerted by the weight of air above a surface. "
                "A barometer is an instrument used to measure atmospheric pressure."
            ),
            content_hash="c" * 64,
        )
        db.add(source)
        db.flush()
        db.add(SourceSnapshot(
            source_id=source.id, final_url=source.url, content_hash=source.content_hash,
            content_type="text/html", byte_count=len(source.extracted_text),
            extracted_text=source.extracted_text,
        ))
        db.commit()
        source_id = source.id
    result = client.post(
        f"/api/sources/{source_id}/extract-claims",
        headers=auth(admin_token),
        json={"limit": 5},
    )
    assert result.status_code == 200
    assert len(result.json()) == 2
    assert all(item["approved"] is False for item in result.json())
    with SessionLocal() as db:
        assert len(db.scalars(select(ScientificClaim)).all()) == 2


def test_team_creation_and_membership_are_tenant_scoped(client):
    with SessionLocal() as db:
        org = Organization(name="Test School", slug="test-school")
        other = Organization(name="Other School", slug="other-school")
        db.add_all([org, other])
        db.flush()
        coach = User(email="teamcoach@example.com", full_name="Coach", password_hash=hash_password("password123"), role="coach", organization_id=org.id)
        student = User(email="teamstudent@example.com", full_name="Student", password_hash=hash_password("password123"), role="student", organization_id=org.id)
        outsider = User(email="outsider@example.com", full_name="Outsider", password_hash=hash_password("password123"), role="student", organization_id=other.id)
        db.add_all([coach, student, outsider])
        db.commit()
        coach_token = create_access_token(str(coach.id))
    created = client.post("/api/teams", headers=auth(coach_token), json={"name": "Varsity", "division": "C", "season": 2026})
    assert created.status_code == 200
    team_id = created.json()["id"]
    added = client.post(f"/api/teams/{team_id}/members", headers=auth(coach_token), json={"user_email": "teamstudent@example.com", "membership_role": "student"})
    assert added.status_code == 200
    blocked = client.post(f"/api/teams/{team_id}/members", headers=auth(coach_token), json={"user_email": "outsider@example.com", "membership_role": "student"})
    assert blocked.status_code == 404
    with SessionLocal() as db:
        assert len(db.scalars(select(TeamMembership)).all()) == 2


def test_delayed_review_resolves_only_after_due_and_correct(client, student_token):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "s@example.com"))
        event = Event(slug="delayed-event", name="Delayed", division="B", season=2026)
        db.add(event)
        db.flush()
        concept = Concept(event_id=event.id, name="Delayed concept")
        db.add(concept)
        db.flush()
        from app.models.entities import Question
        question = Question(
            event_id=event.id, concept_id=concept.id, status="machine_validated",
            stem="Which option is correct?", choices=["Correct", "Wrong"],
            answer_spec={"correct_index": 0, "points": 1}, explanation="Correct is correct.",
        )
        db.add(question)
        db.flush()
        case = RemediationCase(
            attempt_id=999, user_id=user.id, question_id=question.id, concept_id=concept.id,
            error_type="knowledge", status="delayed_review",
            plan={"next_review_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()},
            student_reflection="I now understand the key concept clearly.",
        )
        db.add(case)
        db.commit()
        case_id = case.id
    due = client.get("/api/remediation/due", headers=auth(student_token))
    assert due.status_code == 200 and due.json()[0]["id"] == case_id
    review = client.post(f"/api/remediation/{case_id}/delayed-review", headers=auth(student_token))
    assert review.status_code == 200
    transfer_id = review.json()["transfer_id"]
    with SessionLocal() as db:
        transfer = db.get(TransferAttempt, transfer_id)
        correct = transfer.question_payload["answer_spec"]["correct_index"]
    result = client.post(f"/api/remediation/delayed-review/{transfer_id}/submit", headers=auth(student_token), json={"answer": {"selected_index": correct}})
    assert result.status_code == 200
    assert result.json()["remediation_status"] == "resolved"
