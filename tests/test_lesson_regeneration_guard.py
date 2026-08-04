"""Regeneration must never leave an event with fewer lessons than it started with.

`generate_lessons_for_event` deletes the prior auto-generated course before it writes the
new one. Every step after that delete can drop lessons silently — `_safe_generate` swallows
per-lesson model failures, `_valid_blocks` discards malformed blocks, and a lesson with no
resolvable citations is skipped. So "the model had a bad day and every lesson was dropped"
ends with the delete committed and nothing put back: an event that had a working course now
has none, and a student sees an empty event.
"""
import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, LessonVersion, Source, SourceSnapshot, EventSourceMap
from app.services.lesson_generation import SLUG_PREFIX, generate_lessons_for_event
from app.services.model_provider import ModelProviderError


def _event_with_material_and_a_course(db):
    event = Event(slug="regen-guard", name="Regen Guard", division="C", season=2026)
    db.add(event)
    db.flush()
    source = Source(
        title="Grounding Material", url="https://example.org/material.pdf",
        publisher="Example", approved=True, rights_status="public_domain",
        extracted_text="Mineral hardness is measured on the Mohs scale. " * 200,
        content_hash="regenguard",
    )
    db.add(source)
    db.flush()
    db.add(SourceSnapshot(
        source_id=source.id, final_url=source.url, content_hash="regenguard",
        extracted_text=source.extracted_text,
    ))
    db.add(EventSourceMap(
        event_id=event.id, source_id=source.id, purpose="course_material",
        source_tier=1, required=True, required_artifact_types=["parsed_text"],
        source_universe_version="v1", freshness_minutes=0, reviewed=True,
    ))
    lesson = Lesson(
        event_id=event.id, slug=f"{SLUG_PREFIX}existing-1", title="Existing Lesson",
        summary="Already serving students.", status="published",
        disposition="unreviewed_practice", current_version=1, sequence=1,
        estimated_minutes=15,
    )
    db.add(lesson)
    db.flush()
    db.add(LessonVersion(
        lesson_id=lesson.id, version=1, content=[{"type": "opening", "heading": "Hi"}],
        citations=[{"source_id": source.id}], review_status="ai_draft",
    ))
    db.commit()
    return event.id


def test_a_regeneration_that_yields_nothing_keeps_the_existing_course(monkeypatch):
    with SessionLocal() as db:
        event_id = _event_with_material_and_a_course(db)

    import app.services.lesson_generation as lg

    class _Provider:
        configured = True

        def generate_json(self, system, user):  # pragma: no cover - shape only
            raise AssertionError("syllabus/lesson generation is stubbed below")

    monkeypatch.setattr(lg, "OpenAICompatibleProvider", lambda *a, **k: _Provider())
    monkeypatch.setattr(lg, "_generate_syllabus", lambda *a, **k: [
        {"title": "Doomed Lesson", "focus": "f", "subtopics": ["a"]},
    ])
    # every lesson fails to generate — the reachable bad day this guard exists for
    monkeypatch.setattr(lg, "_generate_lesson", lambda *a, **k: None)

    with SessionLocal() as db:
        event = db.get(Event, event_id)
        with pytest.raises(ModelProviderError, match="rather than replacing them with nothing"):
            generate_lessons_for_event(db, event)
        db.rollback()

    with SessionLocal() as db:
        surviving = db.scalars(select(Lesson).where(Lesson.event_id == event_id)).all()
        assert [l.title for l in surviving] == ["Existing Lesson"], (
            "the old course must still be serving students after a failed regeneration"
        )
        assert db.scalars(select(LessonVersion).where(
            LessonVersion.lesson_id == surviving[0].id)).all(), "its version must survive too"
