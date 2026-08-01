"""The gate verifier must fail when a gate actually regresses.

A verifier that always passes is worse than none — it converts an unchecked assumption into a
reported guarantee. These tests break each guarantee in turn and require the corresponding
check to notice.
"""
from __future__ import annotations

import itertools

from app.core.database import SessionLocal
from app.models.entities import Event, Exam, Lesson, LessonVersion, Question
from scripts.verify_phases import phase_0, phase_7

_UNIQUE = itertools.count(1)


def _names(checks):
    return {c.name: c for c in checks}


def test_an_exam_without_a_disposition_fails_the_gate():
    with SessionLocal() as db:
        event = Event(slug=f"vp-ev-{next(_UNIQUE)}", name="E", division="B", season=2026)
        db.add(event); db.flush()
        db.add(Exam(event_id=event.id, title="Undecided", duration_minutes=30,
                    question_ids=[], published=False))
        db.flush()
        checks = _names(phase_0(db))
    assert checks["every exam has an explicit disposition"].ok is False


def test_a_published_exam_of_unreviewed_items_fails_the_gate():
    with SessionLocal() as db:
        event = Event(slug=f"vp-unrev-{next(_UNIQUE)}", name="E", division="B", season=2026)
        db.add(event); db.flush()
        item = Question(event_id=event.id, stem="Unreviewed", question_type="single_choice",
                        choices=["a", "b"], answer_spec={"correct_index": 0},
                        status="machine_validated")
        db.add(item); db.flush()
        db.add(Exam(event_id=event.id, title="Bad", duration_minutes=30,
                    question_ids=[item.id], published=True, disposition="reviewed"))
        db.flush()
        checks = _names(phase_0(db))
    assert checks["no new attempt on an exam holding unreviewed items"].ok is False


def test_the_gate_notices_when_the_visibility_rule_itself_regresses(monkeypatch):
    """The regression this verifier exists for.

    A lesson cannot be put into the exposed state directly any more — the rule now refuses it,
    which is the fix working. What must still be true is that if the *rule* regresses, this
    gate reports it rather than trusting it. So the rule is made permissive here, exactly as
    the `student_preview` bypass made it permissive, and the gate must fail.
    """
    import scripts.verify_phases as vp

    with SessionLocal() as db:
        event = Event(slug=f"vp-les-{next(_UNIQUE)}", name="E", division="B", season=2026)
        db.add(event); db.flush()
        lesson = Lesson(event_id=event.id, slug=f"vp-l-{next(_UNIQUE)}", title="Exposed",
                        status="published", current_version=1,
                        disposition="pending_disposition")
        db.add(lesson); db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1, content=[]))
        db.flush()

        # with the real rule, nothing is exposed and the gate holds
        assert _names(phase_0(db))["no unreviewed lesson is student-visible"].ok is True

        monkeypatch.setattr(vp.sv, "lesson_is_student_visible",
                            lambda db, user, lesson, version=None: True)
        checks = _names(phase_0(db))
    assert checks["no unreviewed lesson is student-visible"].ok is False, \
        "a permissive visibility rule must be caught, not trusted"


def test_grandfathered_content_is_exempt_by_design():
    """`unreviewed_practice` is an explicit human decision to keep legacy content readable
    and labelled. The gate must not report it as a regression."""
    with SessionLocal() as db:
        event = Event(slug=f"vp-gf-{next(_UNIQUE)}", name="E", division="B", season=2026)
        db.add(event); db.flush()
        lesson = Lesson(event_id=event.id, slug=f"vp-gf-l-{next(_UNIQUE)}", title="Legacy",
                        status="published", current_version=1,
                        disposition="unreviewed_practice")
        db.add(lesson); db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1, content=[]))
        db.flush()
        checks = _names(phase_0(db))
    assert checks["no unreviewed lesson is student-visible"].ok is True


def test_an_ambiguous_figure_on_a_served_item_fails_the_gate():
    with SessionLocal() as db:
        event = Event(slug=f"vp-fig-{next(_UNIQUE)}", name="E", division="B", season=2026)
        db.add(event); db.flush()
        db.add(Question(
            event_id=event.id, stem="Which mineral is in the figure?",
            question_type="single_choice", choices=["a", "b"],
            answer_spec={"correct_index": 0}, status="draft",
            assets=[{"kind": "figure", "storage_key": "k"}],
            generation_provenance={"import_kind": "past_test", "figure_match": "ambiguous"}))
        db.flush()
        checks = _names(phase_7(db))
    assert checks["no ambiguous figure reaches a served item"].ok is False


def test_a_clean_database_passes_every_phase_0_gate():
    with SessionLocal() as db:
        checks = phase_0(db)
    assert all(c.ok for c in checks), [c.name for c in checks if not c.ok]
