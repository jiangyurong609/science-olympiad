"""Find blueprint keywords that select no passage, before a course is authored on them.

A lesson's keywords are not decoration: `_select_passages` takes, for each keyword in order,
the best passage containing that literal term, and the lesson is written from only what those
passages say. So a keyword no page contains does not degrade gracefully — it silently narrows
the lesson, and the author then reports the missing material as unsupported by the sources.
That reads as a gap in the corpus when it is a typo, a dash, or a term the sources spell
differently.

Three ways a keyword misses that are invisible by inspection, all found in real blueprints:

  * Wikipedia titles the Stefan-Boltzmann law with an EN DASH, and its prose follows the title.
    "Wegener-Bergeron" matched 0 passages while 5 contained "Wegener-Bergeron" with an en dash.
  * Federal health sites render "Crohn's" with a curly apostrophe.
  * "total solids" appears nowhere: the articles say "total dissolved solids" and "total
    suspended solids", and neither contains the substring.

This checks each keyword against exactly what the author will see, using the same folding, and
reports the misses per lesson.

    DATABASE_URL=... PYTHONPATH=. python -m scripts.audit_blueprint_keywords \
        --blueprint data/courses/water-quality-b-2027.json
    DATABASE_URL=... PYTHONPATH=. python -m scripts.audit_blueprint_keywords --all
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, EventSourceMap, SourcePassage
from scripts.author_course_from_blueprint import BLUEPRINT_DIR, _fold


def audit(db, path: Path) -> dict:
    blueprint = json.loads(path.read_text())
    event = db.scalar(select(Event).where(
        Event.slug == blueprint["event_slug"], Event.season == blueprint["season"]))
    if event is None:
        return {"blueprint": path.name, "error": "no such event"}
    source_ids = db.scalars(select(EventSourceMap.source_id).where(
        EventSourceMap.event_id == event.id)).all()
    if not source_ids:
        return {"blueprint": path.name, "error": "event has no sources; ground it first"}
    haystacks = [
        _fold(f"{row.heading} {row.text}")
        for row in db.scalars(select(SourcePassage).where(
            SourcePassage.source_id.in_(source_ids)))
    ]
    report = {"blueprint": path.name, "event": event.slug, "passages": len(haystacks),
              "keywords": 0, "misses": []}
    for unit in blueprint["units"]:
        for lesson in unit["lessons"]:
            missing = []
            for term in lesson.get("keywords", []):
                report["keywords"] += 1
                needle = _fold(term)
                if not any(needle in hay for hay in haystacks):
                    missing.append(term)
            if missing:
                report["misses"].append({"lesson": lesson["slug"], "keywords": missing})
    report["missing_keywords"] = sum(len(m["keywords"]) for m in report["misses"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blueprint")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    paths = (sorted(Path(BLUEPRINT_DIR).glob("*.json")) if args.all
             else [Path(args.blueprint)])
    with SessionLocal() as db:
        for path in paths:
            print(json.dumps(audit(db, path), indent=2))


if __name__ == "__main__":
    main()
