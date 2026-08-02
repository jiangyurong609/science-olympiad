"""Pin which lesson blocks each existing render covers.

`render_storyboard` now records `chapter_title` and `block_indexes` on every render, so the
reader states a recorded fact rather than recomputing the chapter plan from the storyboard's
current scenes. Renders made before that carry neither, and recomputation is only correct
while the storyboard is untouched and the chapter budget unchanged — an edited storyboard
yields different boundaries under the same chapter key, and the reader would then place a
video against sections it does not cover.

This closes that window for existing renders, and refuses where it cannot: the plan is
recomputed and accepted **only if it still produces this render's exact chapter key**. A
render whose key no longer appears was made from a storyboard that has since changed, which
is the case recomputation gets wrong — it is reported and left alone for a human.

    PYTHONPATH=. python -m scripts.backfill_render_chapters
    DATABASE_URL=<target> PYTHONPATH=. python -m scripts.backfill_render_chapters --apply
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.entities import VideoRender, VideoStoryboard
from app.services.video_chapters import plan_chapters


def run(apply: bool) -> dict:
    stats: Counter[str] = Counter()
    rows: list[dict] = []
    with SessionLocal() as db:
        boards = {b.id: b for b in db.scalars(select(VideoStoryboard)).all()}
        for render in db.scalars(select(VideoRender).where(
                VideoRender.status == "succeeded").order_by(VideoRender.id)).all():
            provenance = render.provenance or {}
            if "block_indexes" in provenance:
                stats["already_pinned"] += 1
                continue
            board = boards.get(render.storyboard_id)
            if board is None:
                stats["no_storyboard"] += 1
                continue
            plan = {c["key"]: c for c in plan_chapters(list(board.scenes or []))}
            chapter = plan.get(render.chapter)
            if chapter is None:
                # the storyboard no longer plans to this key: exactly the case a recomputation
                # would answer confidently and wrongly
                stats["plan_no_longer_matches"] += 1
                rows.append({"render": render.id, "chapter": render.chapter,
                             "outcome": "storyboard changed since render — left for a human"})
                continue
            blocks = sorted({i for scene in chapter["scenes"]
                             for i in (scene.get("block_indexes") or []) if isinstance(i, int)})
            stats["pinned"] += 1
            rows.append({"render": render.id, "chapter": render.chapter,
                         "outcome": f"{chapter['title'][:40]} -> blocks {blocks}"})
            if apply:
                render.provenance = {**provenance, "chapter_title": chapter["title"],
                                     "block_indexes": blocks}
                flag_modified(render, "provenance")
        if apply:
            db.commit()
        else:
            db.rollback()
    return {"stats": stats, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Pin chapter coverage onto existing renders")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    result = run(args.apply)
    print("=" * 78)
    print(f"RENDER CHAPTER BACKFILL [{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 78)
    for row in result["rows"]:
        print(f"  render {row['render']:<5} {row['chapter'][:34]:36} {row['outcome']}")
    print("-" * 78)
    for key, value in sorted(result["stats"].items()):
        print(f"  {key:24} {value}")
    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")
    print("=" * 78)


if __name__ == "__main__":
    main()
