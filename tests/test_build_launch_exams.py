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
                citations=[{"title": "USGS", "url": "https://usgs.gov/x"}],
                validation_report={
                    "passed": True,
                    "independent_solver": {"verdict": "solver_agrees"},
                    "independent_verifier": {"passed": True, "errors": []},
                    "factual_grounding": "approved_claims"},
                generation_provenance={"generation_run": "launch-test"}))
        for i in range(imported):
            db.add(Question(
                event_id=event.id, concept_id=concept.id,
                status=QuestionStatus.MACHINE_VALIDATED.value,
                stem=f"Imported past-test question {i}", choices=["A", "B", "C", "D"],
                answer_spec={"correct_index": 0},
                citations=[{"title": "past test"}],
                validation_report={
                    "passed": True,
                    "independent_solver": {"verdict": "solver_agrees"},
                    "independent_verifier": {"passed": True, "errors": []},
                    "factual_grounding": "approved_claims"},
                generation_provenance={"import_kind": "past_test", "section": "Station 3"}))
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


def _item(**over):
    from app.models.entities import Question, QuestionStatus
    base = dict(
        event_id=1, stem="q", choices=["A", "B"], answer_spec={"correct_index": 0},
        status=QuestionStatus.MACHINE_VALIDATED.value,
        citations=[{"title": "USGS"}],
        validation_report={"passed": True,
                           "independent_solver": {"verdict": "solver_agrees"},
                           "independent_verifier": {"passed": True, "errors": []},
                           "factual_grounding": "approved_claims"},
        generation_provenance={"generation_run": "launch-test"})
    base.update(over)
    return Question(**base)


def test_each_gate_is_required_on_its_own_terms():
    """The first version checked `passed` plus a solver flag and called it "every gate".

    An item can carry passed=true beside an absent or failed verifier, because
    validation_report is an untyped blob several paths write. Each component is asserted
    separately here so a future weakening fails a test rather than inflating a count.
    """
    from scripts.build_launch_exams import item_clears_every_gate as gate

    assert gate(_item()) is True

    report = lambda **o: {**{"passed": True,
                            "independent_solver": {"verdict": "solver_agrees"},
                            "independent_verifier": {"passed": True, "errors": []},
                            "factual_grounding": "approved_claims"}, **o}

    assert gate(_item(validation_report=report(independent_verifier=None))) is False, \
        "never verified is not verified clean"
    assert gate(_item(validation_report=report(
        independent_verifier={"passed": False, "errors": ["wrong"]}))) is False
    assert gate(_item(validation_report=report(
        independent_verifier={"passed": True, "errors": ["still wrong"]}))) is False
    assert gate(_item(validation_report=report(factual_grounding="none"))) is False
    assert gate(_item(validation_report=report(independent_solver={"verdict": "disagrees"}))) is False
    assert gate(_item(validation_report=report(passed=False))) is False
    assert gate(_item(citations=[])) is False
    assert gate(_item(status="draft")) is False
    assert gate(_item(generation_provenance={"import_kind": "past_test"})) is False


def test_the_persisted_blueprint_carries_no_text_from_a_past_test():
    """`top_sections` holds raw section headings lifted from imported items."""
    from sqlalchemy import select as _select
    from app.models.entities import Exam as _Exam, Event as _Event

    _, slug = seed(slug="exam-blueprint")
    build(slug, size=30, apply=True)
    with SessionLocal() as db:
        event = db.scalar(_select(_Event).where(_Event.slug == slug))
        exam = db.scalar(_select(_Exam).where(_Exam.event_id == event.id))
        assert "top_sections" not in (exam.blueprint or {})
        blob = str(exam.blueprint)
        assert "Station 3" not in blob, "past-test section text reached the exam record"


def test_rebuilding_an_exam_clears_its_snapshots_and_unpublishes_it():
    """Replacing question_ids alone left the served snapshots — and publication — in place."""
    from sqlalchemy import select as _select
    from app.models.entities import Exam as _Exam, ExamItem as _ExamItem, Event as _Event

    _, slug = seed(slug="exam-rebuild")
    build(slug, size=30, apply=True)
    with SessionLocal() as db:
        event = db.scalar(_select(_Event).where(_Event.slug == slug))
        exam = db.scalar(_select(_Exam).where(_Exam.event_id == event.id))
        exam.published = True
        exam.disposition = "reviewed"
        db.add(_ExamItem(exam_id=exam.id, question_id=999, position=900,
                         question_version=1, snapshot={"stem": "old past-test text"}))
        db.commit()
        exam_id = exam.id

    build(slug, size=30, apply=True)
    with SessionLocal() as db:
        exam = db.get(_Exam, exam_id)
        assert exam.published is False, "a rebuilt exam must not stay published"
        assert exam.disposition == "pending_disposition"
        rows = db.scalars(_select(_ExamItem).where(_ExamItem.exam_id == exam_id)).all()
        assert all(r.question_id != 999 for r in rows), (
            "the stale snapshot would keep serving the old item")
        assert rows, "a rebuilt exam must still have snapshots to serve"
