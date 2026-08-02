"""Curated source lists are a dependency, and were treated as an assumption.

140 URLs were added to `DOMAIN_SOURCES` without fetching one of them. 22 were dead, and every
meteorology URL — including the two already there — returns 403 because `weather.gov` and
`noaa.gov` refuse this bot's user agent. Adding pages from a host that refuses us reads as
"this event now has 16 sources" in every report while grounding it produces nothing.

Liveness needs the network, so it lives in `scripts/check_open_sources.py`. What can be
asserted offline is asserted here.
"""
import re

from scripts.check_open_sources import REFUSES_OUR_AGENT
from scripts.open_sources import DOMAIN_SOURCES, EVENT_DOMAIN, domain_for_event


def test_no_source_comes_from_a_host_that_refuses_our_agent():
    """A 403 host contributes nothing but an inflated source count."""
    offenders = [
        (domain, url)
        for domain, spec in DOMAIN_SOURCES.items()
        for url in spec["urls"]
        if any(host in url for host in REFUSES_OUR_AGENT)
    ]
    assert not offenders, (
        f"{len(offenders)} url(s) come from hosts that 403 this crawler: {offenders[:3]}"
    )


def test_every_mapped_event_resolves_to_a_domain_that_exists():
    """`ground_event` raises SystemExit on a domain it cannot find."""
    for slug, domain in EVENT_DOMAIN.items():
        assert domain in DOMAIN_SOURCES, f"{slug} maps to unknown domain {domain!r}"


def test_division_and_season_suffixes_resolve_to_the_base_mapping():
    """The bug that left 100 of 102 events ungrounded.

    `EVENT_DOMAIN` is keyed on base slugs; `ground_event` looked up the full slug and reported
    "no open-source domain mapped", which reads as a content gap rather than a lookup bug.
    """
    assert domain_for_event("heredity-b") == "genetics"
    assert domain_for_event("disease-detectives-c") == "epidemiology"
    assert domain_for_event("rocks-and-minerals-b") == "geology"
    assert domain_for_event("botany-b-2027") == domain_for_event("botany")
    assert domain_for_event("no-such-event") is None


def test_every_domain_carries_enough_sources_to_ground_a_course():
    """geology's 64 urls produced 239 claims and the only real course in the catalog.

    Two urls produced courses too thin to learn from. This is a floor, not a target: it exists
    so a domain cannot quietly sit at one source while its events report as covered.
    """
    thin = {d: len(spec["urls"]) for d, spec in DOMAIN_SOURCES.items()
            if len(spec["urls"]) < 2}
    assert not thin, f"domains with fewer than 2 sources: {thin}"


def test_urls_are_well_formed_and_unique_within_a_domain():
    for domain, spec in DOMAIN_SOURCES.items():
        urls = spec["urls"]
        assert len(urls) == len(set(urls)), f"{domain} lists a duplicate url"
        for url in urls:
            assert re.match(r"^https://", url), f"{domain}: {url} is not https"


def test_every_domain_declares_its_rights():
    """Grounding on a source whose licence nobody recorded is the failure this avoids."""
    for domain, spec in DOMAIN_SOURCES.items():
        assert spec.get("publisher"), f"{domain} has no publisher"
        assert spec.get("license"), f"{domain} has no license"
