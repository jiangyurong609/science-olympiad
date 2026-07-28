"""Create editor-review lesson drafts grounded in an ingested video transcript."""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Event, EventSourceMap, Lesson, LessonVersion, Source, SourceSnapshot
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

SYSTEM = """You are a Science Olympiad instructional designer. Create one rigorous lesson
from the supplied YouTube transcript. Return strict JSON with title, summary,
estimated_minutes, and blocks. Blocks must be an ordered list: opening first,
3-6 teaching blocks using property_cards, steps, or worked_example, at least 3
checkpoints, and summary last. Checkpoints need choices and correct_index.
Do not copy long transcript passages; paraphrase and distinguish claims that
need editor verification. Output JSON only."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:90] or "video-lesson"


def _latest(db: Session, source_id: int) -> SourceSnapshot | None:
    return db.scalar(select(SourceSnapshot).where(SourceSnapshot.source_id == source_id).order_by(SourceSnapshot.id.desc()))


def normalize_blocks(blocks: list) -> list:
    """Coerce common model variations into the lesson reader's typed blocks."""
    out = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "teaching":
            if block.get("property_cards"):
                cards = []
                for card in block["property_cards"]:
                    props = card.get("properties") or []
                    cards.append({"name": str(card.get("name") or "Concept"), "cue": str(props[0] if props else ""), "detail": " ".join(map(str, props[1:]))})
                out.append({"type": "property_cards", "heading": "Key ideas", "body": "", "cards": cards})
            elif block.get("steps"):
                out.append({"type": "steps", "heading": "Apply the routine", "steps": [{"label": str(s.get("name") or s.get("step") or f"Step {i+1}"), "detail": str(s.get("details") or s.get("detail") or s.get("work") or "")} for i, s in enumerate(block["steps"]) if isinstance(s, dict)]})
            elif block.get("worked_example"):
                example = block["worked_example"]
                out.append({"type": "worked_example", "heading": str(example.get("title") or "Worked example"), "prompt": str(example.get("scenario") or ""), "steps": [str(s.get("work") or s) for s in example.get("steps", [])]})
        elif kind in {"opening", "property_cards", "steps", "worked_example", "checkpoint", "summary", "video"}:
            out.append(block)
    return out


def generate_video_lesson(db: Session, event: Event, source: Source, *, commit: bool = True) -> Lesson | None:
    snapshot = _latest(db, source.id)
    if not snapshot or snapshot.metadata_json.get("kind") != "youtube_transcript":
        return None
    existing = db.scalar(select(Lesson).where(Lesson.event_id == event.id, Lesson.slug.like(f"video-{source.id}-%")))
    if existing:
        return existing
    video = snapshot.metadata_json
    # Keep enough contiguous context for grounding while avoiding model context
    # bloat; the complete timestamped transcript remains in SourceSnapshot.
    transcript = snapshot.extracted_text[:9000]
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise ModelProviderError("External model provider is not configured")
    prompt = json.dumps({"event": event.name, "division": event.division, "video_title": video.get("title") or source.title,
                         "transcript": transcript})
    payload = provider.generate_json(SYSTEM, prompt).payload
    if not isinstance(payload, dict):
        return None
    blocks = normalize_blocks(payload.get("blocks", []))
    if not blocks:
        return None
    for i, block in enumerate(blocks):
        if block.get("type") == "checkpoint":
            block["id"] = f"video-cp-{i}"
    video_block = {"type": "video", "video_id": video["video_id"], "title": video.get("title") or source.title,
                   "channel": video.get("channel", ""), "duration": video.get("duration"),
                   "transcript_source": source.id, "transcript_excerpt": "Watch the video, then use the lesson notes and checkpoints to verify your understanding."}
    if blocks[0].get("type") == "opening":
        blocks.insert(1, video_block)
    else:
        blocks.insert(0, video_block)
    title = str(payload.get("title") or video.get("title") or source.title).strip()
    slug = f"video-{source.id}-{_slug(title)}"
    existing = db.scalar(select(Lesson).where(Lesson.event_id == event.id, Lesson.slug == slug))
    if existing:
        return existing
    try:
        minutes = max(8, min(60, int(payload.get("estimated_minutes", 20))))
    except (TypeError, ValueError):
        minutes = 20
    lesson = Lesson(event_id=event.id, slug=slug, title=title,
                    summary=str(payload.get("summary") or "Transcript-grounded video lesson"),
                    status="draft", current_version=1, sequence=9000, estimated_minutes=minutes)
    db.add(lesson)
    db.flush()
    db.add(LessonVersion(lesson_id=lesson.id, version=1, content=blocks,
                         citations=[{"title": source.title, "publisher": source.publisher, "url": source.url, "source_id": source.id}],
                         review_status="editor_review"))
    if commit:
        db.commit()
        db.refresh(lesson)
    return lesson
