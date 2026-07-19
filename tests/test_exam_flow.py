from app.core.database import SessionLocal
from app.models.entities import Event, Question


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_full_exam_and_remediation_flow(client, admin_token, student_token):
    db = SessionLocal()
    event = Event(
        slug="meteorology", name="Meteorology", division="B", season=2026, description="Weather"
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    event_id = event.id
    db.close()
    gen = client.post(
        "/api/questions/generate",
        headers=auth(admin_token),
        json={
            "event_id": event_id,
            "count": 3,
            "difficulty": 0.5,
            "cognitive_level": "application",
            "question_type": "single_choice",
        },
    )
    assert gen.status_code == 200 and len(gen.json()) == 3
    with SessionLocal() as db:
        for question in db.query(Question).filter(Question.event_id == event_id):
            question.status = "published"
        db.commit()
    exam = client.post(
        "/api/exams",
        headers=auth(admin_token),
        json={
            "event_id": event_id,
            "title": "Mock",
            "duration_minutes": 20,
            "question_count": 3,
            "published": True,
        },
    )
    assert exam.status_code == 200
    exam_id = exam.json()["id"]
    started = client.post(f"/api/exams/{exam_id}/start", headers=auth(student_token))
    assert started.status_code == 200
    attempt = started.json()
    assert attempt["started_at"].endswith("Z")
    assert attempt["deadline_at"].endswith("Z")
    q = attempt["questions"][0]
    saved = client.put(
        f"/api/attempts/{attempt['attempt_id']}/responses",
        headers=auth(student_token),
        json={
            "question_id": q["id"],
            "answer": {"selected_index": 99},
            "confidence": 5,
            "time_spent_seconds": 10,
            "sequence_number": 1,
            "idempotency_key": "attempt-save-0001",
        },
    )
    assert saved.status_code == 200
    submit = client.post(
        f"/api/attempts/{attempt['attempt_id']}/submit", headers=auth(student_token)
    )
    assert submit.status_code == 200
    assert submit.json()["max_score"] == 3
    review = client.get(
        f"/api/attempts/{attempt['attempt_id']}/review", headers=auth(student_token)
    )
    assert review.status_code == 200
    cases = review.json()["remediation_cases"]
    assert len(cases) >= 1
    case_id = cases[0]["id"]
    assert (
        client.post(f"/api/remediation/{case_id}/resolve", headers=auth(student_token)).status_code
        == 400
    )
    ref = client.put(
        f"/api/remediation/{case_id}/reflection",
        headers=auth(student_token),
        json={"reflection": "I selected an answer without checking what the instrument measures."},
    )
    assert ref.status_code == 200
    resolved = client.post(f"/api/remediation/{case_id}/resolve", headers=auth(student_token))
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "delayed_review"
