"""Ingest openly-licensed reference text so material-less events can get a
grounded course. Sources are US-government / public-domain pages (weather.gov,
genome.gov, MedlinePlus, NIST, NPS) whose text is free to reuse.

For each event slug it fetches the curated pages, extracts readable text, and
records a Source + SourceSnapshot + EventSourceMap — the same shape the crawler
produces — so lesson_generation.py can ground a course in it.

Usage: python -m scripts.ingest_reference_material [slug ...]   (default: all)
"""
from __future__ import annotations

import hashlib
import re
import sys

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, EventSourceMap, Source, SourceSnapshot

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

# event slug -> publisher, [(url, title)] of public-domain reference pages
SOURCES = {
    "meteorology": ("NOAA National Weather Service (JetStream)", [
        ("https://www.noaa.gov/jetstream/atmosphere/layers-of-atmosphere", "Layers of the Atmosphere"),
        ("https://www.noaa.gov/jetstream/atmosphere/air-pressure", "Air Pressure"),
        ("https://www.noaa.gov/jetstream/atmosphere/energy", "Energy in the Atmosphere"),
        ("https://www.noaa.gov/jetstream/atmosphere/transfer-of-heat-energy", "Transfer of Heat Energy"),
        ("https://www.noaa.gov/jetstream/atmosphere/precipitation", "Precipitation"),
        ("https://www.noaa.gov/jetstream/global/global-atmospheric-circulations", "Global Atmospheric Circulations"),
        ("https://www.noaa.gov/jetstream/global/jet-stream", "The Jet Stream"),
        ("https://www.noaa.gov/jetstream/global/climate-vs-weather", "Climate vs. Weather"),
        ("https://www.noaa.gov/jetstream/global/climate-zones", "Climate Zones"),
        ("https://www.noaa.gov/jetstream/clouds/how-clouds-form", "How Clouds Form"),
        ("https://www.noaa.gov/jetstream/clouds/ten-basic-clouds", "Ten Basic Cloud Types"),
    ]),
    "ecology": ("EPA / National Park Service / USGS", [
        ("https://www.epa.gov/report-environment/ecological-condition", "Ecological Condition"),
        ("https://www.epa.gov/eco-research/ecosystem-services", "Ecosystem Services"),
        ("https://www.nps.gov/subjects/ecology/index.htm", "Ecology in the National Parks"),
        ("https://www.usgs.gov/special-topics/water-science-school/science/food-web", "Aquatic Food Webs"),
        ("https://www.epa.gov/nutrientpollution/effects-ecosystem", "Nutrient Pollution Effects"),
    ]),
    "heredity": ("National Human Genome Research Institute / MedlinePlus", [
        ("https://www.genome.gov/about-genomics/fact-sheets/A-Brief-Guide-to-Genomics", "A Brief Guide to Genomics"),
        ("https://www.genome.gov/about-genomics/fact-sheets/Introduction-to-Genomics", "Introduction to Genomics"),
        ("https://medlineplus.gov/genetics/understanding/basics/gene/", "What is a Gene?"),
        ("https://medlineplus.gov/genetics/understanding/inheritance/inheritancepatterns/", "Inheritance Patterns"),
        ("https://medlineplus.gov/genetics/understanding/basics/dna/", "What is DNA?"),
        ("https://medlineplus.gov/genetics/understanding/howgeneswork/protein/", "How Genes Make Proteins"),
    ]),
    "experimental-design": ("NIST/SEMATECH e-Handbook of Statistical Methods", [
        ("https://www.itl.nist.gov/div898/handbook/pri/section1/pri11.htm", "What is Experimental Design?"),
        ("https://www.itl.nist.gov/div898/handbook/pri/section1/pri12.htm", "Goals of Experimental Design"),
        ("https://www.itl.nist.gov/div898/handbook/pri/section2/pri21.htm", "Basic Design Principles"),
        ("https://www.itl.nist.gov/div898/handbook/eda/section3/eda35.htm", "Quantitative Techniques"),
        ("https://www.itl.nist.gov/div898/handbook/pmd/section1/pmd12.htm", "Building a Statistical Model"),
    ]),
}


def _extract(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def ingest(db, slug: str) -> int:
    event = db.scalar(select(Event).where(Event.slug == slug))
    if not event or slug not in SOURCES:
        print(f"  {slug}: SKIP (unknown event)")
        return 0
    publisher, pages = SOURCES[slug]
    total = 0
    for url, title in pages:
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True, headers={"User-Agent": UA})
            if resp.status_code != 200:
                print(f"    {title}: HTTP {resp.status_code}, skip")
                continue
            text = _extract(resp.text)
        except httpx.HTTPError as exc:
            print(f"    {title}: error {type(exc).__name__}, skip")
            continue
        if len(text) < 400:
            print(f"    {title}: only {len(text)} chars, skip")
            continue
        source = db.scalar(select(Source).where(Source.url == url))
        if not source:
            source = Source(url=url, title=title, publisher=publisher)
            db.add(source)
            db.flush()
        snap = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_id == source.id).order_by(SourceSnapshot.id.desc()))
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        if not snap or snap.content_hash != content_hash:
            db.add(SourceSnapshot(source_id=source.id, final_url=url,
                                  content_hash=content_hash, extracted_text=text))
        if not db.scalar(select(EventSourceMap).where(
                EventSourceMap.event_id == event.id, EventSourceMap.source_id == source.id)):
            db.add(EventSourceMap(event_id=event.id, source_id=source.id,
                                  purpose="core_reference", source_tier=1,
                                  source_universe_version=1))
        db.flush()
        total += len(text)
        print(f"    {title}: {len(text)} chars ✓")
    db.commit()
    print(f"  {slug}: {total} chars ingested")
    return total


def main() -> None:
    slugs = [a for a in sys.argv[1:] if not a.startswith("--")] or list(SOURCES)
    with SessionLocal() as db:
        for slug in slugs:
            ingest(db, slug)


if __name__ == "__main__":
    main()
