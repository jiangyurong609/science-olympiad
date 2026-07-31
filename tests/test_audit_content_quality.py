"""Phase 0 — tests for the item-level content quality auditor."""
from __future__ import annotations

from app.core.database import SessionLocal
from app.models.entities import Event, Exam, Question
from scripts.audit_content_quality import run


def _event(db, slug="astronomy-c", season=2026):
    e = Event(slug=slug, name="Astronomy", division="C", season=season)
    db.add(e)
    db.flush()
    return e


def _question(db, event_id, *, stem, choices=None, answer_spec=None, correct_index=0,
              question_type="single_choice", status="published", grounded=False,
              marker=None, run_id=None):
    prov = {}
    if marker:
        prov["marker"] = marker
    if run_id:
        prov["generation_run"] = run_id
    if answer_spec is None:
        answer_spec = {"correct_index": correct_index}
    q = Question(
        event_id=event_id, question_type=question_type,
        stem=stem, choices=choices if choices is not None else [],
        answer_spec=answer_spec,
        status=status,
        validation_report={"factual_grounding": "approved_claims"} if grounded else {},
        generation_provenance=prov,
    )
    db.add(q)
    db.flush()
    return q


def test_type_aware_structural_checks():
    with SessionLocal() as db:
        e = _event(db)
        # valid short_answer
        _question(db, e.id, question_type="short_answer",
                  stem="Name the order and family of a ladybird beetle specimen.",
                  answer_spec={"answer": "Coleoptera (Coccinellidae)",
                               "accepted": ["Coleoptera; Coccinellidae"]})
        # invalid short_answer (no answer, no accepted)
        _question(db, e.id, question_type="short_answer",
                  stem="Describe the phase boundary of the cardiac cycle here.",
                  answer_spec={"rubric": ""})
        # valid numeric
        _question(db, e.id, question_type="numeric",
                  stem="Compute the stroke volume in mL for the given data set.",
                  answer_spec={"answer": 70, "tolerance": 2})
        # invalid numeric (no tolerance)
        _question(db, e.id, question_type="numeric",
                  stem="Compute the cardiac output in L/min for the given data.",
                  answer_spec={"answer": 5})
        db.commit()

    r = run()
    # a short_answer with 0 choices must NOT be flagged for MCQ choice rules
    assert "four_meaningful_choices_required" not in r["error_histogram"]
    assert "invalid_correct_index" not in r["error_histogram"]
    assert r["totals"]["passing_structural"] == 2  # one valid SA + one valid numeric
    assert "missing_accepted_answers" in r["error_histogram"]
    assert "missing_or_invalid_tolerance" in r["error_histogram"]


def test_good_bad_ungrounded_and_duplicate_classification():
    with SessionLocal() as db:
        e = _event(db)
        # good, grounded
        _question(db, e.id, stem="Which planet has the most moons in our system?",
                  choices=["Saturn", "Earth", "Mars", "Venus"], grounded=True)
        # bad structural: short stem + duplicate choices + bad index
        _question(db, e.id, stem="short", choices=["A", "A", "B"], correct_index=9)
        # ungrounded (valid structure, no grounding)
        _question(db, e.id, stem="What is the primary gas in a red giant envelope layer?",
                  choices=["Hydrogen", "Helium", "Iron", "Neon"], grounded=False)
        # duplicate stems (self excluded → one cluster of two)
        dup = "The Hertzsprung Russell diagram plots luminosity against what quantity?"
        _question(db, e.id, stem=dup, choices=["Temperature", "Mass", "Age", "Radius"], grounded=True)
        _question(db, e.id, stem=dup, choices=["Temperature", "Mass", "Age", "Radius"], grounded=True)
        db.commit()

    r = run()
    t = r["totals"]
    assert r["census"]["unaudited"] == 0
    assert t["questions"] == 5
    # one structurally-bad question
    assert t["passing_structural"] == 4
    assert "stem_too_short" in r["error_histogram"]
    assert "invalid_correct_index" in r["error_histogram"]
    # exactly one duplicate cluster covering two questions
    assert t["near_dup_clusters"] == 1
    assert t["duplicate_questions"] == 2
    # three grounded (good + two dup), two not
    assert t["grounded"] == 3


def test_status_and_generation_run_filters():
    with SessionLocal() as db:
        e = _event(db)
        _question(db, e.id, stem="Draft item about stellar parallax measurement here.",
                  choices=["A1", "B1", "C1", "D1"], status="draft", run_id="run-42")
        _question(db, e.id, stem="Published item about stellar parallax basics here.",
                  choices=["A2", "B2", "C2", "D2"], status="published", run_id="run-99")
        db.commit()

    only_draft = run(status="draft")
    assert only_draft["totals"]["questions"] == 1
    assert only_draft["census"]["unaudited"] == 0

    only_run = run(generation_run="run-42")
    assert only_run["totals"]["questions"] == 1


def test_single_shot_provenance_and_exam_under_blueprint():
    with SessionLocal() as db:
        e = _event(db)
        _question(db, e.id, stem="Single-shot generated item about lunar maria here.",
                  choices=["A", "B", "C", "D"], marker="catalog-2026-generated")
        db.add(Exam(event_id=e.id, title="Astronomy Mock", question_ids=[1], blueprint={"total": 10}))
        db.commit()

    r = run()
    assert r["totals"]["single_shot_provenance"] == 1
    assert r["totals"]["exams_under_blueprint"] == 1
    assert r["exams_under_blueprint_detail"][0]["expected"] == 10
