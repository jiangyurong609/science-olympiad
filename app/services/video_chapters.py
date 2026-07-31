"""Phase V — split a lesson storyboard into independently rendered chapters.

Measured throughput is roughly 2.4 seconds of wall clock per second of video, against a
render worker whose internal timeout is 15 minutes. A single render therefore tops out
around a five-minute video, which is also about as long as a student will watch one clip.

So a full lesson is rendered as several per-sub-topic chapters rather than one long file:
each fits comfortably inside the timeout, they render in parallel, and one failure costs a
chapter instead of the whole lesson.
"""
from __future__ import annotations

import re

# Aura speaks at roughly this rate; used only to plan chapter boundaries before synthesis.
WORDS_PER_SECOND = 2.6
SCENE_TAIL_SECONDS = 0.6
MIN_SCENE_SECONDS = 2.0
# Keep a chapter well inside the worker's 15-minute cap at ~2.4x wall-per-video-second.
DEFAULT_CHAPTER_SECONDS = 300.0


def estimate_scene_seconds(scene: dict) -> float:
    words = len(re.findall(r"\S+", str(scene.get("narration", ""))))
    return max(MIN_SCENE_SECONDS, round(words / WORDS_PER_SECOND + SCENE_TAIL_SECONDS, 2))


def estimate_render_wall_seconds(video_seconds: float, ratio: float = 2.4) -> float:
    """Projected wall clock for a render, so we can refuse one that would time out."""
    return round(video_seconds * ratio, 1)


def _slug(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug or fallback


def plan_chapters(
    scenes: list[dict],
    max_seconds: float = DEFAULT_CHAPTER_SECONDS,
) -> list[dict]:
    """Group scenes into chapters.

    An explicit `chapter` label on a scene is authoritative — that is the author saying
    where a sub-topic begins. Unlabelled scenes are packed by duration budget instead.
    A single scene longer than the budget becomes its own chapter and is flagged, since
    splitting mid-narration would cut a sentence in half.
    """
    if not scenes:
        return []

    labelled = any(str(scene.get("chapter", "")).strip() for scene in scenes)
    chapters: list[dict] = []
    current: dict | None = None

    for index, scene in enumerate(scenes, start=1):
        seconds = estimate_scene_seconds(scene)
        label = str(scene.get("chapter", "")).strip()

        if labelled:
            start_new = current is None or label != current["title"]
        else:
            start_new = current is None or current["estimated_seconds"] + seconds > max_seconds

        if start_new:
            title = label or str(scene.get("headline", "")) or f"Chapter {len(chapters) + 1}"
            current = {
                "key": _slug(title, f"chapter-{len(chapters) + 1}"),
                "title": title,
                "scenes": [],
                "estimated_seconds": 0.0,
                "over_budget": False,
            }
            chapters.append(current)

        current["scenes"].append({**scene, "index": len(current["scenes"]) + 1})
        current["estimated_seconds"] = round(current["estimated_seconds"] + seconds, 2)

    seen: dict[str, int] = {}
    for chapter in chapters:
        chapter["over_budget"] = chapter["estimated_seconds"] > max_seconds
        chapter["estimated_wall_seconds"] = estimate_render_wall_seconds(chapter["estimated_seconds"])
        key = chapter["key"]
        if key in seen:                      # keys address a render; they must be unique
            seen[key] += 1
            chapter["key"] = f"{key}-{seen[key]}"
        else:
            seen[key] = 1
    return chapters


def chapter_summary(chapters: list[dict]) -> dict:
    return {
        "chapters": len(chapters),
        "total_video_seconds": round(sum(c["estimated_seconds"] for c in chapters), 2),
        "longest_chapter_seconds": round(max((c["estimated_seconds"] for c in chapters), default=0.0), 2),
        "over_budget": [c["key"] for c in chapters if c["over_budget"]],
    }
