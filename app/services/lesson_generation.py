"""Generate a systematic, in-depth course for an event from its materials.

Two stages so the course is comprehensive rather than a few thin slides:
  1. SYLLABUS: the model designs an ordered progression of lessons that cover the
     event from foundations to advanced application, grounded in the material.
  2. LESSON: each syllabus item is expanded into one thorough, multi-block lesson
     (10-16 blocks with several checkpoints) that fully teaches its subtopics.

Blocks match exactly what the lesson reader renders (opening / property_cards /
steps / worked_example / checkpoint / summary). Lessons are published and tagged
with the `auto-` slug prefix so regeneration replaces the prior set.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Event, EventSourceMap, Lesson, LessonVersion, Source, SourceSnapshot,
)
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

MATERIAL_CHARS = 24_000
LESSON_MATERIAL_CHARS = 16_000
SLUG_PREFIX = "auto-"
PROMPT_VERSION = "material-course-v2"
TARGET_LESSONS = 8

_SYLLABUS_SYSTEM = (
    "You are a Science Olympiad curriculum designer. Given an event and its official "
    "material, design a SYSTEMATIC course: an ordered progression of lessons that "
    "together cover the whole event, foundations first and advanced application last, "
    "with NO major topic left out. Return STRICT JSON {\"lessons\": [ {\"title\": str, "
    "\"focus\": str (one sentence on what this lesson teaches), \"subtopics\": [str, ...] "
    "(4-7 concrete subtopics)} ]}. Produce " + str(TARGET_LESSONS) + " lessons of "
    "increasing depth, each distinct, grounded in the actual material. Output only JSON."
)

_LESSON_SYSTEM = (
    "You are an expert Science Olympiad coach writing ONE in-depth lesson within a "
    "course, grounded ONLY in the provided source material. The lesson must be THOROUGH "
    "and teach every listed subtopic — not a summary. Return STRICT JSON {\"title\": str, "
    "\"summary\": str, \"estimated_minutes\": int, \"blocks\": [ ... ]}. `blocks` is an "
    "ORDERED list of 10-16 typed objects that build understanding step by step; each "
    "block is exactly one of:\n"
    "- {\"type\":\"opening\",\"kicker\":str,\"heading\":str,\"body\":str}  (motivating intro; first block)\n"
    "- {\"type\":\"property_cards\",\"heading\":str,\"body\":str,\"cards\":[{\"name\":str,\"cue\":str,\"detail\":str}]}  (a set of related concepts; 3-6 cards)\n"
    "- {\"type\":\"steps\",\"heading\":str,\"steps\":[{\"label\":str,\"detail\":str}]}  (a procedure/routine; 4-7 steps)\n"
    "- {\"type\":\"worked_example\",\"heading\":str,\"prompt\":str,\"steps\":[str]}  (a fully solved example; 4-7 steps)\n"
    "- {\"type\":\"checkpoint\",\"id\":str,\"heading\":str,\"question\":str,\"choices\":[str,str,str,str],\"correct_index\":int,\"explanation\":str}  (knowledge check)\n"
    "- {\"type\":\"summary\",\"heading\":str,\"points\":[str]}  (key takeaways; last block)\n"
    "Requirements: exactly one `opening` first and one `summary` last; at least 5 teaching "
    "blocks (property_cards/steps/worked_example) covering ALL the subtopics; at least 3 "
    "`checkpoint` blocks spread through the lesson, each with one correct answer and "
    "plausible distractors. Be rigorous, specific, and accurate to the source. Do not copy "
    "long verbatim passages. Output only the JSON object."
)

_TEACHING = {"property_cards", "steps", "worked_example"}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:100] or "lesson"


def _course_material(db: Session, event: Event) -> tuple[Source, str] | None:
    """Combine the event's richest materials into one grounding corpus."""
    snaps: list[tuple[Source, str]] = []
    for mapping in db.scalars(select(EventSourceMap).where(EventSourceMap.event_id == event.id)).all():
        snap = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_id == mapping.source_id
        ).order_by(SourceSnapshot.id.desc()))
        text = (snap.extracted_text if snap else "") or ""
        if len(text.strip()) >= 400:
            snaps.append((db.get(Source, mapping.source_id), text))
    if not snaps:
        return None
    snaps.sort(key=lambda s: len(s[1]), reverse=True)
    combined, total = [], 0
    for source, text in snaps:
        chunk = text[: MATERIAL_CHARS - total]
        combined.append(f"# {source.title}\n{chunk}")
        total += len(chunk)
        if total >= MATERIAL_CHARS:
            break
    return snaps[0][0], "\n\n".join(combined)


def _valid_blocks(raw_blocks, lesson_index: int) -> list:
    blocks = []
    for position, block in enumerate(raw_blocks if isinstance(raw_blocks, list) else []):
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "checkpoint":
            choices = [str(c) for c in (block.get("choices") or [])]
            ci = block.get("correct_index")
            if len(choices) < 2 or not isinstance(ci, int) or not (0 <= ci < len(choices)):
                continue
            block = {**block, "choices": choices, "correct_index": ci,
                     "id": f"l{lesson_index}-cp{position}"}
        elif kind not in {"opening", "property_cards", "steps", "worked_example", "summary"}:
            continue
        blocks.append(block)
    return blocks


def event_has_generated_lessons(db: Session, event: Event) -> bool:
    return db.scalar(select(Lesson).where(
        Lesson.event_id == event.id, Lesson.slug.like(f"{SLUG_PREFIX}%")
    )) is not None


def _generate_syllabus(provider, event: Event, material: str) -> list[dict]:
    user = json.dumps({"event": event.name, "division": event.division,
                       "material": material[:MATERIAL_CHARS]})
    payload = provider.generate_json(_SYLLABUS_SYSTEM, user).payload
    lessons = payload.get("lessons", []) if isinstance(payload, dict) else []
    return [l for l in lessons if isinstance(l, dict) and l.get("title")]


def _generate_lesson(provider, event: Event, entry: dict, material: str) -> dict | None:
    user = json.dumps({
        "event": event.name, "division": event.division,
        "lesson_title": entry.get("title"), "focus": entry.get("focus"),
        "subtopics": entry.get("subtopics", []),
        "material": material[:LESSON_MATERIAL_CHARS],
    })
    payload = provider.generate_json(_LESSON_SYSTEM, user).payload
    return payload if isinstance(payload, dict) else None


def generate_lessons_for_event(db: Session, event: Event, commit: bool = True) -> list[Lesson]:
    picked = _course_material(db, event)
    if not picked:
        raise ValueError(f"Event {event.slug} has no material with enough text for lessons")
    source, material = picked
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise ModelProviderError("External model provider is not configured")

    syllabus = _generate_syllabus(provider, event, material)
    if not syllabus:
        raise ModelProviderError("Model returned no syllabus")

    citations = [{"title": source.title, "publisher": source.publisher or "",
                  "url": source.url if source.url.startswith(("http://", "https://")) else ""}]
    # Regeneration replaces the prior auto-generated course.
    old = db.scalars(select(Lesson.id).where(
        Lesson.event_id == event.id, Lesson.slug.like(f"{SLUG_PREFIX}%")
    )).all()
    if old:
        db.execute(delete(LessonVersion).where(LessonVersion.lesson_id.in_(old)))
        db.execute(delete(Lesson).where(Lesson.id.in_(old)))
        db.flush()

    # Generate the lessons' content concurrently (I/O-bound HTTP calls); DB writes
    # stay on this thread afterward since the SQLAlchemy session isn't thread-safe.
    def _safe_generate(entry):
        try:
            return _generate_lesson(provider, event, entry, material)
        except Exception:  # noqa: BLE001 — one bad lesson shouldn't sink the course
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        raw_lessons = list(pool.map(_safe_generate, syllabus))

    lessons: list[Lesson] = []
    for index, (entry, raw) in enumerate(zip(syllabus, raw_lessons)):
        if not raw:
            continue
        blocks = _valid_blocks(raw.get("blocks", []), index)
        teaching = sum(1 for b in blocks if b.get("type") in _TEACHING)
        checkpoints = sum(1 for b in blocks if b.get("type") == "checkpoint")
        if len(blocks) < 6 or teaching < 2 or checkpoints < 1:
            continue
        title = str(raw.get("title") or entry.get("title") or f"{event.name} Lesson {index + 1}").strip()
        try:
            minutes = max(8, min(60, int(raw.get("estimated_minutes", 20))))
        except (TypeError, ValueError):
            minutes = 20
        lesson = Lesson(
            event_id=event.id, slug=f"{SLUG_PREFIX}{_slugify(title)}-{index + 1}",
            title=title, summary=str(raw.get("summary") or entry.get("focus") or ""),
            status="published", current_version=1, sequence=index + 1, estimated_minutes=minutes,
        )
        db.add(lesson)
        db.flush()
        db.add(LessonVersion(
            lesson_id=lesson.id, version=1, content=blocks,
            citations=citations, review_status="published",
        ))
        lessons.append(lesson)
    if commit:
        db.commit()
        for lesson in lessons:
            db.refresh(lesson)
    return lessons
