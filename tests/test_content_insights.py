"""The insights endpoint reports real student activity per subject — and only that.

Staff walk the student app constantly for verification; counting those probes as
participation would invent an audience and hide the difference between a subject nobody
uses and one the team happens to test against. The teacher view exists to answer "who is
learning what, and where does it hurt", so its numbers must survive that scrutiny.
"""
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.entities import (
    Attempt, Event, Lesson, LessonProgress, Question, Response, User,
)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _row(payload, event_id):
    return next((r for r in payload["events"] if r["event"]["id"] == event_id), None)


def test_student_activity_counts_and_staff_probes_do_not(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="insights-event", name="Insights Event", division="B", season=2026)
        db.add(event)
        db.flush()
        lesson = Lesson(event_id=event.id, slug="insights-lesson", title="Insights Lesson",
                        status="published", current_version=1)
        db.add(lesson)
        student = User(email="insights-student@example.com", full_name="Insights Student",
                       role="student", division="B", is_active=True)
        staff = User(email="insights-staff@example.com", full_name="Insights Staff",
                     role="editor", is_active=True)
        db.add_all([student, staff])
        db.flush()
        db.add(LessonProgress(user_id=student.id, lesson_id=lesson.id, lesson_version=1,
                              status="completed"))
        # the staff probe: same shape of activity, different role
        db.add(LessonProgress(user_id=staff.id, lesson_id=lesson.id, lesson_version=1,
                              status="completed"))
        db.commit()
        event_id = event.id

    payload = client.get("/api/content/insights", headers=_auth(admin_token)).json()
    row = _row(payload, event_id)
    assert row is not None
    assert row["participation"]["students"] == 1, "the staff probe was counted as a student"
    assert row["lessons"]["completions"] == 1
    assert row["published"]["lessons"] == 1


def test_scores_and_correct_rate_come_from_graded_student_responses(client, admin_token):
    from app.models.entities import Exam, ExamItem
    with SessionLocal() as db:
        event = Event(slug="insights-scores", name="Insights Scores", division="B", season=2026)
        db.add(event)
        db.flush()
        question = Question(event_id=event.id, status="published", stem="Q",
                            choices=["A", "B", "C", "D"], answer_spec={"correct_index": 0})
        db.add(question)
        student = User(email="insights-scorer@example.com", full_name="Scorer",
                       role="student", division="B", is_active=True)
        db.add(student)
        db.flush()
        exam = Exam(event_id=event.id, title="Scored", published=True,
                    disposition="machine_practice")
        db.add(exam)
        db.flush()
        db.add(ExamItem(exam_id=exam.id, question_id=question.id, position=1))
        attempt = Attempt(exam_id=exam.id, user_id=student.id, status="submitted",
                          score=3, max_score=4,
                          started_at=datetime.now(timezone.utc),
                          submitted_at=datetime.now(timezone.utc))
        db.add(attempt)
        db.flush()
        db.add(Response(attempt_id=attempt.id, question_id=question.id,
                        answer={"choice": 0}, is_correct=True))
        db.commit()
        event_id = event.id

    payload = client.get("/api/content/insights", headers=_auth(admin_token)).json()
    row = _row(payload, event_id)
    assert row["exams"]["attempts"] == 1
    assert row["exams"]["submitted"] == 1
    assert row["exams"]["avg_score_pct"] == 75.0
    assert row["responses"] == {"graded": 1, "correct_pct": 100.0}
    assert "insufficient_response_data" in row["flags"], \
        "one answer must not be presented as difficulty evidence"


def test_recall_heavy_catalogs_are_flagged(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="insights-recall", name="Insights Recall", division="B", season=2026)
        db.add(event)
        db.flush()
        for i in range(20):
            db.add(Question(
                event_id=event.id, status="machine_validated", stem=f"Recall {i}",
                choices=["A", "B", "C", "D"], answer_spec={"correct_index": 0},
                cognitive_level="recall" if i < 12 else "application",
            ))
        db.commit()
        event_id = event.id

    payload = client.get("/api/content/insights", headers=_auth(admin_token)).json()
    row = _row(payload, event_id)
    assert row["questions"]["total"] == 20
    assert row["questions"]["recall_share"] == 0.6
    assert "recall_heavy" in row["flags"]


def test_students_cannot_read_the_teacher_view(client, student_token):
    assert client.get("/api/content/insights", headers=_auth(student_token)).status_code == 403
