"""An outside reviewer's corrections must reach the author, in either file shape.

The loader called `.items()` on the top level, so a file shaped
`{"_why": ..., "lessons": {...}}` returned `_why` and `lessons` as if they were lesson slugs;
neither is in any blueprint, both were dropped as unrepairable, and every correction was
discarded in silence. Nine expert-review files were written in that shape.
"""
import json

from scripts.author_course_from_blueprint import load_corrections


def test_nested_lessons_form_yields_real_slugs(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({
        "_why": "tier 1 findings",
        "lessons": {"habitable-zone": ["missing the factor of 4", "state the tidal-heating case"]},
    }))
    got = load_corrections(path)
    assert set(got) == {"habitable-zone"}
    assert "factor of 4" in got["habitable-zone"] and "tidal-heating" in got["habitable-zone"]


def test_flat_form_still_works(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"pasteurization": "UHT gives commercial, not absolute, sterility"}))
    assert load_corrections(path) == {
        "pasteurization": "UHT gives commercial, not absolute, sterility"}


def test_underscore_keys_are_metadata_not_lessons(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"_why": "x", "_notice": "y", "real-lesson": "fix it"}))
    assert set(load_corrections(path)) == {"real-lesson"}
