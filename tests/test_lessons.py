from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Concept, Event, Lesson, LessonProgress, LessonVersion, MasteryState


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_lesson():
    with SessionLocal() as db:
        event = Event(slug="rocks", name="Rocks", division="B", season=2026)
        db.add(event)
        db.flush()
        concept = Concept(event_id=event.id, name="Properties", description="Observe evidence")
        db.add(concept)
        db.flush()
        lesson = Lesson(
            event_id=event.id,
            concept_id=concept.id,
            slug="properties",
            title="Observe Properties",
            summary="Use evidence.",
            status="published",
            current_version=1,
            sequence=1,
            estimated_minutes=10,
        )
        db.add(lesson)
        db.flush()
        db.add(LessonVersion(
            lesson_id=lesson.id,
            version=1,
            review_status="sme_approved",
            claim_ids=[1],
            citations=[{"title": "Government source"}],
            content=[
                {"id": "intro", "type": "opening", "heading": "Observe"},
                {
                    "id": "check-one",
                    "type": "checkpoint",
                    "heading": "Check",
                    "question": "Which property measures scratching?",
                    "choices": ["Hardness", "Luster"],
                    "correct_index": 0,
                    "explanation": "Hardness measures resistance to scratching.",
                    "misconception_by_choice": {"1": "Luster is reflected light."},
                },
                {
                    "id": "check-two",
                    "type": "checkpoint",
                    "heading": "Check again",
                    "question": "Which property describes reflected light?",
                    "choices": ["Hardness", "Luster"],
                    "correct_index": 1,
                    "explanation": "Luster describes reflected light.",
                },
            ],
        ))
        db.commit()
        return event.id, concept.id, lesson.id


def test_lesson_catalog_start_and_progress(client, student_token):
    event_id, _, lesson_id = create_lesson()

    catalog = client.get(f"/api/events/{event_id}/lessons", headers=auth(student_token))
    assert catalog.status_code == 200
    assert catalog.json()[0]["progress"]["status"] == "not_started"

    started = client.post(f"/api/lessons/{lesson_id}/start", headers=auth(student_token))
    assert started.status_code == 200
    checkpoint = next(block for block in started.json()["content"] if block["type"] == "checkpoint")
    assert "correct_index" not in checkpoint
    assert "explanation" not in checkpoint
    assert started.json()["review_status"] == "sme_approved"

    saved = client.put(
        f"/api/lessons/{lesson_id}/progress",
        headers=auth(student_token),
        json={"current_block": 1, "completed_block_ids": ["intro"]},
    )
    assert saved.status_code == 200
    assert saved.json()["current_block"] == 1


def test_lesson_checkpoints_complete_lesson_and_update_mastery(client, student_token):
    _, concept_id, lesson_id = create_lesson()
    client.post(f"/api/lessons/{lesson_id}/start", headers=auth(student_token))

    wrong = client.post(
        f"/api/lessons/{lesson_id}/checkpoint",
        headers=auth(student_token),
        json={"checkpoint_id": "check-one", "selected_index": 1},
    )
    assert wrong.status_code == 200
    assert wrong.json()["correct"] is False
    assert wrong.json()["misconception"] == "Luster is reflected light."

    first = client.post(
        f"/api/lessons/{lesson_id}/checkpoint",
        headers=auth(student_token),
        json={"checkpoint_id": "check-one", "selected_index": 0},
    )
    assert first.json()["lesson_status"] == "in_progress"
    second = client.post(
        f"/api/lessons/{lesson_id}/checkpoint",
        headers=auth(student_token),
        json={"checkpoint_id": "check-two", "selected_index": 1},
    )
    assert second.json()["lesson_status"] == "completed"

    with SessionLocal() as db:
        progress = db.scalar(select(LessonProgress).where(LessonProgress.lesson_id == lesson_id))
        mastery = db.scalar(select(MasteryState).where(MasteryState.concept_id == concept_id))
        assert progress.status == "completed"
        assert mastery.mastery_probability >= 0.45
        assert mastery.evidence_count == 1
