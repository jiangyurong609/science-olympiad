"""The lesson sequence must lead each section with its chapter video.

This mirrors the browser's buildLessonSteps() so a regression in the ordering contract is
caught here rather than by a person clicking Continue sixteen times.
"""
from __future__ import annotations


def build_steps(block_count: int, chapters: list[dict]) -> list[dict]:
    """Port of buildLessonSteps(): a chapter opens the first section it covers."""
    steps = []
    for index in range(block_count):
        opener = next((c for c in chapters if (c.get("block_indexes") or [None])[0] == index), None)
        if opener:
            steps.append({"kind": "video", "chapter": opener["chapter"], "blockIndex": index})
        steps.append({"kind": "block", "blockIndex": index})
    return steps


CHAPTERS = [
    {"chapter": "what-an-ecosystem-is", "block_indexes": [0, 1, 2]},
    {"chapter": "drawing-the-boundary", "block_indexes": [3, 5]},
    {"chapter": "condition-and-processes", "block_indexes": [6, 7]},
    {"chapter": "why-people-depend-on-it", "block_indexes": [10, 11]},
]


def test_every_chapter_appears_as_a_step():
    steps = build_steps(16, CHAPTERS)
    videos = [s["chapter"] for s in steps if s["kind"] == "video"]
    assert videos == [c["chapter"] for c in CHAPTERS], "no chapter may be dropped from the sequence"


def test_each_video_immediately_precedes_the_section_it_opens():
    steps = build_steps(16, CHAPTERS)
    for i, step in enumerate(steps):
        if step["kind"] == "video":
            following = steps[i + 1]
            assert following["kind"] == "block"
            assert following["blockIndex"] == step["blockIndex"], "video must lead its own section"


def test_a_chapter_opens_once_even_when_it_covers_several_sections():
    steps = build_steps(16, CHAPTERS)
    opens = [s for s in steps if s["kind"] == "video" and s["chapter"] == "what-an-ecosystem-is"]
    assert len(opens) == 1, "a chapter covering 3 sections must not appear 3 times"


def test_every_section_is_still_reachable():
    steps = build_steps(16, CHAPTERS)
    read = [s["blockIndex"] for s in steps if s["kind"] == "block"]
    assert read == list(range(16)), "no reading section may be skipped by the video steps"


def test_sequence_without_chapters_is_just_the_reading():
    assert build_steps(4, []) == [{"kind": "block", "blockIndex": i} for i in range(4)]
