"""Make the catalog tell the truth about the 2027 season.

Three defects this fixes, all of them the same defect wearing different clothes: the catalog
names a subject and says nothing about which body of material it teaches.

1. Six Division B events rotated their topic for 2027 and the courses in the catalog were
   written for the old one. A student picking "Water Quality" is served eight lessons on
   freshwater macroinvertebrates; 2027 tests marine and estuary systems and coral reef
   organisms, and not one of those words appears in the course. The course is not deleted —
   it is real, reviewed teaching and the skills transfer — but its `topic_focus` must say
   which season it was written for and what 2027 actually tests, because that string is what
   the subject card and the course header render.

2. Thirteen subjects are not on the 2027 roster at all (Entomology, Machines, Helicopter,
   Metric Mastery, Potions and Poisons, Ecology, Bungee Drop, Robot Tour, Materials Science,
   Mission Possible B). They move to `prior_season_practice`, which the client already groups
   under "Prior-season practice" with a badge and sorts below current-season subjects, and
   which the archive surface lists. Nothing is deleted or hidden.

3. The roster itself is wrong in two places: the 2027 Division B trial is named Protein
   Builders, not Protein Modeling, and Hydraulics B is missing entirely.

Division B claims here are checked against the official 2027 Division B rules manual. Division C
claims are checked only against the 2027 roster already in the database (built from Science
Olympiad's published event list) — no Division C manual has been read, so this script makes no
claim about any Division C event's topic and only archives C subjects absent from that roster.

Usage: [--dry-run] [--skip-archive] [--skip-roster]
"""
from __future__ import annotations

import argparse
import os

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.models.entities import AuditLog, Event

SEASON = 2027

# (division, event name) -> what the catalog's course actually teaches, and what 2027 tests.
# Every entry was verified twice: against the rules manual's own topic list, and by searching
# the published lesson content for the terms 2027 requires. `severity` is "rotated" when the
# course teaches a different subject and "gap" when it teaches the right subject incompletely.
TOPIC_TRUTH = {
    ("B", "Meteorology"): dict(
        severity="rotated",
        teaches="everyday weather, pressure systems and climate (2026 topic)",
        tests_2027="Severe Weather & Storms — radar, hodographs, Stüve diagrams, METAR",
        note="at least half the 2027 exam is interpreting severe-weather data displays",
    ),
    ("B", "Dynamic Planet"): dict(
        severity="rotated",
        teaches="oceanography: seawater, circulation, waves and tides (2026 topic)",
        tests_2027="Earth's fresh waters — drainage basins, fluvial landforms, groundwater, karst",
    ),
    ("B", "Water Quality"): dict(
        severity="rotated",
        teaches="freshwater macroinvertebrate identification (2026 topic)",
        tests_2027="marine and estuary systems, and coral reef organism identification",
    ),
    ("B", "Anatomy & Physiology"): dict(
        severity="rotated",
        teaches="the nervous system and brain (2026 topic)",
        tests_2027="respiratory, digestive and immune systems",
    ),
    ("B", "Solar System"): dict(
        severity="rotated",
        teaches="a general survey of solar system objects and formation (2026 topic)",
        tests_2027="habitability and astrobiology across named worlds and exoplanet systems",
    ),
    ("B", "Remote Sensing"): dict(
        severity="gap",
        teaches="remote sensing foundations plus atmospheric and climate sensing",
        tests_2027="Observable Earth — SAR/InSAR, radar altimetry, elevation products",
        note="foundations transfer; InSAR, Sentinel, SRTM and elevation products are uncovered",
    ),
    ("B", "Circuit Lab"): dict(
        severity="gap",
        teaches="DC and AC circuit analysis, electrostatics, capacitors and magnetism",
        tests_2027="the same, plus digital logic and single-junction devices",
        note="digital logic, Boolean algebra, De Morgan's law and control devices are uncovered",
    ),
    ("B", "Codebusters"): dict(
        severity="gap",
        teaches="substitution, Porta, Nihilist, Baconian, Morse and transposition ciphers",
        tests_2027="the 2027 Division B cipher list",
        note="5x5 Checkerboard and Homophonic are uncovered; Affine is no longer in scope",
    ),
    ("B", "Boomilever"): dict(
        severity="gap",
        teaches="cantilever design against the 2026 template and specifications",
        tests_2027="the 2027 specifications",
        note="a lesson still walks the 2026 template — build specs change every season",
    ),
}

# Subjects with no 2027 Division B event, per the rules manual's table of contents.
ARCHIVE_B = ["Entomology", "Helicopter", "Machines", "Metric Mastery", "Mission Possible",
             "Potions and Poisons"]
# B/C events with no 2027 event in either division.
ARCHIVE_BC = ["Ecology"]
# Subjects with no 2027 Division C event, per the 2027 roster already in the database.
ARCHIVE_C = ["Bungee Drop", "Entomology", "Helicopter", "Machines", "Materials Science",
             "Robot Tour"]


def _focus_line(truth: dict) -> str:
    base = f"Covers {truth['teaches']}. 2027 tests {truth['tests_2027']}."
    if note := truth.get("note"):
        # Only the first character: `capitalize()` would lowercase InSAR, SRTM and De Morgan.
        base += f" {note[0].upper()}{note[1:]}."
    return base


def _audit(db, action: str, event: Event, **extra):
    db.add(AuditLog(actor_user_id=None, action=action, entity_type="event",
                    entity_id=str(event.id),
                    details={"event": event.name, "division": event.division,
                             "season": event.season, **extra}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-archive", action="store_true")
    ap.add_argument("--skip-roster", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    changes = 0

    def norm(n: str) -> str:
        return " ".join((n or "").lower().split())

    print("== 1. topic truth on courses a student can reach ==")
    for (division, name), truth in TOPIC_TRUTH.items():
        events = [e for e in db.scalars(select(Event).where(
            Event.active.is_(True),
            Event.division == division,
            Event.season_status.notin_(("superseded", "archived_superseded")),
        )).all() if norm(e.name) == norm(name)]
        if not events:
            print(f"  !! no reachable {division} event named {name} — skipped")
            continue
        line = _focus_line(truth)
        for event in events:
            if (event.topic_focus or "") == line:
                print(f"  ok   [{event.id}] {name} {event.season} — already stated")
                continue
            print(f"  set  [{event.id}] {name} {event.season} ({truth['severity']})")
            print(f"       {line}")
            if not args.dry_run:
                before = event.topic_focus or ""
                event.topic_focus = line
                _audit(db, "event.topic_focus_aligned_to_season", event,
                       season_audited=SEASON, severity=truth["severity"],
                       previous_topic_focus=before, new_topic_focus=line)
            changes += 1

    if not args.skip_roster:
        print("\n== 2. roster corrections ==")
        trial = next((e for e in db.scalars(select(Event).where(
            Event.season == SEASON, Event.division == "B")).all()
            if norm(e.name) == "protein modeling"), None)
        if trial:
            print(f"  rename [{trial.id}] Protein Modeling B -> Protein Builders (2027 name)")
            if not args.dry_run:
                _audit(db, "event.renamed_for_season", trial, previous_name=trial.name,
                       new_name="Protein Builders", season_audited=SEASON)
                trial.name = "Protein Builders"
            changes += 1
        else:
            print("  ok     Protein Modeling B not found (already renamed?)")

        hydraulics = next((e for e in db.scalars(select(Event).where(
            Event.season == SEASON, Event.division == "B")).all()
            if norm(e.name) == "hydraulics"), None)
        if hydraulics:
            print(f"  ok     Hydraulics B exists [{hydraulics.id}]")
        else:
            print("  create Hydraulics B (2027 trial event, missing from the roster)")
            if not args.dry_run:
                created = Event(
                    slug="hydraulics-b-trial-2027", name="Hydraulics", division="B",
                    season=SEASON, modality="hybrid",
                    category="Featured Trial Events", season_status="trial", active=True,
                    topic_focus="Density and fluid mechanics, with a built hydraulic device",
                    description="Density and fluid mechanics, with a built hydraulic device",
                )
                db.add(created)
                db.flush()
                _audit(db, "event.created_for_season", created, season_audited=SEASON,
                       reason="2027 Division B trial event absent from the roster")
            changes += 1

    if not args.skip_archive:
        print("\n== 3. subjects not on the 2027 roster -> prior_season_practice ==")
        for division, names in (("B", ARCHIVE_B), ("B/C", ARCHIVE_BC), ("C", ARCHIVE_C)):
            for name in names:
                events = [e for e in db.scalars(select(Event).where(
                    Event.active.is_(True), Event.division == division,
                    Event.season != SEASON,
                    Event.season_status.notin_(("superseded", "archived_superseded")),
                )).all() if norm(e.name) == norm(name)]
                if not events:
                    print(f"  --   no reachable {division} {name}")
                    continue
                for event in events:
                    if event.season_status == "prior_season_practice":
                        print(f"  ok   [{event.id}] {division} {name} already prior-season")
                        continue
                    counts = db.execute(text("""
                        select (select count(*) from lessons l
                                where l.event_id = :e and l.status = 'published') lessons,
                               (select count(*) from exams x
                                where x.event_id = :e and x.published) exams
                    """), {"e": event.id}).first()
                    print(f"  arch [{event.id}] {division} {name} "
                          f"({counts.lessons} lessons, {counts.exams} exams kept, "
                          f"badged 'Prior season')")
                    if not args.dry_run:
                        _audit(db, "event.archived_not_in_season_roster", event,
                               previous_season_status=event.season_status,
                               season_audited=SEASON,
                               reason="subject is not on the 2027 roster",
                               lessons_retained=counts.lessons,
                               exams_retained=counts.exams)
                        event.season_status = "prior_season_practice"
                    changes += 1

    if args.dry_run:
        db.rollback()
        print(f"\ndry run — {changes} change(s) would be applied")
    else:
        db.commit()
        print(f"\ncommitted {changes} change(s) against "
              f"{os.environ.get('DATABASE_URL', '').split('@')[-1].split('/')[0] or 'the database'}")


if __name__ == "__main__":
    main()
