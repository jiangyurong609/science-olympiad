"""Phase 7b — an answer the parser did not establish must not be graded against.

A low-confidence short answer is worse than a missing one: the student is marked wrong
against a guess, with no signal to anyone that the key was invented. These tests pin that a
weak parse loses its answer and lands in the needs-key queue, and that a clean parse is
untouched.
"""
from __future__ import annotations

import itertools

from app.core.database import SessionLocal
from app.models.entities import Event, Source
from app.services.past_test_import import (
    LOW_CONFIDENCE, build_questions, is_trustworthy, parse_confidence,
)
from app.services.scoring import is_gradeable

_UNIQUE = itertools.count(1)

GOOD_SHORT = {
    "label": "4", "page": 2,
    "stem": "Name the depositional environment shown by cross-bedded sandstone.",
    "question_type": "short_answer", "reference_answer": "aeolian dune field",
}
GOOD_CHOICE = {
    "label": "2", "page": 1, "stem": "Which of these minerals is a silicate?",
    "question_type": "single_choice", "choices": ["Quartz", "Halite", "Calcite", "Galena"],
    "correct_index": 0,
}


def _fixtures(db):
    n = next(_UNIQUE)
    event = Event(slug=f"ev-conf-{n}", name="Rocks", division="B", season=2026)
    db.add(event); db.flush()
    source = Source(url=f"https://example.org/t{n}.pdf", title="T",
                    rights_status="public_domain", approved=True)
    db.add(source); db.flush()
    return event, source


# ---------------------------------------------------------------- scoring

def test_a_clean_parse_scores_full_confidence():
    for item in (GOOD_SHORT, GOOD_CHOICE):
        score, reasons = parse_confidence(dict(item))
        assert score == 1.0, (item["label"], reasons)
        assert reasons == []


def test_a_stem_absent_from_the_source_loses_confidence():
    item = dict(GOOD_SHORT, page=None)
    score, reasons = parse_confidence(item)
    assert score < 1.0
    assert "stem_not_found_in_source" in reasons


def test_no_reference_answer_disqualifies_on_its_own():
    """There is nothing to grade against; the arithmetic score is beside the point."""
    score, reasons = parse_confidence(dict(GOOD_SHORT, reference_answer=""))
    assert "no_reference_answer" in reasons
    assert is_trustworthy(score, reasons) is False


def test_an_out_of_range_choice_index_disqualifies_on_its_own():
    score, reasons = parse_confidence(dict(GOOD_CHOICE, correct_index=9))
    assert "no_valid_correct_index" in reasons
    assert is_trustworthy(score, reasons) is False


def test_cosmetic_findings_alone_do_not_disqualify():
    """A missing printed label is a nuisance, not a reason to withhold a good key."""
    score, reasons = parse_confidence(dict(GOOD_SHORT, label=""))
    assert reasons == ["no_printed_label"]
    assert is_trustworthy(score, reasons) is True


def test_a_fragment_is_not_treated_as_a_question():
    score, reasons = parse_confidence(dict(GOOD_SHORT, stem="Name it."))
    assert "stem_too_short_to_be_a_question" in reasons
    assert score < 1.0


def test_a_very_long_stem_reads_as_merged_items():
    score, reasons = parse_confidence(dict(GOOD_SHORT, stem="x " * 900))
    assert "stem_long_enough_to_be_merged_items" in reasons


def test_confidence_never_goes_negative():
    score, _ = parse_confidence({"stem": "", "question_type": "single_choice"})
    assert score == 0.0


# ---------------------------------------------------------------- consequences

def test_a_low_confidence_short_answer_loses_its_key_and_reaches_the_queue():
    with SessionLocal() as db:
        event, source = _fixtures(db)
        # found nowhere in the source, and the "answer" is a bare guess
        item = dict(GOOD_SHORT, page=None, label="", reference_answer="maybe a delta",
                    stem="Name it.")
        assert is_trustworthy(*parse_confidence(item)) is False
        questions = build_questions(db, event, source, None, [item])

    assert len(questions) == 1
    question = questions[0]
    assert question.answer_spec["answer"] == "", "an unestablished key must not be graded"
    assert question.answer_spec["withheld_reason"]
    assert question.generation_provenance["answer_withheld"] is True
    assert not is_gradeable("short_answer", question.answer_spec), \
        "the item must land in the needs-key queue rather than score silently"


def test_a_confident_short_answer_keeps_its_key():
    with SessionLocal() as db:
        event, source = _fixtures(db)
        questions = build_questions(db, event, source, None, [dict(GOOD_SHORT)])
    question = questions[0]
    assert question.answer_spec["answer"] == "aeolian dune field"
    assert question.generation_provenance["answer_withheld"] is False
    assert is_gradeable("short_answer", question.answer_spec)


def test_confidence_is_recorded_on_every_item_for_triage():
    with SessionLocal() as db:
        event, source = _fixtures(db)
        questions = build_questions(db, event, source, None,
                                    [dict(GOOD_SHORT), dict(GOOD_CHOICE)])
    for question in questions:
        assert "parse_confidence" in question.generation_provenance
        assert isinstance(question.generation_provenance["parse_confidence_reasons"], list)


def test_a_low_confidence_multiple_choice_keeps_its_index():
    """Withholding applies to short answers only: a choice item with a bad index is already
    ungradeable, and blanking choices would destroy the item rather than flag it."""
    with SessionLocal() as db:
        event, source = _fixtures(db)
        item = dict(GOOD_CHOICE, page=None, label="")
        questions = build_questions(db, event, source, None, [item])
    assert questions[0].choices == GOOD_CHOICE["choices"]
