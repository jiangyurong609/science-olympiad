from pathlib import Path

from scripts.author_course_from_blueprint import PAST_TEST_URL_PREFIX
from scripts.register_rules_sources import SCOPE_DIR, URL_PREFIX, rules_text


def test_rules_text_drops_the_internal_preamble_and_keeps_the_rules():
    text = rules_text(Path(SCOPE_DIR) / "write-it-do-it.md")
    assert "internal course" not in text and not text.startswith("#")
    assert "incorrect connection" in text and "twenty-five (25) minutes" in text


def test_rules_sources_are_teaching_evidence_not_past_tests():
    # `local://` marks past tests, which are excluded from what a lesson may cite.
    assert not URL_PREFIX.startswith(PAST_TEST_URL_PREFIX)
