"""Replace placeholder source titles with each page's own title.

`ground_event` registered every open source as "<publisher> — <domain> reference", so the
resource library listed 102 Botany rows with one identical title. New sources are now titled
from their page; this backfills the ones already registered, using the retained snapshot's
text where the URL alone is not enough.

    DATABASE_URL=... python -m scripts.retitle_sources            # dry run
    DATABASE_URL=... python -m scripts.retitle_sources --apply
"""
from __future__ import annotations

import argparse
import re
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Source, SourceSnapshot
from scripts.ground_event import derive_source_title

PLACEHOLDER = re.compile(r"\s—\s[\w\s-]+ reference$")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    changed: Counter[str] = Counter()
    with SessionLocal() as db:
        planned: list[tuple[Source, str]] = []
        for source in db.scalars(select(Source).where(Source.url.like("http%"))).all():
            if not PLACEHOLDER.search(source.title or ""):
                continue
            snapshot = db.scalar(select(SourceSnapshot).where(
                SourceSnapshot.source_id == source.id).order_by(SourceSnapshot.id.desc()))
            planned.append((source, derive_source_title(
                source.url, (snapshot.extracted_text or "")[:400] if snapshot else "")))
        # "Mitosis" from Wikipedia, genome.gov and MedlinePlus are three different pages. Two
        # rows with one title are indistinguishable in the library, so a title shared across
        # publishers carries the publisher's host.
        hosts_by_title: dict[str, set[str]] = {}
        for source, title in planned:
            hosts_by_title.setdefault(title, set()).add(source.url.split("/")[2])
        for source, title in planned:
            host = source.url.split("/")[2]
            if len(hosts_by_title.get(title, ())) > 1:
                title = f"{title} ({host.removeprefix('www.')})"
            if title and title != source.title:
                changed[source.url.split("/")[2]] += 1
                if len(changed) <= 3 and sum(changed.values()) <= 6:
                    print(f"  {source.title[:48]!r:52s} -> {title!r}")
                if args.apply:
                    source.title = title[:500]
        if args.apply:
            db.commit()
    print(f"\n{'retitled' if args.apply else 'would retitle'} {sum(changed.values())} sources:",
          dict(changed.most_common(8)))


if __name__ == "__main__":
    main()
