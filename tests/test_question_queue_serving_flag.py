"""The review queue distinguishes blocked items from ones already serving students.

"Pending review" spans two different situations: a question nobody can see until a human
decides, and one already live under a labelled practice disposition, where review is a
promotion. The queue once held 996 items of which 649 were the second kind; summed into
one number, the backlog read as uniformly urgent and could not be triaged.

Serving has two paths — published exams and published skill labs. The flag once checked
only exams, which marked 159 lab-serving questions as dark and nearly got them withdrawn
as unreferenced surplus; the lab case below pins the second path.
"""
from app.core.database import SessionLocal
from app.models.entities import Event, Exam, ExamItem, PracticeSet, PracticeSetVersion, Question


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _question(event_id, stem):
    return Question(
        event_id=event_id, status="machine_validated", stem=stem,
        choices=["A", "B", "C", "D"], answer_spec={"correct_index": 0},
        validation_report={"passed": True},
    )


def test_queue_rows_say_whether_students_are_already_served(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="serving-flag", name="Serving Flag", division="B", season=2026)
        db.add(event)
        db.flush()
        in_exam = _question(event.id, "Which is served through a published exam?")
        in_lab = _question(event.id, "Which is served through a published skill lab?")
        dark = _question(event.id, "Which is dark until reviewed?")
        db.add_all([in_exam, in_lab, dark])
        db.flush()
        exam = Exam(event_id=event.id, title="Labelled Practice", published=True,
                    disposition="machine_practice")
        db.add(exam)
        db.flush()
        db.add(ExamItem(exam_id=exam.id, question_id=in_exam.id, position=1))
        lab = PracticeSet(event_id=event.id, slug="serving-lab", title="Serving Lab", status="published")
        db.add(lab)
        db.flush()
        db.add(PracticeSetVersion(practice_set_id=lab.id, version=1, items=[
            {"question_id": in_lab.id, "prompt": in_lab.stem},
        ]))
        db.commit()
        event_id = event.id
        expected = {in_exam.id: True, in_lab.id: True, dark.id: False}

    rows = client.get(f"/api/content/questions/review-queue?event_id={event_id}",
                      headers=_auth(admin_token)).json()
    by_id = {row["id"]: row["serving_students"] for row in rows}
    assert by_id == expected


def test_unpublished_exams_and_labs_do_not_count_as_serving(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="draft-serving", name="Draft Serving", division="B", season=2026)
        db.add(event)
        db.flush()
        in_draft_exam = _question(event.id, "In a draft exam only.")
        in_draft_lab = _question(event.id, "In a draft lab only.")
        db.add_all([in_draft_exam, in_draft_lab])
        db.flush()
        exam = Exam(event_id=event.id, title="Draft", published=False)
        db.add(exam)
        db.flush()
        db.add(ExamItem(exam_id=exam.id, question_id=in_draft_exam.id, position=1))
        lab = PracticeSet(event_id=event.id, slug="draft-lab", title="Draft Lab", status="draft")
        db.add(lab)
        db.flush()
        db.add(PracticeSetVersion(practice_set_id=lab.id, version=1, items=[
            {"question_id": in_draft_lab.id, "prompt": in_draft_lab.stem},
        ]))
        db.commit()
        event_id = event.id
        ids = {in_draft_exam.id, in_draft_lab.id}

    rows = client.get(f"/api/content/questions/review-queue?event_id={event_id}",
                      headers=_auth(admin_token)).json()
    assert all(row["serving_students"] is False for row in rows if row["id"] in ids), \
        "a draft exam or draft lab serves nobody"
