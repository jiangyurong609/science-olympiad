"""Phase V — chapter planning and chaptered rendering."""
from __future__ import annotations

import pytest

from app.services.video_chapters import (
    DEFAULT_CHAPTER_SECONDS, chapter_summary, estimate_render_wall_seconds,
    estimate_scene_seconds, plan_chapters,
)


def _scene(words: int, **over):
    base = {"headline": "H", "narration": " ".join(["word"] * words)}
    base.update(over)
    return base


def test_scene_duration_is_estimated_from_narration_length():
    short, long = estimate_scene_seconds(_scene(13)), estimate_scene_seconds(_scene(130))
    assert long > short
    assert estimate_scene_seconds(_scene(0)) == 2.0     # never below the readable minimum


def test_wall_clock_projection_uses_measured_ratio():
    # measured on a real render: ~2.4s wall per second of video
    assert estimate_render_wall_seconds(300) == pytest.approx(720, abs=1)


def test_explicit_chapter_labels_are_authoritative():
    scenes = [
        _scene(20, chapter="Roles"), _scene(20, chapter="Roles"),
        _scene(20, chapter="Efficiency"), _scene(20, chapter="Efficiency"),
        _scene(20, chapter="Recap"),
    ]
    chapters = plan_chapters(scenes)
    assert [c["title"] for c in chapters] == ["Roles", "Efficiency", "Recap"]
    assert [len(c["scenes"]) for c in chapters] == [2, 2, 1]


def test_unlabelled_scenes_are_packed_to_the_budget():
    # each scene ~40s of narration; a 120s budget should fit three per chapter
    scenes = [_scene(100) for _ in range(7)]
    chapters = plan_chapters(scenes, max_seconds=120)
    assert len(chapters) > 1
    for chapter in chapters:
        assert chapter["estimated_seconds"] <= 120 or len(chapter["scenes"]) == 1


def test_one_oversized_scene_becomes_its_own_flagged_chapter():
    # splitting mid-narration would cut a sentence, so it renders alone and is flagged
    chapters = plan_chapters([_scene(2000)], max_seconds=120)
    assert len(chapters) == 1
    assert chapters[0]["over_budget"] is True
    assert chapter_summary(chapters)["over_budget"] == [chapters[0]["key"]]


def test_scene_indexes_restart_within_each_chapter():
    chapters = plan_chapters([_scene(10, chapter="A"), _scene(10, chapter="A"),
                              _scene(10, chapter="B")])
    assert [s["index"] for s in chapters[0]["scenes"]] == [1, 2]
    assert [s["index"] for s in chapters[1]["scenes"]] == [1]


def test_duplicate_titles_get_unique_keys():
    # keys address a render target, so collisions would overwrite one another
    chapters = plan_chapters([_scene(10, chapter="Recap"), _scene(10, chapter="Other"),
                              _scene(10, chapter="Recap")])
    keys = [c["key"] for c in chapters]
    assert len(keys) == len(set(keys))


def test_summary_reports_totals():
    chapters = plan_chapters([_scene(50, chapter="A"), _scene(50, chapter="B")])
    summary = chapter_summary(chapters)
    assert summary["chapters"] == 2
    assert summary["total_video_seconds"] > 0
    assert summary["over_budget"] == []


def test_default_budget_stays_inside_the_worker_timeout():
    # the worker's internal cap is 15 minutes; a full-budget chapter must project under it
    assert estimate_render_wall_seconds(DEFAULT_CHAPTER_SECONDS) < 15 * 60


def test_empty_storyboard_plans_nothing():
    assert plan_chapters([]) == []
