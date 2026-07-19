"""Attach existing specimen images (app/static/media) to questions that name them.

Many parsed/generated questions reference a specimen ("...specimen B, conglomerate")
but carry no image. The media library already holds licensed Wikimedia Commons photos
per event (rocks-and-minerals, entomology, astronomy, solar-system). This matches each
image's label/aliases against a question's stem and fills question.assets so the exam
runner shows the picture.

Usage:
  python -m scripts.attach_specimen_images --event <event_id>
  python -m scripts.attach_specimen_images --all
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Question
from app.services.scoring import specimen_definitions

MANIFEST = Path("app/static/media/manifest.json")
GENERIC = {"igneous", "sedimentary", "metamorphic"}  # rock-type descriptors, not names


def _media_key(event_slug: str) -> str:
    return re.sub(r"-(b|c)$", "", event_slug)


def _terms(item: dict) -> set[str]:
    label = item.get("label", "")
    base = re.sub(r"\s*\(.*\)", "", label).strip()
    terms = {base}
    for paren in re.findall(r"\(([^)]+)\)", label):
        paren = paren.strip()
        if paren.lower() not in GENERIC and " " not in paren:  # e.g. "Mica"
            terms.add(paren)
    slug = re.sub(r"-(igneous|sedimentary|metamorphic)$", "", item.get("slug", "")).replace("-", " ")
    terms.add(slug)
    return {t for t in terms if len(t) >= 4}


def _build_matchers(manifest: dict) -> dict[str, list[tuple]]:
    matchers: dict[str, list[tuple]] = {}
    for key, items in manifest.items():
        entries = []
        for item in items:
            asset = {"url": item["url"], "alt": item.get("alt", ""),
                     "attribution": item.get("attribution", ""), "license": item.get("license", "")}
            for term in _terms(item):
                entries.append((re.compile(r"\b" + re.escape(term) + r"\b", re.I), asset, len(term)))
        # longest term first so specific names win
        matchers[key] = sorted(entries, key=lambda e: -e[2])
    return matchers


# Attach a photo for every specimen the stem DEFINES inline — "specimen A,
# basalt," or "Specimen A is shale and specimen B is conglomerate" — labelling
# each image with its specimen letter. Concept questions that merely mention a
# mineral name ("would crystallize olivine") define no specimen, so get nothing.
CAP = 4


def _match_asset(name: str, entries: list[tuple]) -> dict | None:
    for regex, asset, _ in entries:
        if regex.search(name):
            return asset
    return None


def _attach(db, event: Event, matchers: dict, replace: bool = False) -> tuple[int, int]:
    entries = matchers.get(_media_key(event.slug))
    if not entries:
        return 0, 0
    questions = db.scalars(select(Question).where(Question.event_id == event.id)).all()
    attached = 0
    for question in questions:
        if question.assets and not replace:
            continue
        assets: dict[str, dict] = {}
        for letter, name in specimen_definitions(question.stem or "").items():
            asset = _match_asset(name, entries)
            if asset and asset["url"] not in assets:
                assets[asset["url"]] = {**asset, "alt": f"Specimen {letter}: {asset['alt']}"}
        if assets:
            question.assets = list(assets.values())[:CAP]
            attached += 1
        elif replace and question.assets:
            question.assets = []  # clear stale/incorrect image
    db.commit()
    return attached, len(questions)


def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit(f"Media manifest not found: {MANIFEST}")
    manifest = json.load(open(MANIFEST))
    matchers = _build_matchers(manifest)
    replace = "--replace" in sys.argv
    with SessionLocal() as db:
        if "--event" in sys.argv:
            targets = [db.get(Event, int(sys.argv[sys.argv.index("--event") + 1]))]
        elif "--all" in sys.argv:
            keys = set(manifest.keys())
            targets = [e for e in db.scalars(select(Event)).all() if _media_key(e.slug) in keys]
        else:
            raise SystemExit(__doc__)
        total = 0
        for event in targets:
            attached, n = _attach(db, event, matchers, replace)
            if n:
                total += attached
                print(f"  {event.slug:26} attached images to {attached}/{n} questions")
        print(f"\nDone: {total} questions given specimen images.")


if __name__ == "__main__":
    main()
