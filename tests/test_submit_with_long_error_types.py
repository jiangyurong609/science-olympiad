"""A wrong answer must never make an exam unsubmittable.

`distractor_error_types` is model-authored, and the difficulty-calibrated prompt asks for a
specific misconception per choice — so the entries are sentences, not slugs. They land in
RemediationCase.error_type, a varchar(64). In production 2,993 values exceed that and 42
published exams hold at least one, so a student who missed such a question got a 500 on submit
and could never hand the paper in. The label is clipped; the sentence survives in the
diagnostic JSON.
"""
from app.core.database import SessionLocal
from app.models.entities import Attempt, Event, Exam, ExamItem, Question, RemediationCase
from app.services.scoring import ERROR_TYPE_MAX, error_type_label

LONG = ("treating confirmation of the illness as sufficient information for risk-factor "
        "inspection when the investigation still needs exposure timing")


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_label_is_clipped_but_still_readable():
    label = error_type_label(LONG)
    assert len(label) <= ERROR_TYPE_MAX
    assert label.startswith("treating confirmation")
    assert not label.endswith(" …"), "clip at a word, not mid-space"
    assert error_type_label(None) == "unknown"
    assert error_type_label("blank") == "blank", "short labels pass through untouched"


def test_exam_with_sentence_length_misconceptions_can_be_submitted(client, student_token):
    with SessionLocal() as db:
        event = Event(slug="submit-long", name="Submit Long", division="B", season=2026)
        db.add(event)
        db.flush()
        question = Question(
            event_id=event.id, status="published", stem="Which conclusion holds?",
            question_type="single_choice", choices=["A", "B", "C", "D"],
            answer_spec={"correct_index": 0, "points": 1,
                         "distractor_error_types": {"1": LONG, "2": LONG, "3": LONG}},
        )
        db.add(question)
        db.flush()
        exam = Exam(event_id=event.id, title="Long Labels", published=True,
                    disposition="machine_practice")
        db.add(exam)
        db.flush()
        db.add(ExamItem(exam_id=exam.id, question_id=question.id, position=1,
                        snapshot={"stem": question.stem, "choices": question.choices,
                                  "answer_spec": question.answer_spec,
                                  "question_type": "single_choice"}))
        db.commit()
        exam_id, question_id = exam.id, question.id

    start = client.post(f"/api/exams/{exam_id}/start", headers=_auth(student_token))
    assert start.status_code == 200, start.text
    attempt_id = start.json()["attempt_id"]

    # answer wrongly — this is what opens a remediation case
    saved = client.put(f"/api/attempts/{attempt_id}/responses", headers=_auth(student_token),
                       json={"question_id": question_id, "answer": {"selected_index": 1},
                             "sequence_number": 1, "idempotency_key": f"attempt-{attempt_id}-question-{question_id}-seq1"})
    assert saved.status_code == 200, saved.text

    submitted = client.post(f"/api/attempts/{attempt_id}/submit", headers=_auth(student_token))
    assert submitted.status_code == 200, f"submit failed: {submitted.status_code} {submitted.text}"

    with SessionLocal() as db:
        case = db.query(RemediationCase).filter(
            RemediationCase.attempt_id == attempt_id).one()
        assert len(case.error_type) <= ERROR_TYPE_MAX
        assert case.diagnosis["evidence"]["error_type"] == LONG, \
            "the full misconception must survive in the diagnostic JSON"
        assert db.get(Attempt, attempt_id).submitted_at is not None
