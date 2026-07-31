"""Phase V — build and validate the EditSpec v0 consumed by the Remotion render worker.

The worker (see docs/HONEN_GAP_CLOSURE_PLAN.md, Phase V) renders the `VibeEdit` composition
from an EditSpec v0 document. This module turns an *approved* storyboard plus its synthesized
narration into that document, and validates it before we ever spend a render.

Two hard rules encoded here:
  * the worker has no filesystem — every `sourcePath` must be an HTTPS URL it can GET;
  * scene durations are driven by the *actual* narration length, so audio and visuals stay
    locked instead of drifting.
"""
from __future__ import annotations

from typing import Iterable

ASPECTS = {"9:16", "1:1", "16:9"}
DEFAULT_FORMAT = {"aspect": "16:9", "width": 1920, "height": 1080, "fps": 30}
# A slide needs a beat to read after the narration stops before cutting.
SCENE_TAIL_SECONDS = 0.6
MIN_SCENE_SECONDS = 2.0


class EditSpecError(ValueError):
    """Raised when a spec would be rejected by the worker."""


def _is_fetchable(url: object) -> bool:
    return isinstance(url, str) and url.startswith(("http://", "https://"))


def validate_edit_spec(spec: dict) -> dict:
    """Mirror of the worker's Zod gate. Raises EditSpecError; returns the spec on success."""
    if not isinstance(spec, dict):
        raise EditSpecError("spec must be an object")
    if spec.get("version") != 0:
        raise EditSpecError("version must be 0")

    fmt = spec.get("format")
    if not isinstance(fmt, dict):
        raise EditSpecError("format is required")
    if fmt.get("aspect") not in ASPECTS:
        raise EditSpecError(f"format.aspect must be one of {sorted(ASPECTS)}")
    for key in ("width", "height", "fps"):
        if not isinstance(fmt.get(key), int) or fmt[key] <= 0:
            raise EditSpecError(f"format.{key} must be a positive integer")

    clips = spec.get("clips")
    if not isinstance(clips, list) or not clips:
        raise EditSpecError("clips must be a non-empty list")
    seen_ids: set[str] = set()
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            raise EditSpecError(f"clips[{i}] must be an object")
        cid = clip.get("id")
        if not isinstance(cid, str) or not cid:
            raise EditSpecError(f"clips[{i}].id is required")
        if cid in seen_ids:
            raise EditSpecError(f"duplicate clip id {cid!r}")
        seen_ids.add(cid)
        kind = clip.get("sourceKind", "video")
        if kind in ("video", "image"):
            if not _is_fetchable(clip.get("sourcePath")):
                raise EditSpecError(
                    f"clips[{i}].sourcePath must be an http(s) URL the worker can fetch"
                )
        elif kind == "component":
            if not clip.get("componentCode"):
                raise EditSpecError(f"clips[{i}].componentCode required for component clips")
        else:
            raise EditSpecError(f"clips[{i}].sourceKind {kind!r} is not supported")
        in_s, out_s = clip.get("inSeconds", 0), clip.get("outSeconds")
        if not isinstance(in_s, (int, float)) or in_s < 0:
            raise EditSpecError(f"clips[{i}].inSeconds must be >= 0")
        if not isinstance(out_s, (int, float)) or out_s <= in_s:
            raise EditSpecError(f"clips[{i}].outSeconds must be greater than inSeconds")

    for j, ov in enumerate(spec.get("overlays", []) or []):
        if not str(ov.get("text", "")).strip():
            raise EditSpecError(f"overlays[{j}].text must be non-empty")
        pos = ov.get("position") or {}
        for axis in ("x", "y"):
            v = pos.get(axis)
            if not isinstance(v, (int, float)) or not 0 <= v <= 100:
                raise EditSpecError(f"overlays[{j}].position.{axis} must be within 0..100")

    captions = spec.get("captions")
    if captions is not None:
        segments = captions.get("segments")
        if not isinstance(segments, list):
            raise EditSpecError("captions.segments must be a list")
        for k, seg in enumerate(segments):
            if seg.get("endSeconds", 0) <= seg.get("startSeconds", 0):
                raise EditSpecError(f"captions.segments[{k}] has a non-positive duration")

    audio = spec.get("audio") or {}
    for track_name in ("voiceover", "sfx"):
        for m, track in enumerate(audio.get(track_name, []) or []):
            if not _is_fetchable(track.get("sourcePath")):
                raise EditSpecError(f"audio.{track_name}[{m}].sourcePath must be an http(s) URL")
    music = audio.get("music")
    if music is not None and not _is_fetchable(music.get("sourcePath")):
        raise EditSpecError("audio.music.sourcePath must be an http(s) URL")

    return spec


def scene_duration(words: list[dict], tail: float = SCENE_TAIL_SECONDS) -> float:
    """Duration a slide must hold: until its narration finishes, plus a reading beat."""
    if not words:
        return MIN_SCENE_SECONDS
    end = max(float(w.get("endSeconds", 0.0)) for w in words)
    return max(MIN_SCENE_SECONDS, round(end + tail, 3))


def _caption_segments(words: list[dict], offset: float, max_words: int = 7) -> list[dict]:
    """Group word timings into short, readable caption lines anchored on the timeline."""
    segments: list[dict] = []
    for i in range(0, len(words), max_words):
        chunk = words[i:i + max_words]
        if not chunk:
            continue
        segments.append({
            "text": " ".join(str(w.get("text", "")) for w in chunk).strip(),
            "startSeconds": round(offset + float(chunk[0].get("startSeconds", 0.0)), 3),
            "endSeconds": round(offset + float(chunk[-1].get("endSeconds", 0.0)), 3),
            "words": [{
                "text": str(w.get("text", "")),
                "startSeconds": round(offset + float(w.get("startSeconds", 0.0)), 3),
                "endSeconds": round(offset + float(w.get("endSeconds", 0.0)), 3),
            } for w in chunk],
        })
    return segments


def build_edit_spec(
    scenes: Iterable[dict],
    *,
    fmt: dict | None = None,
    caption_style: str = "clean_white",
    transition_seconds: float = 0.4,
) -> dict:
    """Assemble an EditSpec v0 from rendered scenes.

    Each scene is a dict:
        slide_url   — https URL of the rendered slide image (signed GCS)
        audio_url   — https URL of that scene's narration audio
        words       — [{text, startSeconds, endSeconds}] relative to the scene's audio
        headline    — optional on-screen text overlay
    """
    scenes = list(scenes)
    if not scenes:
        raise EditSpecError("at least one scene is required")

    clips, overlays, voiceover, segments = [], [], [], []
    cursor = 0.0
    for index, scene in enumerate(scenes):
        words = scene.get("words") or []
        duration = scene.get("duration") or scene_duration(words)
        clip = {
            "id": f"scene-{index + 1}",
            "sourceKind": "image",
            "sourcePath": scene.get("slide_url"),
            "inSeconds": 0,
            "outSeconds": duration,
            "transform": {"reframe": "contain"},
        }
        if index > 0:
            clip["transitionIn"] = {"type": "fade", "durationInSeconds": transition_seconds}
        clips.append(clip)

        # The slide image already carries its own headline, so a text overlay would double
        # the text and cover the design. Overlays are therefore opt-in per scene.
        headline = (scene.get("headline") or "").strip() if scene.get("overlay") else ""
        if headline:
            overlays.append({
                "id": f"title-{index + 1}",
                "kind": "text",
                "text": headline,
                "stylePreset": "lower_third",
                "animation": "fade",
                "position": {"x": 50, "y": 12, "anchor": "top-center"},
                "startSeconds": round(cursor, 3),
                "durationSeconds": round(min(duration, 3.2), 3),
            })

        if scene.get("audio_url"):
            voiceover.append({
                "sourcePath": scene["audio_url"],
                "startSeconds": round(cursor, 3),
                "trimStartSeconds": 0,
                "gain": 1,
                "fadeInSeconds": 0.05,
                "fadeOutSeconds": 0.15,
            })
        segments.extend(_caption_segments(words, cursor))
        cursor += duration

    spec = {
        "version": 0,
        "format": {**DEFAULT_FORMAT, **(fmt or {})},
        "clips": clips,
        "overlays": overlays,
        "captions": {"stylePreset": caption_style, "fontScale": 1, "segments": segments},
        "audio": {"voiceover": voiceover, "sfx": [], "keepOriginalAudio": False},
    }
    return validate_edit_spec(spec)


def total_duration(spec: dict) -> float:
    return round(sum(c["outSeconds"] - c.get("inSeconds", 0) for c in spec["clips"]), 3)
