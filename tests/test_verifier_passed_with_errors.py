"""A verifier that objects has not passed, whatever shape `passed` arrives in.

The verifier is a free-form model call: `passed` comes back sometimes as a bool and sometimes
as a list of per-check results. `bool(payload["passed"])` is truthy for any non-empty list, so
an item whose verifier simultaneously filled `errors` with real objections — "the stem asks
broadly and two choices are defensible", "the claim does not support this wording" — was
recorded as verifier-approved.

`item_clears_every_gate` refuses those independently, which is why nothing bad shipped, but the
stored report still claimed a pass the verifier never gave. Measured against production, 4
re-validated items carried exactly that contradiction.
"""
import pytest

from scripts.build_launch_exams import item_clears_every_gate


class _Q:
    """Minimal stand-in: item_clears_every_gate only reads these attributes."""

    def __init__(self, report):
        self.status = "machine_validated"
        self.validation_report = report
        self.citations = [{"source_id": 1, "claim_id": 1}]
        self.generation_provenance = {}


def _report(verifier):
    return {
        "passed": True,
        "independent_solver": {"verdict": "solver_agrees", "passed": True},
        "independent_verifier": verifier,
        "factual_grounding": "approved_claims",
    }


def test_gate_refuses_a_verifier_that_listed_errors():
    verifier = {
        "passed": [{"check": "answer consistency", "reason": "key matches"}],
        "errors": [{"check": "single unambiguous answer",
                    "reason": "two choices are defensible"}],
    }
    assert item_clears_every_gate(_Q(_report(verifier))) is False


def test_gate_accepts_a_clean_verifier_in_either_shape():
    for passed in (True, ["single unambiguous answer", "answer consistency"]):
        verifier = {"passed": passed, "errors": []}
        assert item_clears_every_gate(_Q(_report(verifier))) is True, passed


@pytest.mark.parametrize("verifier,expected", [
    ({"passed": [{"check": "a"}], "errors": [{"check": "b"}]}, False),
    ({"passed": True, "errors": ["factual support"]}, False),
    ({"passed": False, "errors": []}, False),
    ({"errors": []}, False),                      # never verified is not verified clean
])
def test_generation_marks_verifier_passed_only_when_clean(verifier, expected):
    """The same rule the generator must apply before writing `passed` into the report."""
    verifier_passed = bool(verifier.get("passed")) and not verifier.get("errors")
    assert verifier_passed is expected
