from datetime import datetime, timedelta, timezone
from app.core.database import SessionLocal
from app.models.entities import Attempt, Event, ExamItem, Question, Source


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def seed_exam(client, admin_token, duration=20):
    with SessionLocal() as db:
        event = Event(slug=f"event-{duration}", name="Test Event", division="B", season=2026)
        db.add(event)
        db.commit()
        db.refresh(event)
        event_id = event.id
    client.post("/api/questions/generate", headers=auth(admin_token), json={
        "event_id": event_id, "count": 1, "difficulty": 0.5,
        "cognitive_level": "application", "question_type": "single_choice",
    })
    with SessionLocal() as db:
        for question in db.query(Question).filter(Question.event_id == event_id):
            question.status = "published"
        db.commit()
    return client.post("/api/exams", headers=auth(admin_token), json={
        "event_id": event_id, "title": "Integrity Mock", "duration_minutes": duration,
        "question_count": 1, "published": True,
    }).json()["id"]


def test_coach_cannot_create_or_approve_sources(client, coach_token):
    created = client.post("/api/sources", headers=auth(coach_token), json={
        "url": "https://science.nasa.gov/test", "rights_status": "fact_grounding_allowed",
    })
    assert created.status_code == 403


def test_exam_snapshot_is_immutable(client, admin_token, student_token):
    exam_id = seed_exam(client, admin_token)
    with SessionLocal() as db:
        item = db.query(ExamItem).filter(ExamItem.exam_id == exam_id).one()
        original_stem = item.snapshot["stem"]
        question = db.get(Question, item.question_id)
        question.stem = "MUTATED AFTER PUBLICATION"
        db.commit()
    started = client.post(f"/api/exams/{exam_id}/start", headers=auth(student_token))
    assert started.status_code == 200
    assert started.json()["questions"][0]["stem"] == original_stem


def test_stale_and_duplicate_response_writes(client, admin_token, student_token):
    exam_id = seed_exam(client, admin_token)
    started = client.post(f"/api/exams/{exam_id}/start", headers=auth(student_token)).json()
    attempt_id = started["attempt_id"]
    qid = started["questions"][0]["id"]
    payload = {
        "question_id": qid, "answer": {"selected_index": 0}, "confidence": 3,
        "time_spent_seconds": 5, "sequence_number": 1, "idempotency_key": "save-key-00000001",
    }
    first = client.put(f"/api/attempts/{attempt_id}/responses", headers=auth(student_token), json=payload)
    assert first.status_code == 200 and not first.json()["duplicate"]
    duplicate = client.put(f"/api/attempts/{attempt_id}/responses", headers=auth(student_token), json=payload)
    assert duplicate.status_code == 200 and duplicate.json()["duplicate"]
    stale = {**payload, "idempotency_key": "save-key-00000002"}
    assert client.put(f"/api/attempts/{attempt_id}/responses", headers=auth(student_token), json=stale).status_code == 409


def test_server_enforces_deadline(client, admin_token, student_token):
    exam_id = seed_exam(client, admin_token, duration=1)
    started = client.post(f"/api/exams/{exam_id}/start", headers=auth(student_token)).json()
    with SessionLocal() as db:
        attempt = db.get(Attempt, started["attempt_id"])
        attempt.deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    qid = started["questions"][0]["id"]
    result = client.put(f"/api/attempts/{started['attempt_id']}/responses", headers=auth(student_token), json={
        "question_id": qid, "answer": {"selected_index": 0}, "confidence": 3,
        "time_spent_seconds": 5, "sequence_number": 1, "idempotency_key": "expired-save-0001",
    })
    assert result.status_code == 409
    assert "automatically submitted" in result.json()["detail"]


def test_source_approval_requires_admin(client, admin_token, coach_token):
    with SessionLocal() as db:
        source = Source(url="https://science.nasa.gov/x", title="x", rights_status="fact_grounding_allowed")
        db.add(source)
        db.commit()
        db.refresh(source)
        source_id = source.id
    assert client.post(f"/api/sources/{source_id}/approve", headers=auth(coach_token)).status_code == 403
    assert client.post(f"/api/sources/{source_id}/approve", headers=auth(admin_token)).status_code == 200
