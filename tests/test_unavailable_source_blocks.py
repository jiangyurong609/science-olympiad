"""A student holds the lesson, never the source packet it was written from.

Six pilot checkpoints assess students on material they were never given — "which statement
best follows from the source packet?", "in the source's 1500 C solid-solution example…". That
is the same defect as a question referring to a figure that was never imported: the item is
unanswerable, and nothing flagged it.
"""
from __future__ import annotations

import pytest

from app.services.course_quality import blocks_citing_an_unavailable_source


@pytest.mark.parametrize("text", [
    "Which statement best follows from the source packet?",
    "In the source's 1500 C solid-solution example, which proportions are accepted?",
    "Which identification from the provided stations best matches that clue?",
    "According to the source, what explains the rainbow colours?",
])
def test_a_reference_to_unavailable_material_is_flagged(text):
    found = blocks_citing_an_unavailable_source([{"type": "checkpoint", "prompt": text}])
    assert len(found) == 1
    assert found[0]["assessed"] is True


@pytest.mark.parametrize("text", [
    "This lesson trains you to identify minerals by repeatable properties.",
    "The lesson shows how to read Bowen's series from hot to cool.",
    "By the end of this part you will separate chalk from dolostone.",
])
def test_normal_pedagogical_voice_is_not_flagged(text):
    """"This lesson shows…" is how a lesson talks about itself, not a dangling reference."""
    assert blocks_citing_an_unavailable_source([{"type": "opening", "body": text}]) == []


def test_the_content_inside_lists_is_searched():
    """Checkpoint choices live in a list; searching only top-level strings missed them —
    the same oversight that made the grounding matcher read headings alone."""
    block = {"type": "checkpoint", "heading": "Checkpoint",
             "choices": ["A sulfate, per the source packet", "A carbonate"]}
    assert len(blocks_citing_an_unavailable_source([block])) == 1


def test_a_teaching_block_is_flagged_but_not_marked_assessed():
    """It should be rewritten, but it is not scoring anyone."""
    found = blocks_citing_an_unavailable_source(
        [{"type": "property_cards", "body": "In the source, barite is BaSO4."}])
    assert len(found) == 1 and found[0]["assessed"] is False


def test_position_and_heading_are_reported_so_a_reviewer_can_find_it():
    found = blocks_citing_an_unavailable_source([
        {"type": "opening", "body": "Clean."},
        {"type": "checkpoint", "heading": "Acid Clues",
         "prompt": "Which item from the source packet fizzes?"},
    ])
    assert found[0]["position"] == 2
    assert found[0]["heading"] == "Acid Clues"


def test_clean_content_produces_nothing():
    assert blocks_citing_an_unavailable_source(
        [{"type": "summary", "points": ["Streak is more reliable than colour."]}]) == []


def test_an_archived_original_does_not_keep_flagging_a_repaired_block():
    """`superseded` keeps the pre-repair block so a reviewer can diff it. Searching that
    archive would report a defect that has already been fixed."""
    repaired = {
        "type": "checkpoint",
        "question": "A barite specimen does nothing in acid. Which statement fits?",
        "choices": ["It is a sulfate", "It is a carbonate"],
        "correct_index": 0,
        "repaired_by": "repair_dangling_checkpoints",
        "superseded": {"type": "checkpoint",
                       "question": "Which statement best follows from the source packet?"},
    }
    assert blocks_citing_an_unavailable_source([repaired]) == []


def test_a_block_that_still_dangles_is_flagged_even_if_it_has_an_archive():
    still_bad = {
        "type": "checkpoint",
        "question": "According to the source, which mineral fizzes?",
        "repaired_by": "repair_dangling_checkpoints",
        "superseded": {"question": "old"},
    }
    assert len(blocks_citing_an_unavailable_source([still_bad])) == 1


# ---------------------------------------------------- figures the lesson never shows

def test_a_block_reading_from_a_figure_the_part_lacks_is_flagged():
    """`is_figure_missing` protects exam items; lessons had no equivalent. The pilot holds
    the exact failure — a worked example reading a diagram the part never shows, and a
    checkpoint assessing that reading."""
    from app.services.course_quality import blocks_referencing_absent_media
    content = [
        {"type": "worked_example", "heading": "Lever rule",
         "body": "In the diagram above, read the tie-line at 1500 C."},
        {"type": "checkpoint", "heading": "Result",
         "question": "From the diagram, which proportions are given?"},
    ]
    found = blocks_referencing_absent_media(content)
    assert len(found) == 2
    assert [b["assessed"] for b in found] == [False, True]


def test_a_part_that_actually_shows_the_figure_is_not_flagged():
    from app.services.course_quality import blocks_referencing_absent_media
    content = [
        {"type": "image_gallery", "heading": "Solid-solution diagram"},
        {"type": "checkpoint", "question": "From the diagram, which proportions are given?"},
    ]
    assert blocks_referencing_absent_media(content) == []


def test_an_attached_asset_counts_as_showing_it():
    from app.services.course_quality import blocks_referencing_absent_media
    content = [
        {"type": "property_cards", "assets": [{"kind": "figure", "storage_key": "k"}]},
        {"type": "checkpoint", "question": "In the figure above, which mineral is shown?"},
    ]
    assert blocks_referencing_absent_media(content) == []


def test_text_only_content_is_not_flagged():
    from app.services.course_quality import blocks_referencing_absent_media
    content = [{"type": "summary", "points": ["Streak beats colour for identification."]}]
    assert blocks_referencing_absent_media(content) == []
