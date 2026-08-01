"""Lesson checkpoints assess students, so they belong behind the same gate as exam items.

An exam item cannot reach `machine_validated` unless a blind solver — shown only the stem and
choices — reproduces the key. The pilot's 73 lesson checkpoints, 47 of them model-written, had
never faced that gate: assessment content was held to two standards depending on which table
it lived in.
"""
from __future__ import annotations

from app.services.course_quality import checkpoints_the_solver_disputed
from scripts.solve_lesson_checkpoints import checkpoint_key


def test_both_checkpoint_schemas_are_read():
    """Authored blocks use question/correct_index; split-generated ones use
    prompt/answer_index. Assuming either silently skips half the content."""
    authored = {"type": "checkpoint", "question": "Which is a silicate?",
                "choices": ["Quartz", "Halite"], "correct_index": 0}
    generated = {"type": "checkpoint", "prompt": "Which is a carbonate?",
                 "choices": ["Calcite", "Quartz"], "answer_index": 0}
    assert checkpoint_key(authored) == ("Which is a silicate?", ["Quartz", "Halite"], 0)
    assert checkpoint_key(generated) == ("Which is a carbonate?", ["Calcite", "Quartz"], 0)


def test_a_checkpoint_without_an_answer_is_not_solvable():
    stem, choices, index = checkpoint_key({"type": "checkpoint", "question": "Why?",
                                           "choices": ["a", "b"]})
    assert index is None


def test_an_agreed_checkpoint_is_not_reported():
    content = [{"type": "checkpoint", "heading": "Fine",
                "solver_check": {"agreed": True, "verdict": "solver_agrees"}}]
    assert checkpoints_the_solver_disputed(content) == []


def test_a_disagreement_is_reported_with_both_answers():
    content = [{"type": "checkpoint", "heading": "Disputed", "correct_index": 1,
                "solver_check": {"agreed": False, "verdict": "solver_disagrees_with_key",
                                 "chosen_index": 3}}]
    disputed = checkpoints_the_solver_disputed(content)
    assert len(disputed) == 1
    assert disputed[0]["key"] == 1 and disputed[0]["solver_choice"] == 3
    assert disputed[0]["verdict"] == "solver_disagrees_with_key"


def test_an_ambiguous_or_underspecified_stem_is_reported_even_when_the_choice_matches():
    """One repaired pilot checkpoint had the solver pick the right index while still
    reporting the stem underspecified. Agreement on the letter is not agreement."""
    content = [{"type": "checkpoint", "heading": "Underspecified", "answer_index": 2,
                "solver_check": {"agreed": False, "chosen_index": 2,
                                 "verdict": "solver_insufficient_information"}}]
    assert len(checkpoints_the_solver_disputed(content)) == 1


def test_model_written_blocks_are_marked_so_review_can_prioritise():
    content = [{"type": "checkpoint", "heading": "Generated", "answer_index": 0,
                "generated_by": "split_lessons",
                "solver_check": {"agreed": False, "verdict": "solver_reports_ambiguous"}}]
    assert checkpoints_the_solver_disputed(content)[0]["model_written"] is True


def test_a_checkpoint_never_solved_is_not_reported_as_disputed():
    """Absence of a check must not read as a failed check — the same distinction
    `gates_run` makes for exam items."""
    assert checkpoints_the_solver_disputed([{"type": "checkpoint", "heading": "Unchecked"}]) == []
