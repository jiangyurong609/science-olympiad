"""The placement diagnostic must refuse rather than report a measurement it did not make.

Three rules carry it, and every one is a Phase 0 rule restated: only student-ready items, only
concepts a student can then act on, and no placement at all from too little evidence. The last
is the one most likely to be quietly relaxed later, so it is pinned hardest.
"""
import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, Lesson, LessonVersion, MasteryState, Question, QuestionStatus, User,
)
from app.services import placement


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def seed(*, concepts=3, items_per_concept=2, status=QuestionStatus.PUBLISHED.value,
         with_lessons=True, slug="placement-event"):
    with SessionLocal() as db:
        event = Event(slug=slug, name="Placement", division="B", season=2026)
        db.add(event); db.flush()
        for c in range(concepts):
            concept = Concept(event_id=event.id, name=f"Concept {c}", description="x")
            db.add(concept); db.flush()
            if with_lessons:
                lesson = Lesson(event_id=event.id, concept_id=concept.id, slug=f"l{c}",
                                title=f"Lesson {c}", status="published",
                                disposition="unreviewed_practice", current_version=1)
                db.add(lesson); db.flush()
                db.add(LessonVersion(lesson_id=lesson.id, version=1,
                                     review_status="sme_approved", claim_ids=[1],
                                     citations=[{"title": "Gov"}],
                                     content=[{"type": "opening", "heading": "Hi"}]))
            for i in range(items_per_concept):
                db.add(Question(event_id=event.id, concept_id=concept.id, status=status,
                                stem=f"Question {c}-{i}", choices=["A", "B"],
                                answer_spec={"correct_index": 1}))
        db.commit()
        return event.slug


def test_a_diagnostic_is_built_from_reviewed_items_only():
    slug = seed()
    with SessionLocal() as db:
        result = placement.build_diagnostic(db, slug)
    assert len(result["items"]) == 6
    assert result["concepts_placeable"] == 3


def test_draft_items_never_reach_a_diagnostic():
    """A diagnostic scores, so Phase 0's rule for scoreable content applies to it."""
    slug = seed(status=QuestionStatus.DRAFT.value, slug="placement-draft")
    with SessionLocal() as db:
        with pytest.raises(placement.PlacementError, match="reviewed item"):
            placement.build_diagnostic(db, slug)


def test_a_concept_with_no_visible_lesson_is_not_a_placement_target():
    """Placing a student somewhere they cannot then go is a dead end."""
    slug = seed(with_lessons=False, slug="placement-nolessons")
    with SessionLocal() as db:
        with pytest.raises(placement.PlacementError, match="placed into"):
            placement.build_diagnostic(db, slug)


def test_too_little_evidence_refuses_rather_than_placing():
    slug = seed(concepts=1, slug="placement-thin")
    with SessionLocal() as db:
        with pytest.raises(placement.PlacementError):
            placement.build_diagnostic(db, slug)


def test_a_placement_seeds_mastery_where_the_student_has_none(client, student_token):
    slug = seed(slug="placement-seed")
    built = client.get(f"/api/events/{slug}/placement", headers=auth(student_token))
    assert built.status_code == 200
    items = built.json()["items"]
    # answer every item correctly
    responses = {str(i["id"]): 1 for i in items}
    posted = client.post(f"/api/events/{slug}/placement", headers=auth(student_token),
                         json={"responses": responses})
    assert posted.status_code == 200
    assert posted.json()["concepts_seeded"] == 3
    with SessionLocal() as db:
        states = db.scalars(select(MasteryState)).all()
        assert states, "a placement must leave something behind"
        assert all(s.evidence_count == 0 for s in states), (
            "a diagnostic seeds a starting point; it is not practice evidence"
        )
        assert all(s.mastery_probability <= placement.DIAGNOSTIC_CEILING for s in states)


def test_a_placement_never_overrules_mastery_the_student_earned(client, student_token):
    slug = seed(slug="placement-earned")
    built = client.get(f"/api/events/{slug}/placement", headers=auth(student_token)).json()
    concept_id = built["items"][0]["concept_id"]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.role == "student"))
        db.add(MasteryState(user_id=user.id, concept_id=concept_id,
                            mastery_probability=0.93, evidence_count=7))
        db.commit()

    # answer everything wrong; the earned concept must be untouched
    responses = {str(i["id"]): 0 for i in built["items"]}
    result = client.post(f"/api/events/{slug}/placement", headers=auth(student_token),
                         json={"responses": responses}).json()
    assert result["concepts_left_alone_because_the_student_had_evidence"] == 1
    with SessionLocal() as db:
        kept = db.scalar(select(MasteryState).where(MasteryState.concept_id == concept_id))
        assert kept.mastery_probability == pytest.approx(0.93)
        assert kept.evidence_count == 7
