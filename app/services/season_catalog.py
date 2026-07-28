from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Event


OFFICIAL_2027_SLATE_URL = (
    "https://www.soinc.org/sites/default/files/uploaded_files/Div_B_C_27_Slate.pdf"
)

_B_2027 = {
    "Life, Personal & Social Science": [
        ("Anatomy & Physiology", "Digestive, immune, and respiratory systems"),
        ("Disease Detectives", ""),
        ("Heredity", ""),
        ("Botany", ""),
        ("Water Quality", "Marine and estuary systems"),
    ],
    "Earth & Space Science": [
        ("Dynamic Planet", "Earth's fresh waters"),
        ("Meteorology", "Severe storms"),
        ("Remote Sensing", ""),
        ("Rocks and Minerals", ""),
        ("Solar System", ""),
    ],
    "Physical Science & Chemistry": [
        ("Hovercraft", ""),
        ("Circuit Lab", ""),
        ("Thermodynamics", ""),
        ("Crime Busters", ""),
        ("Food Science", ""),
    ],
    "Technology & Engineering Design": [
        ("Boomilever", ""),
        ("Elastic Launch Glider", ""),
        ("Roller Coaster", ""),
        ("Scrambler", ""),
    ],
    "Inquiry & Nature of Science": [
        ("Codebusters", ""),
        ("Experimental Design", ""),
        ("Ping Pong Parachute", ""),
        ("Write It Do It", ""),
    ],
}

_C_2027 = {
    "Life, Personal & Social Science": [
        ("Anatomy & Physiology", "Digestive, immune, and respiratory systems"),
        ("Designer Genes", ""),
        ("Disease Detectives", ""),
        ("Botany", ""),
        ("Water Quality", "Marine and estuary systems"),
    ],
    "Earth & Space Science": [
        ("Astronomy", ""),
        ("Dynamic Planet", "Earth's fresh waters"),
        ("Remote Sensing", ""),
        ("Rocks and Minerals", ""),
    ],
    "Physical Science & Chemistry": [
        ("Circuit Lab", ""),
        ("Hovercraft", ""),
        ("Thermodynamics", ""),
        ("Chemistry Lab", "Kinetics and gases"),
        ("Forensics", ""),
        ("Protein Modeling", ""),
    ],
    "Technology & Engineering Design": [
        ("Boomilever", ""),
        ("Electric Vehicle", ""),
        ("Mission Possible", ""),
        ("Wright Stuff", ""),
    ],
    "Inquiry & Nature of Science": [
        ("Codebusters", ""),
        ("Experimental Design", ""),
        ("Ping Pong Parachute", ""),
        ("Engineering CAD", ""),
    ],
}

_TRIAL_2027 = {
    "B": [("Code Craze", ""), ("Protein Modeling", "")],
    "C": [("Code Craze", "")],
}


@dataclass(frozen=True)
class CatalogEvent:
    slug: str
    name: str
    division: str
    category: str
    topic_focus: str
    season_status: str
    official_url: str


@dataclass
class CatalogRegistrationReport:
    mode: str
    season: int
    catalog_rows: int
    created: int = 0
    updated: int = 0
    older_events_archived: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _slug(name: str) -> str:
    normalized = name.lower().replace("&", " and ")
    return "-".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())


def events_2027() -> list[CatalogEvent]:
    rows: list[CatalogEvent] = []
    for division, categories in (("B", _B_2027), ("C", _C_2027)):
        for category, events in categories.items():
            for name, focus in events:
                base = _slug(name)
                rows.append(
                    CatalogEvent(
                        slug=f"{base}-{division.lower()}-2027",
                        name=name,
                        division=division,
                        category=category,
                        topic_focus=focus,
                        season_status="current",
                        official_url=f"https://www.soinc.org/{base}-{division.lower()}",
                    )
                )
    for division, events in _TRIAL_2027.items():
        for name, focus in events:
            rows.append(
                CatalogEvent(
                    slug=f"{_slug(name)}-{division.lower()}-trial-2027",
                    name=name,
                    division=division,
                    category="Featured Trial Events",
                    topic_focus=focus,
                    season_status="trial",
                    official_url="https://www.soinc.org/learn/trial-events",
                )
            )
    rows.append(
        CatalogEvent(
            slug="season-resources-bc-2027",
            name="Season Resources",
            division="B/C",
            category="Season Resources",
            topic_focus="Schedules, orientation, workshop resources, and official channels",
            season_status="current",
            official_url="https://www.soinc.org/2026-national-tournament",
        )
    )
    return rows


def register_2027_catalog(
    db: Session,
    *,
    apply: bool = False,
    archive_older: bool = True,
) -> CatalogRegistrationReport:
    rows = events_2027()
    report = CatalogRegistrationReport(
        mode="apply" if apply else "dry_run",
        season=2027,
        catalog_rows=len(rows),
    )
    for row in rows:
        event = db.scalar(
            select(Event).where(Event.slug == row.slug, Event.season == 2027)
        )
        if event is None:
            report.created += 1
            if not apply:
                continue
            event = Event(slug=row.slug, name=row.name, division=row.division, season=2027)
            db.add(event)
        else:
            report.updated += 1
        if apply:
            event.name = row.name
            event.division = row.division
            event.category = row.category
            event.topic_focus = row.topic_focus
            event.description = row.topic_focus or f"2027 {row.category} event"
            event.official_url = row.official_url
            event.season_status = row.season_status
            event.active = True
    if archive_older:
        older = db.scalars(
            select(Event).where(Event.season < 2027, Event.season_status == "current")
        ).all()
        report.older_events_archived = len(older)
        if apply:
            for event in older:
                event.season_status = "foundational"
    if apply:
        db.commit()
    return report
