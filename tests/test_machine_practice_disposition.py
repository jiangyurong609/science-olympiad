"""Machine-gated practice is servable, and must never be mistaken for reviewed content.

This is the one disposition that lets a student be scored on material no human has read, so
the two things that keep it honest are asserted here: it is *earned* by measurement rather than
set as a flag, and everything that labels unreviewed content labels it too.
"""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Concept, Event, Exam, ExamItem, Question, QuestionStatus
from app.services import student_visibility as sv


def _gated_report():
    return {"passed": True,
            "independent_solver": {"verdict": "solver_agrees"},
            "independent_verifier": {"passed": True, "errors": []},
            "factual_grounding": "approved_claims"}


def seed_exam(*, all_gated=True, slug="mp-event"):
    with SessionLocal() as db:
        event = Event(slug=slug, name="MP", division="B", season=2026)
        db.add(event); db.flush()
        concept = Concept(event_id=event.id, name="T", description="x")
        db.add(concept); db.flush()
        items = []
        for i in range(4):
            report = _gated_report()
            if not all_gated and i == 0:
                report["independent_verifier"] = {"passed": False, "errors": ["unsupported"]}
            question = Question(
                event_id=event.id, concept_id=concept.id,
                status=QuestionStatus.MACHINE_VALIDATED.value,
                stem=f"q{i}", choices=["A", "B"], answer_spec={"correct_index": 1},
                citations=[{"title": "USGS"}], validation_report=report,
                generation_provenance={"generation_run": "launch-x"})
            db.add(question); items.append(question)
        db.flush()
        exam = Exam(event_id=event.id, title="Practice Test — MP",
                    question_ids=[q.id for q in items], published=True,
                    disposition=sv.DISPOSITION_PENDING, duration_minutes=20)
        db.add(exam); db.flush()
        for position, question in enumerate(items):
            db.add(ExamItem(exam_id=exam.id, question_id=question.id,
                            question_version=question.version, position=position,
                            snapshot={"stem": question.stem}))
        db.commit()
        return exam.id


def test_an_exam_earns_machine_practice_by_measurement():
    exam_id = seed_exam()
    with SessionLocal() as db:
        exam = db.get(Exam, exam_id)
        assert sv.classify_exam(db, exam) == sv.DISPOSITION_MACHINE_PRACTICE
        allowed, _ = sv.can_start_new_attempt(db, exam)
        assert allowed is True, "machine-gated practice is servable"


def test_one_item_short_of_the_gates_sinks_the_whole_exam():
    """The class is earned per exam, not per item — a single failure refuses all of it."""
    exam_id = seed_exam(all_gated=False, slug="mp-partial")
    with SessionLocal() as db:
        exam = db.get(Exam, exam_id)
        assert sv.classify_exam(db, exam) == sv.DISPOSITION_UNREVIEWED_PRACTICE
        allowed, why = sv.can_start_new_attempt(db, exam)
        assert allowed is False
        assert "not been reviewed" in why


def test_setting_the_disposition_by_hand_does_not_survive_classification():
    """The flag is a record of a measurement, never a substitute for one."""
    exam_id = seed_exam(all_gated=False, slug="mp-forged")
    with SessionLocal() as db:
        exam = db.get(Exam, exam_id)
        exam.disposition = sv.DISPOSITION_MACHINE_PRACTICE
        db.commit()
        # can_start_new_attempt honours an explicit disposition, so the guarantee lives in
        # classify_exam — which is what the publish path must use. Assert it refuses.
        assert sv.classify_exam(db, exam) == sv.DISPOSITION_UNREVIEWED_PRACTICE


def test_machine_practice_is_always_labelled_as_unreviewed():
    """Every surface that labels unreviewed content must label this too."""
    exam_id = seed_exam(slug="mp-label")
    with SessionLocal() as db:
        exam = db.get(Exam, exam_id)
        exam.disposition = sv.DISPOSITION_MACHINE_PRACTICE
        db.commit()
        assert sv.is_unreviewed_practice(exam) is True, (
            "if this ever reads False, students are told machine output is verified"
        )


def test_an_unknown_release_class_never_claims_to_be_reviewed():
    """The default label used to be "Reviewed Practice" — the strongest claim available."""
    from app.api.routes import RELEASE_LABELS, UNKNOWN_RELEASE_LABEL

    assert "review" not in UNKNOWN_RELEASE_LABEL.lower() or \
        UNKNOWN_RELEASE_LABEL.lower().startswith("unreview")
    assert RELEASE_LABELS["machine_practice"] == "AI Practice · Not Expert Reviewed"
