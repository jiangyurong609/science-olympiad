"""Rewrite checkpoints that assess a student on material they were never given.

Six pilot checkpoints ask things like "which statement best follows from the source packet?"
or "in the source's 1500 °C solid-solution example, which proportions are accepted?". A
student holds the lesson, never the packet it was written from, so these are unanswerable —
the same defect as a question about a figure that was never imported.

This is repair, not authoring judgement. The question must end up answerable **from its own
lesson part and nothing else**, so the rewrite is given that part's text and forbidden to
introduce anything not already in it. The answer is preserved where the original had a
defensible one; only the dangling reference is removed.

Rewritten blocks are tagged `repaired_by` and their original is kept in `superseded`, so the
editor reviewing this lesson sees exactly what changed and can reject it. Nothing here
approves anything — the lesson stays in whatever review state it was already in.

    PYTHONPATH=. python -m scripts.repair_dangling_checkpoints --event rocks-and-minerals-b
    PYTHONPATH=. python -m scripts.repair_dangling_checkpoints --event ... --apply
"""
from __future__ import annotations

import argparse
import copy
import json

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, LessonVersion
from app.services.course_quality import UNAVAILABLE_SOURCE, block_text
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

SYSTEM = (
    "You repair Science Olympiad checkpoint questions. Return ONLY valid JSON. "
    "The rewritten question must be answerable using nothing but the lesson text supplied. "
    "Never refer to 'the source', 'the source packet', 'the provided stations', or any "
    "material outside the lesson. Never introduce a fact the lesson text does not contain."
)


def _lesson_text(blocks: list[dict], exclude_index: int) -> str:
    return " ".join(block_text(b) for i, b in enumerate(blocks) if i != exclude_index)


def repair_block(provider, block: dict, lesson_title: str, context: str) -> dict | None:
    payload = provider.generate_json(SYSTEM, (
        f"Lesson part: {lesson_title!r}\n\n"
        f"This checkpoint refers to material the student does not have, so it cannot be "
        f"answered:\n{json.dumps({k: v for k, v in block.items() if k != 'superseded'})}\n\n"
        f"Rewrite it so it tests the same idea using only what this lesson part says:\n\n"
        f"{context[:7000]}\n\n"
        f"Keep the same cognitive level. Keep four choices with exactly one defensible "
        f'answer. Return {{"heading": str, "prompt": str, "choices": [str x4], '
        f'"answer_index": int, "explanation": str}}.'
    )).payload
    if isinstance(payload, str):
        payload = json.loads(payload)

    choices = [str(c).strip() for c in (payload.get("choices") or []) if str(c).strip()]
    answer_index = payload.get("answer_index")
    prompt = str(payload.get("prompt") or "").strip()
    if len(choices) < 3 or not prompt:
        return None
    if not isinstance(answer_index, int) or not 0 <= answer_index < len(choices):
        return None
    # Checkpoint blocks do not share a schema across generations: the originally authored ones
    # use `question`/`correct_index`, while those written by `split_lessons` use
    # `prompt`/`answer_index`. Writing the wrong pair leaves the original dangling text in
    # place beside an unread new field — which the guard below caught on all six.
    prompt_key = "question" if "question" in block else "prompt"
    index_key = "correct_index" if "correct_index" in block else "answer_index"
    trimmed = choices[:4]
    rewritten = {
        **block,
        "heading": str(payload.get("heading") or block.get("heading") or "Checkpoint")[:200],
        prompt_key: prompt[:1000],
        "choices": trimmed,
        index_key: min(answer_index, len(trimmed) - 1),
        "explanation": str(payload.get("explanation") or "")[:1000],
        "repaired_by": "repair_dangling_checkpoints",
        "superseded": {k: v for k, v in block.items() if k != "superseded"},
    }
    # the whole point is removing the dangling reference; refuse a rewrite that kept one
    if UNAVAILABLE_SOURCE.search(block_text(
            {k: v for k, v in rewritten.items() if k != "superseded"})):
        return None
    return rewritten


def run(event_slug: str, apply: bool) -> dict:
    provider = OpenAICompatibleProvider()
    if apply and not provider.configured:
        raise SystemExit("no model provider configured")

    stats = {"examined": 0, "repaired": 0, "refused": 0, "failed": 0}
    rows = []
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == event_slug))
        if not event:
            raise SystemExit(f"unknown event {event_slug!r}")
        for lesson in db.scalars(select(Lesson).where(
            Lesson.event_id == event.id, Lesson.status != "withdrawn",
        ).order_by(Lesson.sequence, Lesson.id)).all():
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version))
            if version is None:
                continue
            content = copy.deepcopy(list(version.content or []))
            changed = False
            for index, block in enumerate(content):
                if block.get("type") != "checkpoint":
                    continue
                if not UNAVAILABLE_SOURCE.search(block_text(block)):
                    continue
                stats["examined"] += 1
                heading = block.get("heading") or ""
                if not apply:
                    rows.append({"lesson": lesson.title, "heading": heading,
                                 "action": "would repair"})
                    continue
                try:
                    rewritten = repair_block(provider, block, lesson.title,
                                             _lesson_text(content, index))
                except (ModelProviderError, ValueError, KeyError) as exc:
                    stats["failed"] += 1
                    rows.append({"lesson": lesson.title, "heading": heading,
                                 "action": f"failed: {type(exc).__name__}"})
                    continue
                if rewritten is None:
                    stats["refused"] += 1
                    rows.append({"lesson": lesson.title, "heading": heading,
                                 "action": "refused — rewrite still dangled or was malformed"})
                    continue
                content[index] = rewritten
                changed = True
                stats["repaired"] += 1
                rows.append({"lesson": lesson.title, "heading": heading,
                             "action": "repaired"})
            if apply and changed:
                version.content = content
                flag_modified(version, "content")
        if apply:
            db.commit()
        else:
            db.rollback()
    return {"stats": stats, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Repair checkpoints citing unavailable material")
    ap.add_argument("--event", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    result = run(args.event, args.apply)
    print("=" * 76)
    print(f"DANGLING CHECKPOINT REPAIR — {args.event} "
          f"[{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 76)
    for row in result["rows"]:
        print(f"  {row['lesson'][:40]:42} {row['heading'][:26]:28} {row['action']}")
    print("-" * 76)
    for key, value in result["stats"].items():
        print(f"  {key:10} {value}")
    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")


if __name__ == "__main__":
    main()
