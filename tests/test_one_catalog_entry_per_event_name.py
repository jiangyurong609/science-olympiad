"""A subject must appear in the event picker once.

Publishing a 2027 event makes it `current`; its 2026 twin keeps whatever status it had. If
that status is also catalog-visible the picker shows the subject twice, disambiguated by
season — "Rocks and Minerals · Div B" twice, then "Disease Detectives · Div B · 2027" above
"Disease Detectives · Div B · 2026". Both were reported by the user, from a screenshot,
after the publish that caused them.

The demotion used to be a hand-maintained list of event IDs, so each newly published subject
had to be remembered separately and two were not. This is the rule that list was standing in
for.
"""
import pytest

from scripts.publish_2027_season import CATALOG_VISIBLE_PEERS, CURRENT, PRIOR_SEASON


class _Event:
    def __init__(self, slug, name, division, season, season_status):
        self.slug, self.name, self.division = slug, name, division
        self.season, self.season_status = season, season_status


def _catalog_rows(events):
    """The events a picker would list: one row per catalog-visible event."""
    return [e for e in events if e.season_status in CATALOG_VISIBLE_PEERS]


def _duplicate_names(events):
    seen = {}
    for event in _catalog_rows(events):
        seen.setdefault((event.name.strip().lower(), event.division), []).append(event)
    return {k: v for k, v in seen.items() if len(v) > 1}


def test_a_current_event_and_a_foundational_twin_are_a_duplicate():
    events = [
        _Event("disease-detectives-b-2027", "Disease Detectives", "B", 2027, CURRENT),
        _Event("disease-detectives-b", "Disease Detectives", "B", 2026, "foundational"),
    ]
    assert _duplicate_names(events), "this is the state the user screenshotted"


def test_demoting_the_twin_resolves_it():
    events = [
        _Event("disease-detectives-b-2027", "Disease Detectives", "B", 2027, CURRENT),
        _Event("disease-detectives-b", "Disease Detectives", "B", 2026, PRIOR_SEASON),
    ]
    assert not _duplicate_names(events)


def test_prior_season_practice_is_not_a_catalog_peer():
    # It is badged and filed on the archive surface. This is why the six subjects demoted
    # earlier each show as one row while Disease Detectives showed as two.
    assert PRIOR_SEASON not in CATALOG_VISIBLE_PEERS
    assert CURRENT in CATALOG_VISIBLE_PEERS


@pytest.mark.parametrize("twin_status", sorted(CATALOG_VISIBLE_PEERS))
def test_every_catalog_visible_status_collides_with_current(twin_status):
    events = [
        _Event("x-b-2027", "Heredity", "B", 2027, CURRENT),
        _Event("x-b", "Heredity", "B", 2026, twin_status),
    ]
    assert _duplicate_names(events)
