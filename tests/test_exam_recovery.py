from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Attempt, AttemptSubmission, Event, Exam, ExamItem, Question, Response,
    ResponseRevision, User,
)


def auth(token, session_id=None):
    headers = {"Authorization": f"Bearer {token}"}
    if session_id:
        headers["X-Exam-Client-Session"] = session_id
    return headers


def seed_recovery_exam():
    with SessionLocal() as db:
        event = Event(slug="recovery-event", name="Recovery Event", division="B", season=2026)
        db.add(event)
        db.flush()
        question = Question(
            event_id=event.id, status="published",
            stem="Which property is measured by a scratch comparison?",
            choices=["Hardness", "Streak", "Luster", "Cleavage"],
            answer_spec={"correct_index": 0, "points": 1}, explanation="Hardness resists scratching.",
        )
        db.add(question)
        db.flush()
        exam = Exam(
            event_id=event.id, title="Recovery Form", duration_minutes=20,
            question_ids=[question.id], published=True,
        )
        db.add(exam)
        db.flush()
        db.add(ExamItem(
            exam_id=exam.id, question_id=question.id, question_version=question.version,
            position=0, snapshot={
                "stem": question.stem, "choices": question.choices,
                "question_type": "single_choice", "answer_spec": question.answer_spec,
                "explanation": question.explanation,
            },
        ))
        db.commit()
        return exam.id, question.id


def save_payload(question_id, sequence, selected, key, offline=False):
    return {
        "question_id": question_id, "answer": {"selected_index": selected},
        "confidence": 3 + selected, "time_spent_seconds": 12 + sequence,
        "sequence_number": sequence, "idempotency_key": key,
        "client_metadata": {
            "client_session_id": "browser-session-a",
            "offline_replay": offline, "connection": "reconnected" if offline else "online",
        },
    }


def test_refresh_restores_latest_revision_and_submission_manifest_is_immutable(client, student_token):
    exam_id, question_id = seed_recovery_exam()
    started = client.post(
        f"/api/exams/{exam_id}/start", headers=auth(student_token, "browser-session-a")
    )
    assert started.status_code == 200
    attempt_id = started.json()["attempt_id"]

    first = client.put(
        f"/api/attempts/{attempt_id}/responses", headers=auth(student_token),
        json=save_payload(question_id, 1, 0, "recovery-save-key-0001"),
    )
    second = client.put(
        f"/api/attempts/{attempt_id}/responses", headers=auth(student_token),
        json=save_payload(question_id, 2, 1, "recovery-save-key-0002", offline=True),
    )
    assert first.status_code == 200 and second.status_code == 200
    retry_old = client.put(
        f"/api/attempts/{attempt_id}/responses", headers=auth(student_token),
        json=save_payload(question_id, 1, 0, "recovery-save-key-0001"),
    )
    assert retry_old.status_code == 200
    assert retry_old.json()["duplicate"] is True
    assert retry_old.json()["revision_id"] == first.json()["revision_id"]

    restored = client.post(
        f"/api/exams/{exam_id}/start", headers=auth(student_token, "browser-session-a")
    )
    question = restored.json()["questions"][0]
    assert restored.json()["restored_response_count"] == 1
    assert question["saved_answer"] == {"selected_index": 1}
    assert question["saved_confidence"] == 4
    assert question["saved_sequence_number"] == 2
    assert question["saved_time_spent_seconds"] == 14

    wrong_owner = client.post(
        f"/api/attempts/{attempt_id}/submit", headers=auth(student_token, "browser-session-b")
    )
    assert wrong_owner.status_code == 409
    submitted = client.post(
        f"/api/attempts/{attempt_id}/submit", headers=auth(student_token, "browser-session-a")
    )
    assert submitted.status_code == 200
    with SessionLocal() as db:
        revisions = db.scalars(select(ResponseRevision).where(
            ResponseRevision.attempt_id == attempt_id
        ).order_by(ResponseRevision.sequence_number)).all()
        assert len(revisions) == 2
        assert revisions[1].previous_revision_id == revisions[0].id
        assert revisions[0].content_hash != revisions[1].content_hash
        assert revisions[1].client_metadata["offline_replay"] is True
        submission = db.scalar(select(AttemptSubmission).where(
            AttemptSubmission.attempt_id == attempt_id
        ))
        assert submission.submission_kind == "manual"
        assert submission.response_manifest[0]["revision_id"] == revisions[1].id
        original_manifest = list(submission.response_manifest)
        response = db.scalar(select(Response).where(Response.attempt_id == attempt_id))
        response.answer = {"selected_index": 0}
        db.commit()
        assert db.get(AttemptSubmission, submission.id).response_manifest == original_manifest


def test_duplicate_live_tab_is_rejected_but_stale_lease_can_be_recovered(client, student_token):
    exam_id, _ = seed_recovery_exam()
    first = client.post(
        f"/api/exams/{exam_id}/start", headers=auth(student_token, "browser-session-a")
    )
    assert first.status_code == 200
    blocked = client.post(
        f"/api/exams/{exam_id}/start", headers=auth(student_token, "browser-session-b")
    )
    assert blocked.status_code == 409
    assert "another browser tab" in blocked.json()["detail"]
    with SessionLocal() as db:
        attempt = db.get(Attempt, first.json()["attempt_id"])
        attempt.client_lease_at = datetime.now(timezone.utc) - timedelta(seconds=91)
        db.commit()
    recovered = client.post(
        f"/api/exams/{exam_id}/start", headers=auth(student_token, "browser-session-b")
    )
    assert recovered.status_code == 200
    with SessionLocal() as db:
        assert db.get(Attempt, first.json()["attempt_id"]).active_client_session_id == "browser-session-b"


def test_expired_attempt_is_auto_submitted_with_manifest_before_retake(client, student_token):
    exam_id, question_id = seed_recovery_exam()
    with SessionLocal() as db:
        student = db.scalar(select(User).where(User.email == "s@example.com"))
        attempt = Attempt(
            exam_id=exam_id, user_id=student.id, status="in_progress",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            deadline_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.add(attempt)
        db.flush()
        response = Response(
            attempt_id=attempt.id, question_id=question_id,
            answer={"selected_index": 0}, confidence=4, sequence_number=1,
            time_spent_seconds=20, idempotency_key="legacy-before-revision",
        )
        db.add(response)
        db.commit()
        attempt_id = attempt.id
    expired = client.post(
        f"/api/exams/{exam_id}/start", headers=auth(student_token, "browser-session-a")
    )
    assert expired.status_code == 409
    assert "submitted automatically" in expired.json()["detail"]
    with SessionLocal() as db:
        attempt = db.get(Attempt, attempt_id)
        submission = db.scalar(select(AttemptSubmission).where(
            AttemptSubmission.attempt_id == attempt_id
        ))
        assert attempt.submitted_at is not None
        assert submission.submission_kind == "deadline_expired"
        assert submission.response_manifest[0]["revision_id"] is None
