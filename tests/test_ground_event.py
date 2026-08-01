"""Phase 1 — extraction must produce claims, not site furniture.

Auto-approving every scraped sentence made "Skip to global NPS navigation" and "Official
websites use .gov" into verified scientific claims that satisfied grounding gates.
"""
from __future__ import annotations

import pytest

from scripts.ground_event import is_claimlike


@pytest.mark.parametrize("sentence", [
    "Skip to global NPS navigation and then to the main content of this page.",
    "Official websites use .gov A .gov website belongs to an official government organization.",
    "Share sensitive information only on official, secure websites and never elsewhere.",
    "The National Park System includes hundreds of sites across the United States today.",
])
def test_boilerplate_and_navigation_are_not_claims(sentence):
    ok, reason = is_claimlike(sentence)
    assert not ok, f"{sentence!r} should not be a scientific claim"
    assert reason in {"boilerplate", "off_topic"}


@pytest.mark.parametrize("sentence", [
    "Minerals are naturally occurring solids with a definite chemical composition and structure.",
    "Igneous rocks form when molten magma cools and crystallises beneath or above the surface.",
    "Metamorphic rocks are produced when heat and pressure alter an existing rock.",
])
def test_real_geological_statements_are_claims(sentence):
    ok, reason = is_claimlike(sentence)
    assert ok, f"{sentence!r} rejected as {reason}"


def test_a_topical_sentence_without_a_predicate_is_not_a_proposition():
    ok, reason = is_claimlike("Mineral hardness, streak, luster, cleavage, fracture, density.")
    assert not ok and reason in {"not_a_proposition", "list_or_heading"}


def test_extraction_does_not_approve_by_default():
    """Approval is a human decision; extraction only proposes."""
    import inspect
    from scripts import ground_event
    signature = inspect.signature(ground_event.harvest_claims)
    assert signature.parameters["approve"].default is False
