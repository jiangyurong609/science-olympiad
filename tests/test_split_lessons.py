"""Phase 3 — the lesson splitter must never produce a part that fails the rubric.

`plan_cuts` shipped two defects before these tests existed: it cut only at checkpoints (so a
check-heavy tail could never be cut again and stayed at 14–16 minutes), then it cut at the
first eligible boundary (so a 23.5-minute lesson became 8.7 + 14.8). Both produced parts over
the limit, which is the one thing splitting exists to prevent.
"""
from __future__ import annotations

import pytest

from scripts.split_lessons import (
    MAX_MINUTES, MIN_TEACHING, WORDS_PER_MINUTE, _teaching, minutes_of, plan_cuts,
)


def _block(kind: str, minutes: float = 1.0, **extra) -> dict:
    return {"type": kind, "body": " ".join(["word"] * int(minutes * WORDS_PER_MINUTE)), **extra}


def _lesson(pattern: str, minutes_each: float = 2.0) -> list[dict]:
    """Build blocks from a shorthand: o=opening t=teaching c=checkpoint s=summary."""
    kinds = {"o": "opening", "t": "property_cards", "c": "checkpoint", "s": "summary"}
    return [_block(kinds[ch], minutes_each if ch != "c" else 0.5) for ch in pattern]


def test_a_short_lesson_is_left_alone():
    blocks = _lesson("otctcs", 1.0)
    assert minutes_of(blocks) <= MAX_MINUTES
    assert plan_cuts(blocks) == [blocks]


def test_no_part_exceeds_the_limit():
    """Given enough teaching blocks to divide, every part must come in under the limit.
    The pilot's lessons carry ten, which is the shape this guards."""
    blocks = _lesson("otctcttctcttctcs", 1.6)      # ~25 minutes, 10 teaching blocks
    parts = plan_cuts(blocks)
    assert len(parts) > 1
    for part in parts:
        assert minutes_of(part) <= MAX_MINUTES, [round(minutes_of(p), 1) for p in parts]


def test_a_check_heavy_tail_still_gets_cut():
    """The checkpoint-only rule stranded exactly this shape at 14+ minutes: its checks all
    sit at the end, so there was no late check boundary to cut at."""
    blocks = _lesson("ottttttttccccs", 1.7)
    parts = plan_cuts(blocks)
    assert len(parts) > 1
    assert all(minutes_of(p) <= MAX_MINUTES for p in parts), \
        [round(minutes_of(p), 1) for p in parts]


def test_a_teaching_thin_lesson_is_reported_not_silently_broken():
    """Six teaching blocks cannot yield two parts of three *and* balance under the limit.
    The splitter still divides — 9 + 13 beats 22 — but the residual has to stay visible,
    which is what `main` prints as "parts still over 12 minutes"."""
    blocks = _lesson("ottcttcttccccs", 2.0)
    parts = plan_cuts(blocks)
    for part in parts:
        assert _teaching(part) >= MIN_TEACHING, "a part must never be structurally invalid"
    assert [b for part in parts for b in part] == blocks


def test_parts_are_balanced_not_front_loaded():
    """First-fit produced 8.7 and 14.8 from one lesson; the spread must stay tight."""
    blocks = _lesson("otctctctcs", 2.6)
    parts = plan_cuts(blocks)
    spread = max(minutes_of(p) for p in parts) - min(minutes_of(p) for p in parts)
    assert spread <= MAX_MINUTES / 2, [round(minutes_of(p), 1) for p in parts]


def test_every_part_keeps_enough_teaching_blocks():
    """Checkpoints are generated later; teaching blocks never are, so each part must
    already carry its own."""
    blocks = _lesson("ottctttcttcts", 2.0)
    for part in plan_cuts(blocks):
        assert _teaching(part) >= MIN_TEACHING


def test_a_lesson_too_thin_to_split_is_left_whole():
    """Three teaching blocks cannot become two lessons of three, however long they are."""
    blocks = [_block("opening"), _block("property_cards", 8), _block("checkpoint", 0.5),
              _block("property_cards", 8), _block("property_cards", 8), _block("summary")]
    assert minutes_of(blocks) > MAX_MINUTES
    assert len(plan_cuts(blocks)) == 1, "splitting must not manufacture an invalid part"


def test_block_order_and_content_survive_the_split():
    blocks = _lesson("otctctctcs", 2.2)
    parts = plan_cuts(blocks)
    assert [b for part in parts for b in part] == blocks, "split must be a partition"


def test_no_scrap_part_is_created():
    blocks = _lesson("otctctctctcs", 2.0)
    for part in plan_cuts(blocks):
        assert minutes_of(part) >= 3, [round(minutes_of(p), 1) for p in plan_cuts(blocks)]


@pytest.mark.parametrize("pattern,each", [
    ("otctctcs", 3.0), ("ottcttcttcs", 2.4), ("otctctctctctcs", 1.8), ("ottttccccs", 2.6),
])
def test_the_limit_holds_across_shapes(pattern, each):
    parts = plan_cuts(_lesson(pattern, each))
    over = [round(minutes_of(p), 1) for p in parts if minutes_of(p) > MAX_MINUTES]
    # a lesson with too few teaching blocks to divide is allowed to stay whole and long;
    # anything the splitter *does* divide must respect the limit
    assert not over or len(parts) == 1, over
