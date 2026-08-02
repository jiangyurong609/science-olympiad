"""A lesson must work whichever shape its checkpoints were written in.

`test_lessons.py` builds its fixture the hand-authored way — `question`, `correct_index`, an
explicit `id` — and passes. 41 of the 73 checkpoints actually published to the pilot are the
other shape, produced by `split_lessons`: `prompt`, `answer_index`, no `id` at all. Every one
of them was broken, and the existing tests could not see it because no fixture was ever built
that way.

These are pinned against the real published shape rather than a convenient one.
"""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Concept, Event, Lesson, LessonProgress, LessonVersion, MasteryState


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_split_style_lesson():
    """The shape `split_lessons` emits: `prompt`, `answer_index`, and no `id`."""
    with SessionLocal() as db:
        event = Event(slug="rocks-split", name="Rocks", division="B", season=2026)
        db.add(event)
        db.flush()
        concept = Concept(event_id=event.id, name="Cleavage", description="Break patterns")
        db.add(concept)
        db.flush()
        lesson = Lesson(
            event_id=event.id, concept_id=concept.id, slug="cleavage",
            title="Cleavage and Fracture", summary="Tell them apart.", status="published",
            disposition="unreviewed_practice", current_version=1, sequence=1,
            estimated_minutes=10,
        )
        db.add(lesson)
        db.flush()
        db.add(LessonVersion(
            lesson_id=lesson.id, version=1, review_status="sme_approved", claim_ids=[1],
            citations=[{"title": "Government source"}],
            content=[
                {"type": "opening", "heading": "Breaking"},
                {
                    "type": "checkpoint",
                    "heading": "Check",
                    "prompt": "Which term describes breaking along flat planes?",
                    "choices": ["Fracture", "Cleavage"],
                    "answer_index": 1,
                    "explanation": "Cleavage follows planes of weak bonding.",
                },
            ],
        ))
        db.commit()
        return concept.id, lesson.id


def test_a_split_generated_checkpoint_does_not_ship_its_answer_key(client, student_token):
    """`answer_index` was never stripped, so the key went to the browser with the question."""
    _, lesson_id = create_split_style_lesson()
    started = client.post(f"/api/lessons/{lesson_id}/start", headers=auth(student_token))
    assert started.status_code == 200
    checkpoint = next(b for b in started.json()["content"] if b["type"] == "checkpoint")
    assert "answer_index" not in checkpoint
    assert "correct_index" not in checkpoint
    assert "explanation" not in checkpoint


def test_a_split_generated_checkpoint_reaches_the_reader_with_its_question(client, student_token):
    """The reader renders `question`; these blocks carry the stem under `prompt`."""
    _, lesson_id = create_split_style_lesson()
    started = client.post(f"/api/lessons/{lesson_id}/start", headers=auth(student_token))
    checkpoint = next(b for b in started.json()["content"] if b["type"] == "checkpoint")
    assert checkpoint["question"] == "Which term describes breaking along flat planes?"
    assert checkpoint["id"], "an id-less block still needs an id the server will accept back"


def test_a_split_generated_checkpoint_can_be_answered_and_completes_the_lesson(
        client, student_token):
    """The whole learn->prove chain: answer, complete, record mastery evidence."""
    concept_id, lesson_id = create_split_style_lesson()
    started = client.post(f"/api/lessons/{lesson_id}/start", headers=auth(student_token))
    checkpoint = next(b for b in started.json()["content"] if b["type"] == "checkpoint")

    wrong = client.post(f"/api/lessons/{lesson_id}/checkpoint", headers=auth(student_token),
                        json={"checkpoint_id": checkpoint["id"], "selected_index": 0})
    assert wrong.status_code == 200, "the id the server served must be one it accepts back"
    assert wrong.json()["correct"] is False

    right = client.post(f"/api/lessons/{lesson_id}/checkpoint", headers=auth(student_token),
                        json={"checkpoint_id": checkpoint["id"], "selected_index": 1})
    assert right.json()["correct"] is True, "graded against `answer_index`, not a missing key"
    assert right.json()["lesson_status"] == "completed"

    with SessionLocal() as db:
        progress = db.scalar(select(LessonProgress).where(LessonProgress.lesson_id == lesson_id))
        mastery = db.scalar(select(MasteryState).where(MasteryState.concept_id == concept_id))
        assert progress.status == "completed"
        assert mastery is not None, "lesson completion is the only mastery evidence a reader gives"
        assert mastery.evidence_count == 1


def test_a_malformed_checkpoint_cannot_strand_a_lesson_incomplete(client, student_token):
    """A checkpoint with no key under any name is ungradeable.

    Counting it toward completion would hold the lesson permanently unfinished, since a
    student has no answer that could ever be marked correct.
    """
    with SessionLocal() as db:
        event = Event(slug="rocks-broken", name="Rocks", division="B", season=2026)
        db.add(event); db.flush()
        concept = Concept(event_id=event.id, name="Streak", description="Powder colour")
        db.add(concept); db.flush()
        lesson = Lesson(event_id=event.id, concept_id=concept.id, slug="streak",
                        title="Streak", summary="Powder.", status="published",
                        disposition="unreviewed_practice", current_version=1, sequence=1)
        db.add(lesson); db.flush()
        db.add(LessonVersion(
            lesson_id=lesson.id, version=1, review_status="sme_approved", claim_ids=[1],
            citations=[{"title": "Government source"}],
            content=[
                {"type": "checkpoint", "heading": "Answerable",
                 "prompt": "What does streak test?", "choices": ["Powder colour", "Hardness"],
                 "answer_index": 0},
                {"type": "checkpoint", "heading": "Broken",
                 "prompt": "No key was ever written for this one.",
                 "choices": ["A", "B"]},
            ],
        ))
        db.commit()
        lesson_id = lesson.id

    started = client.post(f"/api/lessons/{lesson_id}/start", headers=auth(student_token))
    blocks = [b for b in started.json()["content"] if b["type"] == "checkpoint"]

    answered = client.post(f"/api/lessons/{lesson_id}/checkpoint", headers=auth(student_token),
                           json={"checkpoint_id": blocks[0]["id"], "selected_index": 0})
    assert answered.status_code == 200, "a broken neighbour must not break a sound checkpoint"
    assert answered.json()["lesson_status"] == "completed"

    ungradeable = client.post(f"/api/lessons/{lesson_id}/checkpoint", headers=auth(student_token),
                              json={"checkpoint_id": blocks[1]["id"], "selected_index": 0})
    assert ungradeable.status_code == 422, "say it cannot be graded, don't call the answer wrong"


def test_progress_cannot_mark_an_id_less_checkpoint_complete_unanswered(client, student_token):
    """The guard keyed off the raw `id`, so it never saw these blocks at all."""
    _, lesson_id = create_split_style_lesson()
    started = client.post(f"/api/lessons/{lesson_id}/start", headers=auth(student_token))
    checkpoint = next(b for b in started.json()["content"] if b["type"] == "checkpoint")

    cheated = client.put(f"/api/lessons/{lesson_id}/progress", headers=auth(student_token),
                         json={"current_block": 1, "completed_block_ids": [checkpoint["id"]]})
    assert cheated.status_code == 422
