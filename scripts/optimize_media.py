"""Bound the size of the specimen image library, and rewrite what points at it.

The library was stored exactly as Wikimedia served it: 199 files, 398 MB, a median of
1.2 MB and a 36 MB Ganymede PNG at 3445x3445. A station question shows up to four
specimens, so a single identification item could pull 20 MB over a school connection
before a student sees anything, and the whole library is baked into the Cloud Run image.

Nothing in this product displays a specimen larger than a card. 1600 px on the long edge
is more than a student can use and roughly 3% of the bytes.

PNG is kept only where transparency is actually used; everything else becomes progressive
JPEG, so a file's name can change, and this rewrites the manifest, `Question.assets` and
lesson block content together rather than leaving dangling URLs behind.

    python -m scripts.optimize_media --dry-run
    python -m scripts.optimize_media --apply            # files + manifest
    DATABASE_URL=... python -m scripts.optimize_media --apply --rewrite-db
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

MEDIA_DIR = Path("app/static/media")
MANIFEST = MEDIA_DIR / "manifest.json"
MAX_EDGE = 1600
JPEG_QUALITY = 85


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        return image.convert("RGBA").getchannel("A").getextrema()[0] < 255
    return False


def optimize(path: Path, apply: bool) -> tuple[Path, int, int]:
    """Return (new path, bytes before, bytes after). No-op files report unchanged."""
    before = path.stat().st_size
    with Image.open(path) as image:
        image.load()
        keep_png = path.suffix.lower() == ".png" and _has_alpha(image)
        target = path if keep_png else path.with_suffix(".jpg")
        if max(image.size) > MAX_EDGE:
            image.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        elif target == path and before <= 400_000:
            return path, before, before  # already small and already the right container
        if not apply:
            return target, before, before
        if keep_png:
            image.save(target, "PNG", optimize=True)
        else:
            image.convert("RGB").save(target, "JPEG", quality=JPEG_QUALITY,
                                      optimize=True, progressive=True)
    if target != path:
        path.unlink()
    return target, before, target.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rewrite-db", action="store_true",
                        help="update Question.assets and lesson content for renamed files")
    args = parser.parse_args()
    apply = args.apply and not args.dry_run

    manifest = json.loads(MANIFEST.read_text())
    renames: dict[str, str] = {}
    before_total = after_total = 0
    for event, items in manifest.items():
        for item in items:
            path = Path("app" + item["url"])
            if not path.exists():
                print(f"  MISSING {item['url']}")
                continue
            new_path, before, after = optimize(path, apply)
            before_total += before
            after_total += after
            new_url = "/" + str(new_path.relative_to("app")).replace("\\", "/")
            if new_url != item["url"]:
                renames[item["url"]] = new_url
                item["url"] = new_url
    print(f"{before_total / 1e6:.0f} MB -> {after_total / 1e6:.0f} MB "
          f"({len(renames)} files renamed)")
    if not apply:
        print("dry run; nothing written")
        return
    MANIFEST.write_text(json.dumps(manifest, indent=2))

    if args.rewrite_db and renames:
        from sqlalchemy import select

        from app.core.database import SessionLocal
        from app.models.entities import LessonVersion, Question

        def swap(text: str) -> str:
            for old, new in renames.items():
                text = text.replace(old, new)
            return text

        with SessionLocal() as db:
            touched = 0
            for question in db.scalars(select(Question)).all():
                raw = json.dumps(question.assets or [])
                if any(old in raw for old in renames):
                    question.assets = json.loads(swap(raw))
                    touched += 1
            versions = 0
            for version in db.scalars(select(LessonVersion)).all():
                raw = json.dumps(version.content or {})
                if any(old in raw for old in renames):
                    version.content = json.loads(swap(raw))
                    versions += 1
            db.commit()
            print(f"rewrote {touched} questions and {versions} lesson versions")


if __name__ == "__main__":
    main()
