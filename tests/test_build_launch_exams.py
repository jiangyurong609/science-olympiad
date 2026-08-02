"""A practice exam may be *shaped* by a past test. It may not be *made of* one.

The platform holds 4,755 imported past-test items — Science Olympiad's question text. The
blueprint derived from them is structure, which is fact; the items themselves are expression,
which is theirs. This is the one place those two could get confused, so it is pinned here.
"""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Concept, Event, Exam, Question, QuestionStatus
from scripts.build_launch_exams import _our_items, _past_test_pool, build


def seed(slug="exam-event", ours=14, imported=12):
    with SessionLocal() as db:
        event = Event(slug=slug, name="Exam Event", division="B", season=2026)
        db.add(event); db.flush()
        concept = Concept(event_id=event.id, name="Topic", description="x")
        db.add(concept); db.flush()
        for i in range(ours):
            db.add(Question(
                event_id=event.id, concept_id=concept.id,
                status=QuestionStatus.MACHINE_VALIDATED.value,
                stem=f"Our question {i}", choices=["A", "B", "C", "D"],
                answer_spec={"correct_index": 1},
                validation_report={"passed": True,
                                   "independent_solver": {"verdict": "solver_agrees"}},
                generation_provenance={"generation_run": "launch-test"}))
        for i in range(imported):
            db.add(Question(
                event_id=event.id, concept_id=concept.id,
                status=QuestionStatus.MACHINE_VALIDATED.value,
                stem=f"Imported past-test question {i}", choices=["A", "B", "C", "D"],
                answer_spec={"correct_index": 0},
                validation_report={"passed": True,
                                   "independent_solver": {"verdict": "solver_agrees"}},
                generation_provenance={"import_kind": "past_test"}))
        db.commit()
        return event.id, slug


def test_no_imported_past_test_item_can_enter_an_exam():
    """The constraint the whole script exists to honour."""
    event_id, slug = seed()
    result = build(slug, size=30, apply=True)
    assert "exam of" in result["outcome"]
    with SessionLocal() as db:
        exam = db.scalar(select(Exam).where(Exam.event_id == event_id))
        chosen = db.scalars(select(Question).where(Question.id.in_(exam.question_ids))).all()
        assert chosen, "the exam must actually hold items"
        for question in chosen:
            provenance = question.generation_provenance or {}
            assert provenance.get("import_kind") != "past_test", (
                f"imported past-test item {question.id} reached a published exam"
            )


def test_the_past_test_pool_is_still_read_for_its_shape():
    """Excluding their text must not mean ignoring their structure."""
    _, slug = seed(slug="exam-shape")
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == slug))
        assert len(_past_test_pool(db, event)) == 12
        assert len(_our_items(db, event)) == 14


def test_an_exam_is_never_created_already_servable():
    """Phase 0 decides serving; this script must not pre-empt it."""
    event_id, slug = seed(slug="exam-unpublished")
    build(slug, size=30, apply=True)
    with SessionLocal() as db:
        exam = db.scalar(select(Exam).where(Exam.event_id == event_id))
        assert exam.published is False
        allowed, _ = __import__(
            "app.services.student_visibility", fromlist=["x"]).can_start_new_attempt(db, exam)
        assert allowed is False


def test_too_few_of_our_own_items_refuses_rather_than_padding():
    """The failure mode is topping up a thin pool with imported items."""
    _, slug = seed(slug="exam-thin", ours=3, imported=40)
    result = build(slug, size=30, apply=True)
    assert "need 10" in result["outcome"]
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == slug))
        assert db.scalar(select(Exam).where(Exam.event_id == event.id)) is None


def test_an_ungated_item_of_ours_is_not_exam_material():
    """Passing the solver is the bar; being ours is not enough."""
    _, slug = seed(slug="exam-ungated", ours=0, imported=0)
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == slug))
        for i in range(12):
            db.add(Question(event_id=event.id, stem=f"ungated {i}",
                            choices=["A", "B"], answer_spec={"correct_index": 0},
                            status=QuestionStatus.DRAFT.value,
                            validation_report={"passed": False},
                            generation_provenance={"generation_run": "x"}))
        db.commit()
        assert _our_items(db, event) == []
