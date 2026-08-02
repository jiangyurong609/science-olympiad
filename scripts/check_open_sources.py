"""Fetch every curated source URL and report the ones that do not answer.

Written after adding 140 URLs to `DOMAIN_SOURCES` without fetching any of them first. 22 were
dead on arrival, and the damage was worse than a few missing pages: **every** meteorology URL
returns 403, including the two that predate the additions, because `weather.gov` and
`noaa.gov` refuse this bot's user agent outright. So that domain could never ground anything,
and the previous run — which had produced 10 claims from the two older URLs — dropped to zero
once the new ones were added. A source list is a dependency; an unfetched one is an assumption.

Run this before committing a change to `DOMAIN_SOURCES`, and periodically after, since a
curated URL is only as good as the day it was checked.

    PYTHONPATH=. python -m scripts.check_open_sources
    PYTHONPATH=. python -m scripts.check_open_sources --domain meteorology
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor

import httpx

from scripts.open_sources import DOMAIN_SOURCES

USER_AGENT = {
    "User-Agent": ("FieldstoneEducationalBot/1.0 (Science Olympiad learning platform; "
                   "+https://science-olympiad.com)"),
}
# Hosts *measured* to refuse this agent with 403 on every path tried. Listing them is not a
# workaround — it records why an authoritative source is unusable, so nobody adds a fourteenth
# page from the same host expecting a different answer.
#
# Measured per host, not per organisation: `oceanservice.noaa.gov` answers 200 on all eight
# pages we use, while `www.noaa.gov` and `www.weather.gov` refuse everything. Blocking "NOAA"
# would have discarded eight working oceanography sources — this list was in fact written that
# way first, and the test below caught it.
REFUSES_OUR_AGENT = {"www.weather.gov", "www.noaa.gov"}


def check(pair: tuple[str, str]) -> tuple[str, str, str]:
    domain, url = pair
    try:
        response = httpx.get(url, timeout=httpx.Timeout(25.0, connect=10.0),
                             follow_redirects=True, headers=USER_AGENT)
        return domain, url, str(response.status_code)
    except Exception as exc:                     # noqa: BLE001 - reporting, not handling
        return domain, url, type(exc).__name__


def main() -> None:
    ap = argparse.ArgumentParser(description="Check curated source URLs still answer")
    ap.add_argument("--domain", default=None)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    pairs = [(d, u) for d, spec in DOMAIN_SOURCES.items()
             for u in spec["urls"] if args.domain in (None, d)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(check, pairs))

    bad = [r for r in results if r[2] != "200"]
    # A timeout used to be excluded from the exit status as "transient". That let the script
    # exit 0 while claiming "all urls answering", when a url that never answers is exactly as
    # useless to `ground_event` as a 404. Timeouts are retried once; anything still not 200
    # after that counts.
    retried = []
    for domain, url, status in bad:
        if status in {"ReadTimeout", "ConnectTimeout", "ReadError"}:
            retried.append(check((domain, url)))
        else:
            retried.append((domain, url, status))
    bad = [r for r in retried if r[2] != "200"]
    results = [r for r in results if r[2] == "200"] + retried
    by_domain: dict[str, int] = {}
    for domain, _, status in bad:
        by_domain[domain] = by_domain.get(domain, 0) + 1

    print("=" * 78)
    print(f"OPEN SOURCE CHECK — {len(results)} url(s)")
    print("=" * 78)
    for domain, url, status in sorted(bad):
        note = "  (host refuses our agent)" if any(
            h in url for h in REFUSES_OUR_AGENT) else ""
        print(f"  {status:>12}  {domain:14} {url[:70]}{note}")
    print("-" * 78)
    print(f"  answering 200: {len(results) - len(bad)}/{len(results)}")
    for domain, count in sorted(by_domain.items(), key=lambda kv: -kv[1]):
        live = sum(1 for d, _, s in results if d == domain and s == "200")
        print(f"  {domain:16} {count} unusable, {live} live")
    print("=" * 78)
    raise SystemExit(1 if by_domain else 0)


if __name__ == "__main__":
    main()
