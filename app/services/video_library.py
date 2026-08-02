"""Phase V — what students and reviewers actually see.

A render existing is not the same as a render being watchable. Two rules govern this layer:

  * students only ever see renders that passed post-render QA — a storyboard can be approved
    and the resulting video still be wrong (bad pacing, a caption drifting, a wrong frame),
    so the video itself is reviewed before anyone learns from it;
  * playback links are minted per request, because signed URLs expire and a withdrawn video
    should stop being reachable.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Lesson, VideoRender, VideoStoryboard
from app.services import media_storage
from app.services.video_chapters import plan_chapters

QA_PENDING = "pending"
QA_APPROVED = "approved"
QA_REJECTED = "rejected"
QA_DECISIONS = {QA_APPROVED, QA_REJECTED}


class VideoLibraryError(ValueError):
    pass


def _slug_chapter(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def _latest_per_chapter(renders: list[VideoRender]) -> list[VideoRender]:
    """Renders are versioned; a chapter shows its newest successful render."""
    newest: dict[str, VideoRender] = {}
    for render in renders:
        current = newest.get(render.chapter)
        if current is None or render.version > current.version:
            newest[render.chapter] = render
    return sorted(newest.values(), key=lambda r: (r.id))


def lesson_chapters(db: Session, lesson_id: int, *, include_pending: bool = False) -> list[dict]:
    """Watchable chapters for a lesson, newest render per chapter, in storyboard order."""
    storyboard = db.scalars(
        select(VideoStoryboard)
        .where(VideoStoryboard.lesson_id == lesson_id)
        .order_by(VideoStoryboard.version.desc())
    ).first()
    if not storyboard:
        return []

    query = select(VideoRender).where(
        VideoRender.storyboard_id == storyboard.id,
        VideoRender.status == "succeeded",
    )
    if not include_pending:
        query = query.where(VideoRender.qa_status == QA_APPROVED)
    renders = _latest_per_chapter(db.scalars(query).all())

    # Rebuild the chapter plan the render was made from, rather than reading a `chapter`
    # label off each scene. Scenes only carry that label when an author wrote one; when they
    # don't, `plan_chapters` groups by duration budget and names the chapter after its first
    # scene — which is how every pilot render was made. Reading the absent label instead left
    # every chapter with no blocks, so the reader had no idea which sections a video covered
    # and could not interleave them. The plan is deterministic on the scenes, and
    # `render_lesson` derives `render.chapter` from the same call, so the keys line up.
    order, blocks_by_chapter, titles = {}, {}, {}
    for position, chapter in enumerate(plan_chapters(list(storyboard.scenes or []))):
        key = chapter["key"]
        order[key], titles[key] = position, chapter["title"]
        blocks_by_chapter[key] = [i for scene in chapter["scenes"]
                                  for i in (scene.get("block_indexes") or [])
                                  if isinstance(i, int)]

    def sort_key(render: VideoRender) -> tuple:
        return (order.get(render.chapter, len(order)), render.id)

    out = []
    links = media_storage.playback_urls([r.video_key for r in renders])
    for render in sorted(renders, key=sort_key):
        out.append({
            "render_id": render.id,
            "chapter": render.chapter,
            # A render made before chaptering has no chapter key; it is the whole lesson.
            "title": (titles.get(render.chapter)
                      or (render.provenance or {}).get("chapter_title")
                      or (render.chapter.replace("-", " ").title() if render.chapter
                          else "Full lesson")),
            "duration_seconds": render.duration_seconds,
            "version": render.version,
            "qa_status": render.qa_status,
            "block_indexes": sorted(set(blocks_by_chapter.get(render.chapter, []))),
            "playback_url": links.get(render.video_key, ""),
        })
    return out


def review_queue(db: Session, *, status: str = QA_PENDING, limit: int = 50) -> list[dict]:
    """Successful renders awaiting a human watching them."""
    renders = db.scalars(
        select(VideoRender)
        .where(VideoRender.status == "succeeded", VideoRender.qa_status == status)
        .order_by(VideoRender.id.desc())
        .limit(limit)
    ).all()
    boards = {b.id: b for b in db.scalars(select(VideoStoryboard).where(
        VideoStoryboard.id.in_({r.storyboard_id for r in renders} or {-1}))).all()}
    lessons = {l.id: l for l in db.scalars(select(Lesson).where(
        Lesson.id.in_({b.lesson_id for b in boards.values()} or {-1}))).all()}
    links = media_storage.playback_urls([r.video_key for r in renders])

    out = []
    for render in renders:
        storyboard = boards.get(render.storyboard_id)
        lesson = lessons.get(storyboard.lesson_id) if storyboard else None
        out.append({
            "render_id": render.id,
            "chapter": render.chapter,
            "version": render.version,
            "duration_seconds": render.duration_seconds,
            "qa_status": render.qa_status,
            "qa_notes": render.qa_notes or [],
            "storyboard_id": render.storyboard_id,
            "storyboard_title": storyboard.title if storyboard else "",
            "lesson_id": lesson.id if lesson else None,
            "lesson_title": lesson.title if lesson else "",
            "scenes": (render.provenance or {}).get("scenes"),
            "playback_url": links.get(render.video_key, ""),
        })
    return out


def record_qa(db: Session, render_id: int, decision: str, notes: list[dict], user_id: int) -> VideoRender:
    """Approve a render for students, or reject it with scene/timestamp-anchored notes.

    Rejection is not a dead end: the notes are what the author edits the storyboard against
    before rendering again, which is why they are kept on the render.
    """
    if decision not in QA_DECISIONS:
        raise VideoLibraryError(f"decision must be one of {sorted(QA_DECISIONS)}")
    render = db.get(VideoRender, render_id)
    if not render:
        raise VideoLibraryError("render not found")
    if render.status != "succeeded":
        raise VideoLibraryError(f"cannot review a render that is {render.status!r}")
    if decision == QA_REJECTED and not notes:
        raise VideoLibraryError("rejection requires at least one note explaining what to fix")

    render.qa_status = decision
    render.qa_notes = [
        {
            "scene": note.get("scene"),
            "at_seconds": note.get("at_seconds"),
            "note": str(note.get("note", "")).strip(),
            "by_user_id": user_id,
        }
        for note in (notes or [])
        if str(note.get("note", "")).strip()
    ]
    db.flush()
    return render
