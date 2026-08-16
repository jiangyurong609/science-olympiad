"""One subject, broken out into who is learning it and what it contains.

The subject table says where it hurts; this endpoint answers the question staff ask next —
who, and in which course or exam. It carries the same rule as the summary: a staff account
walking the student app is verification, not participation, so it must not appear as a student.
"""
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.entities import (
    Attempt, Event, Exam, ExamItem, Lesson, LessonProgress, Question, Response, User,
)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _subject(db):
    event = Event(slug="detail-event", name="Detail Event", division="B", season=2026)
    db.add(event)
    db.flush()
    lesson = Lesson(event_id=event.id, slug="detail-lesson", title="Detail Lesson",
                    status="published", current_version=1, sequence=1)
    draft = Lesson(event_id=event.id, slug="detail-draft", title="Draft Lesson",
                   status="draft", current_version=1, sequence=2)
    question = Question(event_id=event.id, status="published", stem="Q?",
                        choices=["A", "B"], answer_spec={"correct_index": 0, "points": 1})
    db.add_all([lesson, draft, question])
    db.flush()
    exam = Exam(event_id=event.id, title="Detail Exam", published=True,
                disposition="machine_practice")
    db.add(exam)
    db.flush()
    db.add(ExamItem(exam_id=exam.id, question_id=question.id, position=1))
    return event, lesson, exam, question


def test_detail_reports_students_courses_and_exams(client, admin_token):
    with SessionLocal() as db:
        event, lesson, exam, question = _subject(db)
        student = User(email="detail-student@example.com", full_name="Dana Detail",
                       role="student", division="B", is_active=True)
        staff = User(email="detail-staff@example.com", full_name="Staff Prober",
                     role="editor", is_active=True)
        db.add_all([student, staff])
        db.flush()
        db.add_all([
            LessonProgress(user_id=student.id, lesson_id=lesson.id, lesson_version=1,
                           status="completed"),
            # the staff probe: identical activity, different role
            LessonProgress(user_id=staff.id, lesson_id=lesson.id, lesson_version=1,
                           status="completed"),
        ])
        attempt = Attempt(exam_id=exam.id, user_id=student.id, status="remediation_open",
                          score=1, max_score=2,
                          started_at=datetime.now(timezone.utc),
                          submitted_at=datetime.now(timezone.utc))
        db.add(attempt)
        db.flush()
        db.add(Response(attempt_id=attempt.id, question_id=question.id,
                        answer={"selected_index": 0}, is_correct=True))
        db.commit()
        event_id = event.id

    payload = client.get(f"/api/content/insights/{event_id}", headers=_auth(admin_token)).json()

    assert [s["name"] for s in payload["students"]] == ["Dana Detail"], \
        "a staff walkthrough must not appear as a student"
    row = payload["students"][0]
    assert row["lessons_completed"] == 1
    assert row["attempts"] == 1
    assert row["avg_score_pct"] == 50.0
    assert row["correct_pct"] == 100.0
    assert row["last_active"] is not None

    # courses include unpublished ones, because staff need to see what is not out yet
    assert {l["title"]: l["status"] for l in payload["lessons"]} == {
        "Detail Lesson": "published", "Draft Lesson": "draft"}
    assert next(l for l in payload["lessons"] if l["title"] == "Detail Lesson")["completions"] == 1

    assert len(payload["exams"]) == 1
    got = payload["exams"][0]
    assert got["title"] == "Detail Exam" and got["published"] is True
    assert got["items"] == 1 and got["attempts"] == 1 and got["avg_score_pct"] == 50.0


def test_detail_is_staff_only_and_404s_for_a_missing_subject(client, admin_token, student_token):
    assert client.get("/api/content/insights/1", headers=_auth(student_token)).status_code == 403
    assert client.get("/api/content/insights/999999", headers=_auth(admin_token)).status_code == 404
