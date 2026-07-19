from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.entities import (
    Attempt, ContentChallengeEvent, Event, Exam, ExamItem, Question, RemediationCase,
    Response, ScoreCorrection, User,
)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def seed_completed_attempt(student_token_unused=None):
    with SessionLocal() as db:
        student = db.scalar(select(User).where(User.email == "s@example.com"))
        event = Event(slug="challenge-event", name="Challenge Event", division="B", season=2026)
        question = Question(
            event_id=0, status="published", stem="Which specimen has the corrected diagnostic property?",
            choices=["Specimen A", "Specimen B", "Specimen C", "Specimen D"],
            answer_spec={"correct_index": 0, "points": 1}, explanation="Original explanation.",
            validation_report={"passed": True},
        )
        db.add(event)
        db.flush()
        question.event_id = event.id
        db.add(question)
        db.flush()
        exam = Exam(event_id=event.id, title="Challenge Form", published=True, question_ids=[question.id])
        db.add(exam)
        db.flush()
        db.add(ExamItem(
            exam_id=exam.id, question_id=question.id, question_version=question.version, position=0,
            snapshot={
                "stem": question.stem, "choices": question.choices,
                "question_type": "single_choice", "answer_spec": question.answer_spec,
                "explanation": question.explanation,
            },
        ))
        attempt = Attempt(
            exam_id=exam.id, user_id=student.id, submitted_at=datetime.now(timezone.utc),
            score=0, max_score=1, status="remediation_open",
        )
        db.add(attempt)
        db.flush()
        response = Response(
            attempt_id=attempt.id, question_id=question.id, answer={"selected_index": 1},
            is_correct=False, points_awarded=0, diagnostic={"expected": 0, "selected": 1},
        )
        case = RemediationCase(
            attempt_id=attempt.id, user_id=student.id, question_id=question.id,
            source_type="exam", source_ref=f"exam:{attempt.id}:{question.id}",
            error_type="knowledge_or_reasoning", status="open", diagnosis={}, plan={},
        )
        editor = User(email="challenge-editor@example.com", full_name="Challenge Editor", role="editor")
        db.add_all([response, case, editor])
        db.commit()
        return {
            "attempt_id": attempt.id, "question_id": question.id, "exam_id": exam.id,
            "editor_token": create_access_token(str(editor.id)),
        }


def submit_challenge(client, student_token, seeded):
    response = client.post(
        f"/api/attempts/{seeded['attempt_id']}/challenges", headers=auth(student_token),
        json={
            "question_id": seeded["question_id"], "category": "wrong_key",
            "description": "The evidence in the station supports Specimen B, but the original key marks Specimen A.",
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_upheld_key_challenge_pauses_content_rescores_and_voids_false_remediation(
    client, admin_token, student_token,
):
    seeded = seed_completed_attempt()
    challenge_id = submit_challenge(client, student_token, seeded)
    duplicate = client.post(
        f"/api/attempts/{seeded['attempt_id']}/challenges", headers=auth(student_token),
        json={
            "question_id": seeded["question_id"], "category": "wrong_key",
            "description": "This second report should be rejected as a duplicate for the same attempt.",
        },
    )
    assert duplicate.status_code == 409

    triaged = client.post(
        f"/api/content/challenges/{challenge_id}/triage", headers=auth(seeded["editor_token"]),
        json={"severity": "critical", "notes": "Potential wrong key affects every completed attempt."},
    )
    assert triaged.status_code == 200
    with SessionLocal() as db:
        assert db.get(Question, seeded["question_id"]).status == "quarantined"
        assert db.get(Exam, seeded["exam_id"]).published is False

    resolved = client.post(
        f"/api/content/challenges/{challenge_id}/resolve", headers=auth(admin_token),
        json={
            "decision": "upheld", "correction_type": "correct_key",
            "corrected_answer_spec": {"correct_index": 1, "points": 1},
            "public_note": "The answer key was corrected to Specimen B after scientific review.",
            "internal_note": "Editor reproduced the issue against the station evidence and source snapshot.",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["impact"]["changed_scores"] == 1
    assert resolved.json()["impact"]["voided_remediation_cases"] == 1
    with SessionLocal() as db:
        attempt = db.get(Attempt, seeded["attempt_id"])
        response = db.scalar(select(Response).where(Response.attempt_id == attempt.id))
        case = db.scalar(select(RemediationCase).where(RemediationCase.attempt_id == attempt.id))
        correction = db.scalar(select(ScoreCorrection).where(ScoreCorrection.challenge_id == challenge_id))
        events = db.scalars(select(ContentChallengeEvent).where(
            ContentChallengeEvent.challenge_id == challenge_id
        ).order_by(ContentChallengeEvent.id)).all()
        assert (attempt.score, attempt.max_score) == (1, 1)
        assert response.is_correct is True and response.points_awarded == 1
        assert case.status == "void_content_correction"
        assert correction.old_score == 0 and correction.new_score == 1
        assert [event.event_type for event in events] == ["submitted", "triaged", "resolved"]
        assert db.get(Question, seeded["question_id"]).status == "withdrawn"

    mine = client.get("/api/me/challenges", headers=auth(student_token)).json()
    assert mine[0]["status"] == "upheld"
    assert "corrected" in mine[0]["public_note"]
    notifications = client.get("/api/notifications", headers=auth(student_token)).json()
    assert notifications["unread_count"] == 3
    assert {row["type"] for row in notifications["notifications"]} == {
        "challenge_triaged", "challenge_resolved", "score_correction",
    }


def test_not_upheld_challenge_restores_held_question_and_exam(client, admin_token, student_token):
    seeded = seed_completed_attempt()
    with SessionLocal() as db:
        active_student = User(
            email="active-during-challenge@example.com", full_name="Active Student",
            role="student", division="B",
        )
        db.add(active_student)
        db.flush()
        active_attempt = Attempt(
            exam_id=seeded["exam_id"], user_id=active_student.id, status="in_progress",
        )
        db.add(active_attempt)
        db.commit()
        active_attempt_id = active_attempt.id
        active_token = create_access_token(str(active_student.id))
    challenge_id = submit_challenge(client, student_token, seeded)
    assert client.post(
        f"/api/content/challenges/{challenge_id}/triage", headers=auth(seeded["editor_token"]),
        json={"severity": "high", "notes": "Pause while the cited station evidence is checked."},
    ).status_code == 200
    with SessionLocal() as db:
        assert db.get(Attempt, active_attempt_id).status == "content_hold"
    held = client.post(f"/api/exams/{seeded['exam_id']}/start", headers=auth(active_token))
    assert held.status_code == 409
    assert "responses are preserved" in held.json()["detail"]
    resolved = client.post(
        f"/api/content/challenges/{challenge_id}/resolve", headers=auth(admin_token),
        json={
            "decision": "not_upheld", "correction_type": "no_score_change",
            "public_note": "The original key was confirmed after reviewing the complete station evidence.",
            "internal_note": "Two independent reviewers reproduced the original answer from the snapshot.",
        },
    )
    assert resolved.status_code == 200
    with SessionLocal() as db:
        assert db.get(Question, seeded["question_id"]).status == "published"
        assert db.get(Exam, seeded["exam_id"]).published is True
        assert db.get(Attempt, active_attempt_id).status == "in_progress"
        assert db.scalar(select(ScoreCorrection)) is None
