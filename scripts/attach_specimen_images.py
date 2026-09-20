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
from app.services.scoring import is_figure_missing, references_figure, specimen_definitions

MANIFEST = Path("app/static/media/manifest.json")
GENERIC = {"igneous", "sedimentary", "metamorphic"}  # rock-type descriptors, not names


def _media_key(event_slug: str) -> str:
    # Seasoned slugs too: `rocks-and-minerals-b-2027` and `rocks-and-minerals-b` share one
    # media library. Stripping only the division suffix meant every 2027 event missed the
    # manifest entirely and reported "no images for this event", which is indistinguishable
    # from a library that does not hold the specimen.
    return re.sub(r"-(b|c)$", "", re.sub(r"-(19|20)\d{2}$", "", event_slug))


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


# An IDENTIFICATION item asks what the specimen in the photograph is; the specimen's name is
# the ANSWER, so it appears in the key and nowhere in the stem. `_attach` matches on the stem
# and therefore cannot help these — which is why 73 of Rocks & Minerals' image-bearing
# questions had no image, and why a 32-item station paper was withdrawn at 2 items. Matching
# the KEY restores them, and the photograph is the question rather than a decoration on it.
#
# Two things this must not do. It must not caption the image with the specimen's name, the way
# the stem-matched path does ("Specimen A: Photograph of Quartz") — that alt text is served in
# the DOM and would hand over the answer. And it must not fire on an item that merely happens
# to be keyed to a mineral while pointing at a graph or a table, so the stem has to look like
# an identification and must not be asking about a data display.
_IDENTIFY_RE = re.compile(
    r"\bidentify\b|\bwhat (?:is|are)\b|\bwhich (?:mineral|rock|specimen|sample)\b"
    r"|\bname (?:the|this)\b|\bthe (?:specimen|sample|mineral|rock) (?:shown|pictured|in the)",
    re.I)
_DATA_DISPLAY_RE = re.compile(r"\b(graph|chart|table|map|diagram|plot|axis|curve|key below)\b", re.I)


def _attach_from_key(db, event: Event, matchers: dict) -> tuple[int, int]:
    """Give an identification item the photograph it is asking about, captioned neutrally."""
    entries = matchers.get(_media_key(event.slug))
    if not entries:
        return 0, 0
    questions = db.scalars(select(Question).where(Question.event_id == event.id)).all()
    attached = 0
    for question in questions:
        stem = question.stem or ""
        if question.assets or not references_figure(stem):
            continue
        if not is_figure_missing(stem, question.assets):
            continue  # already answerable from the text; adding a photo would be decoration
        if not _IDENTIFY_RE.search(stem) or _DATA_DISPLAY_RE.search(stem):
            continue
        if specimen_definitions(stem):
            continue  # the stem names its specimens; _attach handles those
        choices = question.choices or []
        index = (question.answer_spec or {}).get("correct_index")
        if not isinstance(index, int) or index >= len(choices):
            continue
        choice = choices[index]
        answer = choice if isinstance(choice, str) else (choice or {}).get("text", "")
        asset = _match_asset(answer, entries)
        if not asset:
            continue
        question.assets = [{**asset, "alt": "Photograph of the specimen to identify"}]
        attached += 1
    db.commit()
    return attached, len(questions)


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
    from_key = "--from-key" in sys.argv
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
            if from_key:
                attached, n = _attach_from_key(db, event, matchers)
            else:
                attached, n = _attach(db, event, matchers, replace)
            if n:
                total += attached
                print(f"  {event.slug:26} attached images to {attached}/{n} questions")
        print(f"\nDone: {total} questions given specimen images.")


if __name__ == "__main__":
    main()
