"""Walk every published block the way the browser does, and report what a student would see.

Three defects reached students in a row and none of the existing audits could have caught any
of them, because every one of those audits asks whether content is *well-formed* or
*supported*: grounding checks a claim exists, the solver checks a key is reproducible, the
topical screen checks the subject. A block can satisfy all of that and still render as an
empty box.

  * 41 checkpoints carried their stem under `prompt` while the reader read `question`, so they
    arrived as a heading and four choices with no question.
  * 79 card blocks were keyed `property`/`meaning`/`competition_implication` while the reader
    read `name`/`cue`/`detail`, so real text rendered as the word "Concept".
  * 79 more had no content at all — five cards literally named "Concept" — and the reader
    drew five empty boxes, which tells a student there is something here they failed to see.

All three were found by a person clicking through the site. This asks the question they were
asking, for every block in the catalog: **put through `student_safe`, does this produce
something a student can actually read?**

It deliberately runs the same code path the API serves, not a re-implementation. An audit that
models the renderer would drift from it, and the drift is exactly the bug class.

    PYTHONPATH=. python -m scripts.audit_rendered_content
    DATABASE_URL=<prod> PYTHONPATH=. python -m scripts.audit_rendered_content --event crime-busters-b-2027
    PYTHONPATH=. python -m scripts.audit_rendered_content --fail-on-defect   # for CI
"""
from __future__ import annotations

import argparse
import re
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, LessonVersion
from app.services import lesson_blocks
from app.services.course_quality import UNAVAILABLE_SOURCE

# Text that names a document the student was never given. The pilot's checkpoints were repaired
# for this; the prose was never checked, and Crime Busters cites "the USC key" and "the BullSO
# key" in a block a student reads with neither in front of them.
DANGLING = re.compile(
    r"\b(the (USC|BullSO|provided|attached|supplied) (key|packet|sheet|materials?|stations?)"
    r"|the source (packet|materials?|document)|as (shown|provided) (above|in the packet))\b",
    re.IGNORECASE)

# What each block type must produce to be worth a step in the reader.
def defects_for(safe: dict, raw: dict) -> list[str]:
    kind = str(safe.get("type") or "")
    found: list[str] = []

    if safe.get("empty"):
        found.append("renders_as_nothing")

    if kind == lesson_blocks.CHECKPOINT:
        if not str(safe.get("question") or "").strip():
            found.append("checkpoint_without_a_question")
        if len([c for c in safe.get("choices") or [] if str(c).strip()]) < 2:
            found.append("checkpoint_without_choices")
        if lesson_blocks.checkpoint_answer_index(raw) is None:
            found.append("checkpoint_without_a_key")
    elif kind == "property_cards":
        if raw.get("cards") and not safe.get("cards"):
            found.append("cards_all_dropped_as_placeholder")
    elif kind == "worked_example":
        if not (raw.get("steps") or []):
            found.append("worked_example_without_steps")
        if not str(raw.get("prompt") or "").strip():
            found.append("worked_example_without_a_prompt")
    elif kind == "image_gallery":
        if not (raw.get("images") or []):
            found.append("gallery_without_images")
    elif kind == "video":
        if not str(raw.get("video_id") or "").strip():
            found.append("video_block_without_a_video")
    elif kind == "steps":
        if not (raw.get("steps") or raw.get("items") or safe.get("cards")):
            found.append("steps_block_without_steps")

    if not str(safe.get("heading") or "").strip() and kind != lesson_blocks.CHECKPOINT:
        found.append("block_without_a_heading")

    text = " ".join(str(v) for v in safe.values() if isinstance(v, str))
    if DANGLING.search(text) or UNAVAILABLE_SOURCE.search(text):
        found.append("cites_material_the_student_does_not_have")
    return found


def run(event_slug: str | None) -> dict:
    stats: Counter[str] = Counter()
    by_event: Counter[str] = Counter()
    rows: list[dict] = []
    with SessionLocal() as db:
        events = {e.id: e for e in db.scalars(select(Event)).all()}
        versions = {(v.lesson_id, v.version): v
                    for v in db.scalars(select(LessonVersion)).all()}
        query = select(Lesson).where(Lesson.status == "published")
        if event_slug:
            event = db.scalar(select(Event).where(Event.slug == event_slug))
            if not event:
                raise SystemExit(f"unknown event {event_slug!r}")
            query = query.where(Lesson.event_id == event.id)

        for lesson in db.scalars(query.order_by(Lesson.id)).all():
            version = versions.get((lesson.id, lesson.current_version))
            if version is None:
                continue
            slug = events[lesson.event_id].slug if lesson.event_id in events else "?"
            content = version.content or []
            stats["lessons"] += 1
            stats["blocks"] += len(content)
            lesson_defects = 0
            visible_steps = 0
            for index, raw in enumerate(content):
                # the exact call the API makes; not a model of it
                safe = lesson_blocks.student_safe(raw, index)
                if not safe.get("empty"):
                    visible_steps += 1
                for defect in defects_for(safe, raw):
                    stats[defect] += 1
                    lesson_defects += 1
                    rows.append({"event": slug, "lesson": lesson.title,
                                 "block": index, "type": safe.get("type"),
                                 "defect": defect})
            if lesson_defects:
                stats["lessons_with_a_defect"] += 1
                by_event[slug] += 1
            if visible_steps < 3:
                stats["lessons_with_under_3_visible_steps"] += 1
                rows.append({"event": slug, "lesson": lesson.title, "block": -1,
                             "type": "lesson", "defect": "too_little_left_to_read"})
    return {"stats": stats, "rows": rows, "by_event": by_event}


def main() -> None:
    ap = argparse.ArgumentParser(description="What a student would actually see, block by block")
    ap.add_argument("--event", default=None)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--fail-on-defect", action="store_true",
                    help="exit non-zero if any block renders as nothing (for CI)")
    args = ap.parse_args()

    result = run(args.event)
    stats, rows = result["stats"], result["rows"]
    print("=" * 92)
    print("RENDERED CONTENT AUDIT — every published block, through the serve path")
    print("=" * 92)
    for row in rows[:args.top]:
        print(f"  {row['defect'][:38]:40} {row['event'][:22]:24} "
              f"{row['lesson'][:24]:26} block {row['block']}")
    if len(rows) > args.top:
        print(f"  … {len(rows) - args.top} more")
    print("-" * 92)
    for key in sorted(k for k in stats if k not in {"lessons", "blocks"}):
        print(f"  {key:44} {stats[key]}")
    print(f"\n  {stats['lessons']} lessons, {stats['blocks']} blocks examined")
    if result["by_event"]:
        print("\n  worst events:")
        for slug, n in result["by_event"].most_common(8):
            print(f"    {slug:32} {n} lesson(s)")
    print("=" * 92)
    if args.fail_on_defect and stats.get("renders_as_nothing"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
