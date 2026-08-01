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


def _map(db, event, source):
    """EventSourceMap has several NOT NULL columns; keep the requirement in one place."""
    from app.models.entities import EventSourceMap
    db.add(EventSourceMap(event_id=event.id, source_id=source.id, purpose="past_test",
                          source_tier="official", source_universe_version="test"))


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


# ------------------------------------------------- event scoping (adversarial review finding)

def test_identically_titled_keys_on_different_events_do_not_cross():
    """Normalised titles are not unique across the catalog.

    `find_key_source` matched on title alone, so if another event owned the only same-titled
    key it was accepted and sent to the parser — students graded against a different test's
    answers. The earlier "another event" test used a *different* title, so it never exercised
    this collision.
    """
    from app.models.entities import Event
    with SessionLocal() as db:
        n = next(_UNIQUE)
        mine = Event(slug=f"mine-{n}", name="Mine", division="B", season=2026)
        theirs = Event(slug=f"theirs-{n}", name="Theirs", division="C", season=2026)
        db.add_all([mine, theirs]); db.flush()

        test = _source(db, "Regional Invitational 2026 TEST")
        their_key = _source(db, "Regional Invitational 2026 KEY")
        _map(db, mine, test)
        _map(db, theirs, their_key)
        db.flush()

        assert find_key_source(db, test, mine) is None, \
            "a key belonging to another event must never be used"


def test_the_event_scoped_key_is_still_found():
    from app.models.entities import Event
    with SessionLocal() as db:
        n = next(_UNIQUE)
        mine = Event(slug=f"scoped-{n}", name="Mine", division="B", season=2026)
        other = Event(slug=f"other-{n}", name="Other", division="C", season=2026)
        db.add_all([mine, other]); db.flush()

        test = _source(db, "Scoped Invitational 2026 TEST")
        my_key = _source(db, "Scoped Invitational 2026 KEY")
        _map(db, mine, test)
        _map(db, mine, my_key)
        db.flush()

        assert find_key_source(db, test, mine).id == my_key.id


def test_an_unmapped_catalog_still_matches_by_title():
    """Source mapping is incomplete for much of the catalog; scoping must not turn an
    incomplete mapping into "no key exists"."""
    with SessionLocal() as db:
        from app.models.entities import Event
        n = next(_UNIQUE)
        event = Event(slug=f"unmapped-{n}", name="E", division="B", season=2026)
        db.add(event); db.flush()
        test = _source(db, "Unmapped Invitational 2026 TEST")
        key = _source(db, "Unmapped Invitational 2026 KEY")
        db.flush()
        assert find_key_source(db, test, event).id == key.id
