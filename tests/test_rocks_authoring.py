import json
from pathlib import Path

import pytest

from app.models.entities import Source, SourcePassage
from scripts.author_rocks_vertical_slice import (
    BLUEPRINT_PATH, _normalize_blocks, _select_passages,
)
from scripts.author_skill_questions import _validate_item
from scripts.import_course_manifest import (
    _blocks as import_blocks,
    _verify_manifest,
)


def valid_lesson_payload():
    teaching = [
        {
            "type": "property_cards", "heading": "Properties", "body": "Compare.",
            "cards": [{"name": "Streak", "cue": "Powder", "detail": "Observe."}],
            "passage_ids": [1],
        },
        {
            "type": "steps", "heading": "Test",
            "steps": [{"label": "Observe", "detail": "Record evidence."}],
            "passage_ids": [1],
        },
        {
            "type": "worked_example", "heading": "Example", "prompt": "Unknown",
            "steps": ["Observe.", "Test.", "Conclude."], "passage_ids": [2],
        },
    ]
    checks = [{
        "type": "checkpoint", "id": f"raw-{index}", "heading": "Check",
        "question": f"Which evidence is most useful in case {index}?",
        "choices": ["A", "B", "C", "D"], "correct_index": 0,
        "explanation": "A uses the diagnostic evidence.",
        "misconception_by_choice": {
            "1": "B relies on color alone.",
            "2": "C skips the test.",
            "3": "D overstates the evidence.",
        },
        "cognitive_level": "transfer" if index == 3 else "application",
        "passage_ids": [1, 2],
    } for index in range(1, 4)]
    return {
        "blocks": [
            {"type": "opening", "kicker": "Goal", "heading": "Learn", "body": "You can test."},
            teaching[0], checks[0], teaching[1], checks[1], teaching[2], checks[2],
            {"type": "summary", "heading": "Recap", "points": ["Use evidence."], "next_step": "Practice."},
        ]
    }


def test_rocks_blueprint_has_complete_unit_lesson_structure():
    blueprint = json.loads(Path(BLUEPRINT_PATH).read_text())
    assert blueprint["event_slug"] == "rocks-and-minerals-b-2027"
    assert len(blueprint["units"]) == 6
    lessons = [lesson for unit in blueprint["units"] for lesson in unit["lessons"]]
    assert len(lessons) == 14
    assert all(2 <= len(unit["lessons"]) <= 3 for unit in blueprint["units"])
    assert len({lesson["slug"] for lesson in lessons}) == len(lessons)
    assert all(lesson["objective"] and lesson["keywords"] for lesson in lessons)


def test_lesson_normalizer_enforces_citations_checks_and_transfer():
    blocks = _normalize_blocks(valid_lesson_payload(), {1, 2}, "hardness")
    checks = [block for block in blocks if block["type"] == "checkpoint"]
    assert [block["id"] for block in checks] == [
        "hardness-check-1", "hardness-check-2", "hardness-check-3",
    ]
    assert all(block["passage_ids"] for block in checks)

    invalid = valid_lesson_payload()
    invalid["blocks"][1]["passage_ids"] = [999]
    with pytest.raises(ValueError, match="no valid passage citation"):
        _normalize_blocks(invalid, {1, 2}, "hardness")


def test_passage_selection_searches_all_passages_and_prioritizes_diverse_sources():
    sources = {
        1: Source(id=1, url="https://example.org/a", title="Mohs Hardness Guide"),
        2: Source(id=2, url="https://example.org/b", title="Mineral Properties"),
    }
    passages = [
        SourcePassage(
            id=1, source_id=1, source_snapshot_id=1, sequence=1,
            locator="Page 1", passage_type="pdf_page",
            text="The Mohs scale compares scratch hardness.", content_hash="a",
        ),
        SourcePassage(
            id=2, source_id=1, source_snapshot_id=1, sequence=2,
            locator="Page 2", passage_type="pdf_page",
            text="A scratch should be checked carefully.", content_hash="b",
        ),
        SourcePassage(
            id=3, source_id=2, source_snapshot_id=2, sequence=1,
            locator="Page 4", passage_type="pdf_page",
            text="Glass and copper can bracket hardness.", content_hash="c",
        ),
    ]
    selected = _select_passages(
        passages, sources, ["Mohs", "hardness", "scratch", "glass"], require_video=False,
    )
    assert {row.source_id for row in selected} == {1, 2}
    assert {row.id for row in selected} == {1, 2, 3}


def test_question_validator_requires_exact_evidence_and_choice_feedback():
    passage = SourcePassage(
        id=9, source_id=1, source_snapshot_id=2, sequence=1,
        locator="Page 3", passage_type="pdf_page",
        text="A mineral's streak is the color of its powdered form.",
        content_hash="p",
    )
    raw = {
        "stem": "Which observation records the color of a mineral in powdered form?",
        "choices": ["Streak", "Luster", "Hardness", "Cleavage"],
        "correct_index": 0,
        "explanation": "Streak observes the powdered mineral.",
        "rationale_by_choice": {
            "0": "Streak is the powdered color.", "1": "Luster describes reflected light.",
            "2": "Hardness measures scratch resistance.", "3": "Cleavage describes breakage.",
        },
        "misconception_by_choice": {
            "1": "Confuses reflected light with powder color.",
            "2": "Confuses scratch resistance with powder color.",
            "3": "Confuses breakage with powder color.",
        },
        "cognitive_level": "application", "difficulty": 0.3,
        "estimated_seconds": 60, "passage_id": 9,
        "claim_text": "Streak describes the color of a mineral's powdered form.",
        "evidence_excerpt": "streak is the color of its powdered form",
    }
    result = _validate_item(raw, {9: passage})
    assert result["passage_id"] == 9
    assert result["rationale_by_choice"]["3"].startswith("Cleavage")
    raw["rationale_by_choice"] = [
        "Streak is the powdered color.", "Luster describes reflected light.",
        "Hardness measures scratch resistance.", "Cleavage describes breakage.",
    ]
    assert _validate_item(raw, {9: passage})["rationale_by_choice"]["0"].startswith("Streak")
    raw["evidence_excerpt"] = "This wording is not in the retained source."
    with pytest.raises(ValueError, match="not present"):
        _validate_item(raw, {9: passage})


def test_manifest_verification_rejects_tampering_and_student_release():
    payload = {
        "schema_version": 1,
        "student_release": False,
        "course": {"slug": "rocks-and-minerals-b-2027"},
    }
    from scripts.import_course_manifest import _hash

    payload["manifest_hash"] = _hash(payload)
    assert _verify_manifest(payload) == payload["manifest_hash"]

    tampered = {**payload, "student_release": True}
    with pytest.raises(ValueError, match="hash does not match"):
        _verify_manifest(tampered)

    release_payload = {**payload, "student_release": True}
    release_payload.pop("manifest_hash")
    release_payload["manifest_hash"] = _hash(release_payload)
    with pytest.raises(ValueError, match="review-only"):
        _verify_manifest(release_payload)


def test_manifest_blocks_resolve_stable_passage_refs_to_local_ids():
    source = Source(id=3, url="https://example.org/source", title="Source")
    passage = SourcePassage(
        id=91, source_id=3, source_snapshot_id=7, sequence=1,
        locator="Page 1", passage_type="pdf_page",
        text="Minerals have observable properties.", content_hash="hash",
    )
    imported = import_blocks(
        [{"type": "steps", "passage_refs": ["passage:stable"]}],
        {"passage:stable": (source, object(), passage)},
    )
    assert imported == [{"type": "steps", "passage_ids": [91]}]
