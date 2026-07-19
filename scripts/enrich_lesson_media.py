"""Make the deep courses visual: give each lesson an image gallery of the
specimens IT actually discusses, drawn from the licensed media library.

For every event that has an image library (rocks, entomology, astronomy,
solar-system and their divisions), each `auto-` lesson's text is scanned for
specimen names; matched specimens become an `image_gallery` block inserted after
the opening. Idempotent — replaces any prior auto-injected gallery (id
`auto-media-gallery`). Events without a library are left as text (correct).

Usage: python -m scripts.enrich_lesson_media [--min N] [--cap N]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, LessonVersion

MANIFEST = Path("app/static/media/manifest.json")
GALLERY_ID = "auto-media-gallery"
GENERIC = {"igneous", "sedimentary", "metamorphic"}


def _media_key(slug: str) -> str:
    return re.sub(r"-(b|c)$", "", slug)


def _terms(item: dict) -> set[str]:
    label = item.get("label", "")
    base = re.sub(r"\s*\(.*\)", "", label).strip()
    terms = {base}
    for paren in re.findall(r"\(([^)]+)\)", label):
        if paren.strip().lower() not in GENERIC and " " not in paren:
            terms.add(paren.strip())
    slug = re.sub(r"-(igneous|sedimentary|metamorphic)$", "", item.get("slug", "")).replace("-", " ")
    terms.add(slug)
    return {t for t in terms if len(t) >= 4}


def _library(manifest: dict) -> dict[str, list]:
    out: dict[str, list] = {}
    for key, items in manifest.items():
        entries = []
        for item in items:
            regex = re.compile("|".join(r"\b" + re.escape(t) + r"\b" for t in _terms(item)), re.I)
            entries.append((regex, item))
        out[key] = entries
    return out


def _block_text(block: dict) -> str:
    parts = [block.get("heading", ""), block.get("body", ""), block.get("prompt", "")]
    for card in block.get("cards", []) or []:
        parts += [card.get("name", ""), card.get("cue", ""), card.get("detail", "")]
    for step in block.get("steps", []) or []:
        parts += [step.get("label", ""), step.get("detail", "")] if isinstance(step, dict) else [str(step)]
    parts += [str(p) for p in (block.get("points", []) or [])]
    return " ".join(str(p) for p in parts)


def main() -> None:
    min_matches = int(sys.argv[sys.argv.index("--min") + 1]) if "--min" in sys.argv else 2
    cap = int(sys.argv[sys.argv.index("--cap") + 1]) if "--cap" in sys.argv else 6
    library = _library(json.loads(MANIFEST.read_text()))
    enriched = 0
    with SessionLocal() as db:
        for event in db.scalars(select(Event)).all():
            entries = library.get(_media_key(event.slug))
            if not entries:
                continue
            lessons = db.scalars(select(Lesson).where(
                Lesson.event_id == event.id, Lesson.slug.like("auto-%"))).all()
            for lesson in lessons:
                version = db.scalar(select(LessonVersion).where(
                    LessonVersion.lesson_id == lesson.id).order_by(LessonVersion.version.desc()))
                if not version or not isinstance(version.content, list):
                    continue
                content = [b for b in version.content if b.get("id") != GALLERY_ID]
                text = " ".join(_block_text(b) for b in content)
                seen, images = set(), []
                for regex, item in entries:
                    if item["url"] in seen:
                        continue
                    if regex.search(text):
                        images.append({"url": item["url"], "label": item["label"], "note": "",
                                       "alt": item["alt"], "attribution": item["attribution"],
                                       "license": item["license"]})
                        seen.add(item["url"])
                    if len(images) >= cap:
                        break
                if len(images) >= min_matches:
                    gallery = {
                        "id": GALLERY_ID, "type": "image_gallery",
                        "kicker": "Visual field guide",
                        "heading": "See What This Lesson Covers",
                        "body": "Study each specimen's distinctive appearance — fast, accurate visual recognition is exactly what identification stations reward.",
                        "images": images,
                    }
                    insert_at = 1 if content and content[0].get("type") == "opening" else 0
                    content.insert(insert_at, gallery)
                    enriched += 1
                version.content = content
                flag_modified(version, "content")
        db.commit()
    print(f"Added specimen galleries to {enriched} lessons.")


if __name__ == "__main__":
    main()
