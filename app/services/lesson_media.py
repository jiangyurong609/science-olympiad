"""Grounded, deterministic media composition for lesson drafts.

The model writes the explanation and checks; this module chooses only media
that already passed the platform's source/rights gates.  That keeps URLs and
captions from being hallucinated while giving every visual event a balanced
watch/read/observe rhythm.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Event, EventSourceMap, Lesson, LessonVersion, RightsStatus, Source, SourcePassage, SourceSnapshot


MANIFEST_PATH = Path(__file__).resolve().parent.parent / "static" / "media" / "manifest.json"
GALLERY_ID = "auto-media-gallery"
VIDEO_ID = "auto-source-video"
APPROVED_IMAGE_RIGHTS = {
    RightsStatus.PUBLIC_DOMAIN.value,
    RightsStatus.APPROVED_WITH_ATTRIBUTION.value,
    RightsStatus.DERIVATIVE_GENERATION_ALLOWED.value,
}


def _base_event_slug(slug: str) -> str:
    return re.sub(r"-(?:b|c)(?:-\d{4})?$", "", slug.lower())


def _block_text(block: dict) -> str:
    values = [block.get("heading", ""), block.get("body", ""), block.get("prompt", "")]
    for card in block.get("cards", []) or []:
        if isinstance(card, dict):
            values.extend([card.get("name", ""), card.get("cue", ""), card.get("detail", "")])
    for step in block.get("steps", []) or []:
        if isinstance(step, dict):
            values.extend([step.get("label", ""), step.get("detail", "")])
        else:
            values.append(str(step))
    values.extend(str(point) for point in (block.get("points", []) or []))
    return " ".join(str(value) for value in values).casefold()


def _manifest_images(event: Event) -> list[dict]:
    try:
        manifest = json.loads(MANIFEST_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return list(manifest.get(_base_event_slug(event.slug), []))


def _approved_video(db: Session, event: Event) -> tuple[Source, dict] | None:
    mappings = db.scalars(select(EventSourceMap).where(
        EventSourceMap.event_id == event.id,
        EventSourceMap.reviewed.is_(True),
    )).all()
    for mapping in mappings:
        source = db.get(Source, mapping.source_id)
        if not source or not source.approved or "youtube.com" not in source.url and "youtu.be" not in source.url:
            continue
        snapshot = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_id == source.id,
        ).order_by(SourceSnapshot.id.desc()))
        metadata = (snapshot.metadata_json if snapshot else None) or source.metadata_json or {}
        if metadata.get("kind") != "youtube_transcript" or not metadata.get("video_id"):
            continue
        return source, metadata
    return None


def compose_multimedia_blocks(db: Session, event: Event, blocks: list[dict]) -> list[dict]:
    """Insert grounded video/gallery blocks into a generated lesson.

    Existing authored media is preserved. Auto blocks are replaced so
    regeneration is idempotent. A gallery is added only when at least two
    event images match the lesson's concepts; a video is added only for an
    approved, reviewed YouTube source.
    """
    content = [block for block in blocks if block.get("id") not in {GALLERY_ID, VIDEO_ID}]
    corpus = " ".join(_block_text(block) for block in content)
    images = []
    for item in _manifest_images(event):
        label = str(item.get("label") or "")
        terms = [label.casefold(), str(item.get("slug") or "").replace("-", " ").casefold()]
        if any(term and re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", corpus) for term in terms):
            images.append({
                "url": item.get("url"), "label": label, "alt": item.get("alt") or label,
                "note": "Use observable features before naming the specimen.",
                "attribution": item.get("attribution", ""), "license": item.get("license", ""),
                "source_url": item.get("source_url", ""),
            })
        if len(images) >= 6:
            break
    inserts = []
    if len(images) >= 2:
        inserts.append({
            "id": GALLERY_ID, "type": "image_gallery", "kicker": "Observe before you infer",
            "heading": "See the Evidence", "body": "Compare the specimens side by side. Name the observation that separates each one before you decide.",
            "images": images,
        })
    video = _approved_video(db, event)
    if video:
        source, metadata = video
        passage_ids = [row.id for row in db.scalars(select(SourcePassage).where(
            SourcePassage.source_id == source.id,
        ).order_by(SourcePassage.sequence, SourcePassage.id).limit(2)).all()]
        inserts.append({
            "id": VIDEO_ID, "type": "video", "video_id": metadata["video_id"],
            "title": metadata.get("title") or source.title, "channel": metadata.get("channel", ""),
            "duration": metadata.get("duration"), "transcript_source": source.id,
            "passage_ids": passage_ids,
            "transcript_excerpt": "Watch for the demonstration, then use the next checkpoint to apply the same reasoning yourself.",
        })
    if not inserts:
        return content
    insert_at = 1 if content and content[0].get("type") == "opening" else 0
    # Video first establishes context; the gallery follows as an observation
    # task. The lesson remains text-led rather than becoming a media carousel.
    content[insert_at:insert_at] = sorted(inserts, key=lambda item: 0 if item["type"] == "video" else 1)
    return content


def enrich_lesson_version(db: Session, lesson: Lesson, version: LessonVersion) -> bool:
    """Apply deterministic media composition to one version, returning changed."""
    composed = compose_multimedia_blocks(db, db.get(Event, lesson.event_id), version.content or [])
    if composed == (version.content or []):
        return False
    version.content = composed
    return True
