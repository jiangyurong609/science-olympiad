"""The review queue distinguishes blocked items from ones already serving students.

"Pending review" spans two different situations: a question nobody can see until a human
decides, and one already live in a published exam under a labelled practice disposition,
where review is a promotion. The queue once held 996 items of which 490 were the second
kind; summed into one number, the backlog read as uniformly urgent and could not be
triaged. Each row therefore says which kind it is.
"""
from app.core.database import SessionLocal
from app.models.entities import Event, Exam, ExamItem, Question


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _question(event_id, stem):
    return Question(
        event_id=event_id, status="machine_validated", stem=stem,
        choices=["A", "B", "C", "D"], answer_spec={"correct_index": 0},
        validation_report={"passed": True},
    )


def test_queue_rows_say_whether_a_published_exam_already_serves_them(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="serving-flag", name="Serving Flag", division="B", season=2026)
        db.add(event)
        db.flush()
        served = _question(event.id, "Which is served to students?")
        dark = _question(event.id, "Which is dark until reviewed?")
        db.add_all([served, dark])
        db.flush()
        exam = Exam(event_id=event.id, title="Labelled Practice", published=True,
                    disposition="machine_practice")
        db.add(exam)
        db.flush()
        db.add(ExamItem(exam_id=exam.id, question_id=served.id, position=1))
        db.commit()
        event_id, served_id, dark_id = event.id, served.id, dark.id

    rows = client.get(f"/api/content/questions/review-queue?event_id={event_id}",
                      headers=_auth(admin_token)).json()
    by_id = {row["id"]: row for row in rows}
    assert by_id[served_id]["in_published_exam"] is True
    assert by_id[dark_id]["in_published_exam"] is False


def test_an_unpublished_exam_does_not_count_as_serving(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="draft-exam-flag", name="Draft Exam Flag", division="B", season=2026)
        db.add(event)
        db.flush()
        question = _question(event.id, "In a draft exam only.")
        db.add(question)
        db.flush()
        exam = Exam(event_id=event.id, title="Draft", published=False)
        db.add(exam)
        db.flush()
        db.add(ExamItem(exam_id=exam.id, question_id=question.id, position=1))
        db.commit()
        event_id, question_id = event.id, question.id

    rows = client.get(f"/api/content/questions/review-queue?event_id={event_id}",
                      headers=_auth(admin_token)).json()
    row = next(r for r in rows if r["id"] == question_id)
    assert row["in_published_exam"] is False, "a draft exam serves nobody"
