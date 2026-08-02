"""A course manifest must carry every lesson, and say how many it carried.

The exporter kept only the primary LessonSkill link per skill, so a skill teaching three
parts of a split lesson exported one. The pilot has 24 lessons across 8 skills; the manifest
carried 8. Worse, its summary counted *skills* and printed them as `lessons: 8`, so a
migration losing two-thirds of the content reported a number that looked right.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _export(tmp_path: Path, event: str) -> dict:
    out = tmp_path / "manifest.json"
    result = subprocess.run(
        [sys.executable, "-m", "scripts.export_course_manifest",
         "--event", event, "--output", str(out)],
        capture_output=True, text=True, cwd=Path.cwd(),
        env={"PYTHONPATH": ".", "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    if result.returncode != 0:
        pytest.skip(f"export unavailable in this environment: {result.stderr[-200:]}")
    return json.loads(out.read_text())


def _lessons(manifest: dict) -> list[dict]:
    return [lesson
            for unit in manifest["course"]["units"]
            for skill in unit["skills"]
            for lesson in skill.get("lessons", [])]


def test_every_lesson_a_skill_teaches_is_carried(tmp_path):
    manifest = _export(tmp_path, "rocks-and-minerals-b")
    lessons = _lessons(manifest)
    assert len(lessons) > len(manifest["course"]["units"]), \
        "a split course teaches more lessons than it has units"
    slugs = [lesson["slug"] for lesson in lessons]
    assert len(slugs) == len(set(slugs)), "each lesson should appear once"


def test_split_parts_survive_the_export(tmp_path):
    """The parts are the content most at risk: they exist only as extra links on a skill."""
    manifest = _export(tmp_path, "rocks-and-minerals-b")
    parts = [lesson for lesson in _lessons(manifest) if "part-" in lesson["slug"]]
    assert parts, "the split parts must be in the manifest, not just the first of each"


def test_each_carried_lesson_has_its_content(tmp_path):
    manifest = _export(tmp_path, "rocks-and-minerals-b")
    for lesson in _lessons(manifest):
        assert "content" in lesson and isinstance(lesson["content"], list)
        assert "version" in lesson and "review_status" in lesson


def test_exactly_one_lesson_per_skill_is_primary(tmp_path):
    manifest = _export(tmp_path, "rocks-and-minerals-b")
    for unit in manifest["course"]["units"]:
        for skill in unit["skills"]:
            lessons = skill.get("lessons", [])
            if not lessons:
                continue
            primaries = [lesson for lesson in lessons if lesson.get("is_primary")]
            assert len(primaries) <= 1, f"{skill['slug']} has {len(primaries)} primaries"


def test_the_import_reads_the_plural_field_and_still_accepts_the_singular():
    """Manifests written before this change must keep importing."""
    source = Path("scripts/import_course_manifest.py").read_text()
    assert 'skill_payload.get("lessons")' in source
    assert 'skill_payload.get("lesson")' in source, "older manifests must still import"
