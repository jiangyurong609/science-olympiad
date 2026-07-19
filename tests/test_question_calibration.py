from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.entities import Attempt, Event, Exam, ExamItem, Question, Response, User


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def seed_pilot(sample_size=30):
    with SessionLocal() as db:
        event = Event(slug="calibration-pilot", name="Calibration Pilot", division="B", season=2026)
        db.add(event)
        db.flush()
        item = Question(
            event_id=event.id, status="published", stem="Which mineral property measures resistance to scratching?",
            choices=["Hardness", "Streak", "Luster", "Cleavage"],
            answer_spec={"correct_index": 0, "points": 1}, validation_report={"passed": True},
        )
        anchor = Question(
            event_id=event.id, status="published", stem="Which instrument measures mass?",
            choices=["Balance", "Thermometer", "Ruler", "Barometer"],
            answer_spec={"correct_index": 0, "points": 1}, validation_report={"passed": True},
        )
        db.add_all([item, anchor])
        db.flush()
        exam = Exam(event_id=event.id, title="Pilot Form", published=True, question_ids=[item.id, anchor.id])
        db.add(exam)
        db.flush()
        for position, question in enumerate((item, anchor)):
            db.add(ExamItem(
                exam_id=exam.id, question_id=question.id, question_version=question.version,
                position=position, snapshot={
                    "stem": question.stem, "question_type": "single_choice",
                    "choices": question.choices, "answer_spec": question.answer_spec,
                },
            ))
        for index in range(sample_size):
            high_performer = index < sample_size // 2
            user = User(
                email=f"pilot-{index}@example.com", full_name=f"Pilot {index}",
                role="student", division="B",
            )
            db.add(user)
            db.flush()
            attempt = Attempt(
                exam_id=exam.id, user_id=user.id, submitted_at=datetime.now(timezone.utc),
                score=2 if high_performer else 0, max_score=2,
                status="remediation_complete" if high_performer else "remediation_open",
            )
            db.add(attempt)
            db.flush()
            for question in (item, anchor):
                db.add(Response(
                    attempt_id=attempt.id, question_id=question.id,
                    answer={"selected_index": 0 if high_performer else 1},
                    is_correct=high_performer, points_awarded=1 if high_performer else 0,
                    confidence=4 if high_performer else 2, time_spent_seconds=35 + index,
                ))
        calibrator = User(
            email="calibrator@example.com", full_name="Independent Calibrator", role="calibrator",
        )
        db.add(calibrator)
        db.commit()
        return item.id, create_access_token(str(calibrator.id))


def test_calibration_requires_sufficient_unique_students(client):
    question_id, token = seed_pilot(sample_size=10)
    response = client.post(f"/api/content/questions/{question_id}/calibration", headers=auth(token), json={
        "decision": "accepted", "notes": "Pilot statistics reviewed against the approved thresholds.",
    })
    assert response.status_code == 409
    assert "insufficient_unique_students" in response.json()["detail"]["failures"]


def test_calibration_records_metrics_and_promotes_exact_version(client):
    question_id, token = seed_pilot(sample_size=30)
    queue = client.get("/api/content/questions/calibration-queue", headers=auth(token))
    assert queue.status_code == 200
    candidate = next(row for row in queue.json() if row["id"] == question_id)
    assert candidate["passed"] is True
    assert candidate["metrics"]["sample_size"] == 30
    assert candidate["metrics"]["facility"] == 0.5
    assert candidate["metrics"]["corrected_item_total_discrimination"] == 1.0

    accepted = client.post(f"/api/content/questions/{question_id}/calibration", headers=auth(token), json={
        "decision": "accepted", "notes": "Representative pilot statistics meet every deterministic threshold.",
    })
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "calibrated"
    assert accepted.json()["metrics"]["unique_student_policy"] == "first_scored_exposure_per_user"
