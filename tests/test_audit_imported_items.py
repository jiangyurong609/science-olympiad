"""The detector for broken imported questions must judge by the answer key.

Its first version judged the stem's wording and was wrong in both directions: it would have
deleted "Match the definition: a disease that occurs infrequently and irregularly" (keyed
"Sporadic" — a perfectly good recall question that merely lost its word bank), and "Is
radiance a scalar or vector quantity?" (keyed "vector"). Deleting a valid question from a
real past paper is worse than leaving a broken one, so both directions are pinned here.
"""
from types import SimpleNamespace

from scripts.audit_imported_items import classify


def q(stem, key, choices=None):
    return SimpleNamespace(stem=stem, choices=choices or [],
                           answer_spec={"answer": key, "accepted": [key]})


def test_a_letter_keyed_to_a_lost_column_is_broken():
    assert classify(q("Match the disorder Myopia to the correct description.", "A")) \
        == "letter_key_to_lost_column"


def test_a_stem_that_names_the_term_and_supplies_its_definition_answers_itself():
    assert classify(q("Match the term “Nephology” to its definition: the study of "
                      "clouds and cloud formation.", "Nephology")) == "answer_in_stem"


def test_recall_with_a_real_word_key_is_kept():
    assert classify(q("Match the definition: A disease that occurs infrequently and "
                      "irregularly.", "Sporadic")) is None


def test_either_or_questions_are_kept():
    assert classify(q("Is radiance a scalar or vector quantity?", "vector")) is None
    assert classify(q("Determine whether the following statement is true or false: a "
                      "polygenic trait is controlled by more than one gene.", "true")) is None


def test_items_with_a_real_choice_list_are_never_flagged():
    assert classify(q("Match the term to the definition: taking too much Tylenol can cause "
                      "organ failure.", "C", choices=[f"term {i}" for i in range(15)])) is None


def test_paper_furniture_is_flagged():
    assert classify(q("Write your salinity estimate on the answer sheet. This estimate will "
                      "be used as Tiebreaker 1.", "n/a")) == "paper_furniture"
