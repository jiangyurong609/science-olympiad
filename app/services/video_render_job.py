"""Phase V — end-to-end render: approved storyboard → narrated, captioned MP4.

Chains the pieces in the order the plan specifies, refusing at each gate rather than
producing something a student should not see:

    approved storyboard → narrate each scene (Deepgram) → upload audio
                        → render slides (SVG) → upload slides
                        → build + validate EditSpec → render on the worker → record provenance

The whole call blocks for the length of the render, so this belongs in a background job.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.models.entities import VideoRender
from app.services import media_storage, video_storyboard as sb
from app.services.tts_deepgram import DeepgramNarrator
from app.services.video_editspec import build_edit_spec, total_duration
from app.services.video_slides import render_scene_svg
from app.services.video_worker import RemotionRenderClient


def spec_fingerprint(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def render_storyboard(
    db: Session,
    storyboard_id: int,
    *,
    narrator: DeepgramNarrator | None = None,
    client: RemotionRenderClient | None = None,
    storage=media_storage,
) -> VideoRender:
    """Produce one MP4 for an approved storyboard. Collaborators are injectable so the
    pipeline can be exercised without spending a render."""
    storyboard = sb.assert_renderable(db, storyboard_id)   # gate: approval required
    narrator = narrator or DeepgramNarrator()
    client = client or RemotionRenderClient()
    if not narrator.configured:
        raise sb.StoryboardError("Deepgram is not configured; cannot narrate")
    if not client.configured:
        raise sb.StoryboardError("video_render_worker_url is not configured")

    render = sb.start_render(db, storyboard.id)
    render.status = "rendering"
    db.flush()

    try:
        scenes, audio_keys, slide_keys = [], [], []
        for index, scene in enumerate(storyboard.scenes or [], start=1):
            narration = narrator.narrate(scene.get("narration", ""))
            audio = storage.upload_media(
                storage.render_key(storyboard.id, render.version, f"scene-{index}.mp3"),
                narration.audio, "audio/mpeg",
            )
            slide_svg = render_scene_svg({**scene, "index": index})
            slide = storage.upload_media(
                storage.render_key(storyboard.id, render.version, f"scene-{index}.svg"),
                slide_svg.encode("utf-8"), "image/svg+xml",
            )
            audio_keys.append(audio.key)
            slide_keys.append(slide.key)
            scenes.append({
                "slide_url": slide.url,
                "audio_url": audio.url,
                "headline": scene.get("headline", ""),
                "words": narration.words,
            })

        spec = build_edit_spec(scenes)          # validated on the way out
        target = storage.signed_upload_url(
            storage.render_key(storyboard.id, render.version, "lesson.mp4")
        )
        result = client.render(spec, upload_url=target.url)

        render.status = "succeeded"
        render.spec_hash = spec_fingerprint(spec)
        render.duration_seconds = total_duration(spec)
        render.audio_keys = audio_keys
        render.slide_keys = slide_keys
        render.video_key = target.key
        render.provenance = {
            **(render.provenance or {}),
            "scenes": len(scenes),
            "bytes": result.bytes_written,
            "tts_model": narrator.model,
        }
    except Exception as exc:
        render.status = "failed"
        render.error = f"{type(exc).__name__}: {exc}"[:2000]
        db.commit()
        raise
    db.commit()
    # commit expires the instance; reload it so callers can read the result after the
    # session closes instead of hitting DetachedInstanceError.
    db.refresh(render)
    return render
