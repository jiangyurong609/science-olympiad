"""A hint must help without answering, and must not be capability on unreviewed content.

Two refusals carry Phase 8's scaffolding, and both are easy to lose silently: a hint that
names the answer still *reads* like help, and a hint served on an unreviewed lesson is exactly
the "capability multiplies the defect" the plan's rule 4 exists for.
"""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, Lesson, LessonProgress, LessonVersion, ReviewDecision, User,
)
from app.services.lesson_hints import hint_is_too_revealing


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_lesson_with_hint(*, hint="Think about which property resists scratching.",
                            too_revealing=False):
    with SessionLocal() as db:
        event = Event(slug="hints-event", name="Hints", division="B", season=2026)
        db.add(event); db.flush()
        concept = Concept(event_id=event.id, name="Hardness", description="Scratch")
        db.add(concept); db.flush()
        lesson = Lesson(event_id=event.id, concept_id=concept.id, slug="hardness",
                        title="Hardness", summary="Scratching.", status="published",
                        disposition="unreviewed_practice", current_version=1, sequence=1)
        db.add(lesson); db.flush()
        block = {
            "type": "checkpoint", "heading": "Check",
            "prompt": "Which property resists scratching?",
            "choices": ["Luster", "Hardness"], "answer_index": 1,
            "hint": hint,
        }
        if too_revealing:
            block["hint_too_revealing"] = True
        db.add(LessonVersion(
            lesson_id=lesson.id, version=1, review_status="sme_approved", claim_ids=[1],
            citations=[{"title": "Government source"}], content=[block],
        ))
        db.commit()
        return lesson.id


def _approve(lesson_id: int) -> None:
    with SessionLocal() as db:
        reviewer = db.scalar(select(User).where(User.role.in_(("admin", "editor"))))
        if reviewer is None:
            reviewer = User(email="reviewer@example.test", full_name="Reviewer",
                            role="editor")
            db.add(reviewer); db.flush()
        for stage in ("editor", "sme"):
            db.add(ReviewDecision(entity_type="lesson", entity_id=lesson_id, entity_version=1,
                                  stage=stage, decision="approved",
                                  reviewer_user_id=reviewer.id))
        db.commit()


def _checkpoint_id(client, lesson_id, token):
    started = client.post(f"/api/lessons/{lesson_id}/start", headers=auth(token))
    return next(b for b in started.json()["content"] if b["type"] == "checkpoint")["id"]


def test_a_hint_is_withheld_until_the_lesson_has_been_reviewed(client, student_token):
    """Rule 4: no new student-facing capability on unreviewed content."""
    lesson_id = create_lesson_with_hint()
    cid = _checkpoint_id(client, lesson_id, student_token)
    response = client.get(f"/api/lessons/{lesson_id}/checkpoint/{cid}/hint",
                          headers=auth(student_token))
    assert response.status_code == 200
    assert response.json() == {"available": False, "reason": "lesson_not_yet_reviewed"}


def test_a_reviewed_lesson_serves_its_hint(client, student_token):
    lesson_id = create_lesson_with_hint()
    cid = _checkpoint_id(client, lesson_id, student_token)
    _approve(lesson_id)
    response = client.get(f"/api/lessons/{lesson_id}/checkpoint/{cid}/hint",
                          headers=auth(student_token))
    assert response.json()["available"] is True
    assert "scratching" in response.json()["hint"]


def test_a_hint_the_solver_showed_was_giving_the_answer_away_is_never_served(
        client, student_token):
    lesson_id = create_lesson_with_hint(hint="The answer is Hardness.", too_revealing=True)
    cid = _checkpoint_id(client, lesson_id, student_token)
    _approve(lesson_id)
    response = client.get(f"/api/lessons/{lesson_id}/checkpoint/{cid}/hint",
                          headers=auth(student_token))
    assert response.json() == {"available": False, "reason": "hint_withheld_pending_rewrite"}, (
        "review clearance must not override the answer-leak refusal"
    )


def test_asking_for_a_hint_is_recorded(client, student_token):
    lesson_id = create_lesson_with_hint()
    cid = _checkpoint_id(client, lesson_id, student_token)
    _approve(lesson_id)
    client.get(f"/api/lessons/{lesson_id}/checkpoint/{cid}/hint", headers=auth(student_token))
    with SessionLocal() as db:
        progress = db.scalar(select(LessonProgress).where(
            LessonProgress.lesson_id == lesson_id))
        assert progress.checkpoint_results[cid]["hint_used"] is True


def test_the_hint_response_never_carries_the_answer_index(client, student_token):
    lesson_id = create_lesson_with_hint()
    cid = _checkpoint_id(client, lesson_id, student_token)
    _approve(lesson_id)
    body = client.get(f"/api/lessons/{lesson_id}/checkpoint/{cid}/hint",
                      headers=auth(student_token)).json()
    assert set(body) <= {"available", "hint", "reason"}


def test_the_too_revealing_rule_only_implicates_hints_that_change_the_answer():
    # solver already knew it without the hint: the item was easy, the hint proved nothing
    assert hint_is_too_revealing(solver_choice=1, answer_index=1, baseline_choice=1) is False
    # solver was wrong without it and right with it: the hint handed it over
    assert hint_is_too_revealing(solver_choice=1, answer_index=1, baseline_choice=0) is True
    # still wrong with the hint
    assert hint_is_too_revealing(solver_choice=0, answer_index=1, baseline_choice=0) is False
    # nothing to judge against
    assert hint_is_too_revealing(solver_choice=1, answer_index=None, baseline_choice=0) is False
