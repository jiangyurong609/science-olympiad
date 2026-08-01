"""Phase 7c — a test must find its own answer key, and never someone else's.

27 of 96 imports ran with no key at all (1,226 items) while the matching key sat in the
database under a title differing by a single word. `Astronomy … 2026 TEST` produced 55
multiple-choice items with an empty answer on every one, right next to
`Astronomy … 2026 KEY`. Nothing ever opened it.

The refusals matter as much as the matches: a key from the wrong event grades students
confidently and wrongly, which is worse than the missing key it would replace.
"""
from __future__ import annotations

import itertools

from app.core.database import SessionLocal
from app.models.entities import Source
from app.services.past_test_import import find_key_source

_UNIQUE = itertools.count(1)


def _source(db, title):
    source = Source(url=f"local://{title}-{next(_UNIQUE)}", title=title,
                    rights_status="public_domain", approved=True)
    db.add(source); db.flush()
    return source


def test_a_test_finds_the_key_named_after_it():
    with SessionLocal() as db:
        test = _source(db, "Astronomy - Wichita Heights Div C 2026 TEST")
        key = _source(db, "Astronomy - Wichita Heights Div C 2026 KEY")
        assert find_key_source(db, test).id == key.id


def test_the_role_word_may_differ_in_wording():
    with SessionLocal() as db:
        test = _source(db, "Circuit Lab Regional 2026 Exam")
        key = _source(db, "Circuit Lab Regional 2026 Answers")
        assert find_key_source(db, test).id == key.id


def test_punctuation_and_case_do_not_prevent_a_match():
    with SessionLocal() as db:
        test = _source(db, "Dynamic  Planet — Div. C, 2026 TEST")
        key = _source(db, "dynamic planet - div c 2026 key")
        assert find_key_source(db, test).id == key.id


def test_another_events_key_is_never_borrowed():
    with SessionLocal() as db:
        test = _source(db, "Entomology - Heights Div C 2026 TEST")
        _source(db, "Machines - Heights Div C 2026 KEY")
        assert find_key_source(db, test) is None


def test_a_different_year_is_not_the_same_test():
    with SessionLocal() as db:
        test = _source(db, "Water Quality Div C 2026 TEST")
        _source(db, "Water Quality Div C 2025 KEY")
        assert find_key_source(db, test) is None


def test_two_equally_good_candidates_produce_no_match():
    """A tie is ambiguity, and guessing between keys is how the wrong one gets attached."""
    with SessionLocal() as db:
        test = _source(db, "Fossils Invitational 2026 TEST")
        _source(db, "Fossils Invitational 2026 KEY")
        _source(db, "Fossils Invitational 2026 ANSWERS")
        assert find_key_source(db, test) is None


def test_a_source_not_named_as_a_test_is_left_alone():
    with SessionLocal() as db:
        source = _source(db, "USGS Mineral Resources Overview")
        _source(db, "USGS Mineral Resources Overview KEY")
        assert find_key_source(db, source) is None


def test_a_test_with_no_key_present_returns_none():
    with SessionLocal() as db:
        test = _source(db, "Optics Div B 2026 TEST")
        assert find_key_source(db, test) is None


def test_a_title_that_is_only_a_role_word_matches_nothing():
    with SessionLocal() as db:
        test = _source(db, "TEST")
        _source(db, "KEY")
        assert find_key_source(db, test) is None
