"""Phase V — turn a published lesson into a reviewable storyboard, and gate the render.

The storyboard is where slides and narration are authored together, so a scene is only
well-formed when its on-screen plan and its spoken beat describe the same idea. Two gates
protect what reaches students:

  * grounding — every narration beat cites an approved claim from the lesson, so narration
    cannot introduce a fact the lesson never established;
  * approval — nothing is synthesized or rendered from a storyboard that a human has not
    approved.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Lesson, LessonVersion, ScientificClaim, VideoRender, VideoStoryboard,
)

DRAFT = "draft"
APPROVED = "approved"
REJECTED = "rejected"

# Lesson block types that carry teaching content worth a slide.
TEACHABLE_BLOCKS = {
    "opening", "property_cards", "steps", "worked_example", "image_gallery", "summary",
}


class StoryboardError(ValueError):
    pass


def _block_text(block: dict) -> str:
    for key in ("heading", "title", "text", "summary", "prompt"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def draft_from_lesson(db: Session, lesson_id: int) -> dict:
    """Propose scenes from a lesson's current version. The narration here is a starting
    point for a human to refine — the point of the approval gate."""
    lesson = db.get(Lesson, lesson_id)
    if not lesson:
        raise StoryboardError("lesson not found")
    version = db.scalar(select(LessonVersion).where(
        LessonVersion.lesson_id == lesson.id,
        LessonVersion.version == lesson.current_version,
    ))
    if not version:
        raise StoryboardError("lesson has no current version")

    claim_ids = [c for c in (version.claim_ids or []) if isinstance(c, int)]
    scenes = []
    for index, block in enumerate(version.content or []):
        if block.get("type") not in TEACHABLE_BLOCKS:
            continue
        headline = _block_text(block)
        if not headline:
            continue
        scenes.append({
            "index": len(scenes) + 1,
            # Which lesson block this scene teaches. Kept so a chapter can be shown against
            # the section it covers instead of becoming a parallel, unrelated list.
            "block_indexes": [index],
            "block_type": block.get("type"),
            "headline": headline,
            "visual": block.get("type"),
            "narration": "",             # authored/refined before approval
            "claim_ids": claim_ids[:1],  # narrower grounding is set during review
            "asset_ids": [a for a in (block.get("asset_ids") or []) if isinstance(a, int)],
        })
    if not scenes:
        raise StoryboardError("lesson has no teachable blocks to storyboard")
    return {
        "lesson_id": lesson.id,
        "lesson_version": lesson.current_version,
        "event_id": lesson.event_id,
        "title": lesson.title,
        "scenes": scenes,
    }


def _claims_available_to_lesson(db: Session, lesson_id: int | None) -> set[int]:
    """Claims a lesson may cite: approved, and belonging to this lesson or its event.

    Approval alone is not grounding. Without this, narration about ecosystems could cite an
    approved claim about mineral identification and pass the gate.
    """
    if lesson_id is None:
        return set()
    lesson = db.get(Lesson, lesson_id)
    if not lesson:
        return set()
    version = db.scalar(select(LessonVersion).where(
        LessonVersion.lesson_id == lesson.id,
        LessonVersion.version == lesson.current_version,
    ))
    allowed = {c for c in ((version.claim_ids if version else None) or []) if isinstance(c, int)}
    # also allow approved claims mapped to this event's concepts, which is how the claims
    # pipeline attaches evidence
    from app.models.entities import Concept
    concept_ids = [c.id for c in db.scalars(
        select(Concept).where(Concept.event_id == lesson.event_id)
    ).all()]
    if concept_ids:
        allowed |= set(db.scalars(select(ScientificClaim.id).where(
            ScientificClaim.concept_id.in_(concept_ids)
        )).all())
    approved = set(db.scalars(
        select(ScientificClaim.id).where(ScientificClaim.approved.is_(True))
    ).all())
    return allowed & approved


def validate_scenes(db: Session, scenes: list[dict], lesson_id: int | None = None) -> list[str]:
    """Grounding + completeness problems that must be fixed before approval."""
    problems: list[str] = []
    if not scenes:
        return ["storyboard has no scenes"]
    approved_claims = set(db.scalars(
        select(ScientificClaim.id).where(ScientificClaim.approved.is_(True))
    ).all())
    relevant_claims = _claims_available_to_lesson(db, lesson_id)
    for scene in scenes:
        label = f"scene {scene.get('index', '?')}"
        if not str(scene.get("narration", "")).strip():
            problems.append(f"{label}: narration is empty")
        if not str(scene.get("headline", "")).strip():
            problems.append(f"{label}: no on-screen headline")
        claim_ids = scene.get("claim_ids") or []
        if not claim_ids:
            problems.append(f"{label}: narration is not grounded in any claim")
        else:
            ungrounded = [c for c in claim_ids if c not in approved_claims]
            if ungrounded:
                problems.append(f"{label}: cites unapproved claim(s) {ungrounded}")
            if lesson_id is not None:
                unrelated = [c for c in claim_ids if c in approved_claims and c not in relevant_claims]
                if unrelated:
                    problems.append(
                        f"{label}: cites claim(s) {unrelated} that do not belong to this lesson "
                        f"or its event — approval alone is not grounding"
                    )
    return problems


def create_storyboard(db: Session, lesson_id: int, scenes: list[dict], title: str = "") -> VideoStoryboard:
    lesson = db.get(Lesson, lesson_id)
    if not lesson:
        raise StoryboardError("lesson not found")
    latest = db.scalars(select(VideoStoryboard).where(
        VideoStoryboard.lesson_id == lesson_id
    ).order_by(VideoStoryboard.version.desc())).first()
    storyboard = VideoStoryboard(
        lesson_id=lesson.id,
        lesson_version=lesson.current_version,
        event_id=lesson.event_id,
        version=(latest.version + 1) if latest else 1,
        title=title or lesson.title,
        scenes=scenes,
        status=DRAFT,
    )
    db.add(storyboard)
    db.flush()
    return storyboard


def approve_storyboard(db: Session, storyboard_id: int, user_id: int) -> VideoStoryboard:
    """Approval gate — refuses while any grounding/completeness problem remains."""
    storyboard = db.get(VideoStoryboard, storyboard_id)
    if not storyboard:
        raise StoryboardError("storyboard not found")
    problems = validate_scenes(db, storyboard.scenes or [], lesson_id=storyboard.lesson_id)
    if problems:
        raise StoryboardError("; ".join(problems))
    storyboard.status = APPROVED
    storyboard.approved_by_user_id = user_id
    storyboard.approved_at = datetime.now(timezone.utc)
    db.flush()
    return storyboard


def assert_renderable(db: Session, storyboard_id: int) -> VideoStoryboard:
    """The gate the render job calls: no approval, no render."""
    storyboard = db.get(VideoStoryboard, storyboard_id)
    if not storyboard:
        raise StoryboardError("storyboard not found")
    if storyboard.status != APPROVED:
        raise StoryboardError(
            f"storyboard {storyboard_id} is {storyboard.status!r}; approve it before rendering"
        )
    return storyboard


def start_render(db: Session, storyboard_id: int, spec_hash: str = "") -> VideoRender:
    """Open a new, versioned render for an approved storyboard (never overwrites a prior one)."""
    storyboard = assert_renderable(db, storyboard_id)
    latest = db.scalars(select(VideoRender).where(
        VideoRender.storyboard_id == storyboard.id
    ).order_by(VideoRender.version.desc())).first()
    render = VideoRender(
        storyboard_id=storyboard.id,
        version=(latest.version + 1) if latest else 1,
        status="queued",
        spec_hash=spec_hash,
        provenance={
            "lesson_id": storyboard.lesson_id,
            "lesson_version": storyboard.lesson_version,
            "storyboard_version": storyboard.version,
        },
    )
    db.add(render)
    db.flush()
    return render
