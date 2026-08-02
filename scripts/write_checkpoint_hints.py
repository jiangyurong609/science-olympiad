"""Phase 8 — write a hint for each checkpoint, and prove it does not answer the question.

Scaffolding is the part of Phase 8 with nothing behind it: 18 `worked_example` and 19 `steps`
blocks exist as content, but **0 of the pilot's 73 checkpoints carry a hint** and nothing could
serve one. A hint is the cheapest scaffolding there is — it costs no new block type, no new
render, and no reviewer time beyond the lesson review already queued.

The risk is obvious and is the reason this is gated rather than generated: a hint that names
the answer converts a checkpoint into a reading comprehension test, and the failure is
invisible in the content — it reads like help. So each hint faces the same instrument every
other assessment artefact here faces, inverted.

    baseline: solver sees stem + choices                  -> can it pick the key?
    hinted:   solver sees stem + choices + the hint       -> can it pick the key now?

A hint is refused when the second succeeds and the first did not. A solver that already knew
the answer proves nothing about the hint; only a hint that *turns* a wrong answer into the key
is implicated. Refused hints are stored with `hint_too_revealing` rather than dropped, so the
reviewer sees what was rejected and why.

Nothing here publishes or approves. `lesson_hints` will not serve a hint for a lesson that has
not passed editor and SME review, so this writes content that stays dark until the lesson it
belongs to is approved — the same way Phase 7 produced drafts while review was the constraint.

    PYTHONPATH=. python -m scripts.write_checkpoint_hints --event rocks-and-minerals-b
    PYTHONPATH=. python -m scripts.write_checkpoint_hints --event ... --apply
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, LessonVersion
from app.services import lesson_blocks
from app.services.course_quality import block_text
from app.services.lesson_hints import HINT_FIELD, hint_is_too_revealing
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

HINT_SYSTEM = (
    "You write hints for Science Olympiad lesson checkpoints. Return ONLY valid JSON as "
    '{"hint": str}. A hint points at the idea the student should apply, or the part of the '
    "lesson worth re-reading. It must NOT name the correct choice, restate it, eliminate "
    "choices, or say 'the answer is'. One or two sentences. Write for a middle-school or "
    "early-high-school competitor."
)
SOLVER_SYSTEM = (
    "Answer the multiple-choice question. Return ONLY valid JSON as "
    '{"chosen_index": int}. You have not read the lesson.'
)


def _solve(provider, stem: str, choices: list, hint: str = "") -> int | None:
    payload = provider.generate_json(SOLVER_SYSTEM, json.dumps({
        "question": stem,
        "choices": [str(c) for c in choices],
        **({"hint": hint} if hint else {}),
    })).payload
    if isinstance(payload, str):
        payload = json.loads(payload)
    index = payload.get("chosen_index")
    return index if isinstance(index, int) else None


def write_hint(provider, block: dict, lesson_title: str, context: str) -> str:
    payload = provider.generate_json(HINT_SYSTEM, json.dumps({
        "lesson": lesson_title,
        "question": lesson_blocks.checkpoint_stem(block),
        "choices": [str(c) for c in (block.get("choices") or [])],
        "lesson_text": context[:6000],
    })).payload
    if isinstance(payload, str):
        payload = json.loads(payload)
    return " ".join(str(payload.get("hint") or "").split())[:400]


def run(event_slug: str, apply: bool, limit: int | None = None) -> dict:
    provider = OpenAICompatibleProvider()
    if apply and not provider.configured:
        raise SystemExit("no model provider configured; hints cannot be written")

    stats: Counter[str] = Counter()
    rows: list[dict] = []
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == event_slug))
        if not event:
            raise SystemExit(f"unknown event {event_slug!r}")
        lessons = db.scalars(select(Lesson).where(
            Lesson.event_id == event.id, Lesson.status != "withdrawn",
        ).order_by(Lesson.sequence, Lesson.id)).all()
        if limit:
            lessons = lessons[:limit]

        for lesson in lessons:
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version))
            if version is None:
                continue
            content = copy.deepcopy(list(version.content or []))
            context = " ".join(block_text(b) for b in content
                               if b.get("type") != lesson_blocks.CHECKPOINT)
            changed = False
            for block in content:
                if block.get("type") != lesson_blocks.CHECKPOINT:
                    continue
                if not lesson_blocks.is_gradeable(block):
                    stats["skipped_ungradeable"] += 1
                    continue
                if str(block.get(HINT_FIELD) or "").strip():
                    stats["already_had_a_hint"] += 1
                    continue
                stats["examined"] += 1
                if not apply:
                    continue

                stem = lesson_blocks.checkpoint_stem(block)
                choices = list(block.get("choices") or [])
                answer_index = lesson_blocks.checkpoint_answer_index(block)
                try:
                    hint = write_hint(provider, block, lesson.title, context)
                except (ModelProviderError, ValueError, KeyError) as exc:
                    stats[f"failed:{type(exc).__name__}"] += 1
                    continue
                if not hint:
                    stats["model_returned_nothing"] += 1
                    continue

                try:
                    baseline = _solve(provider, stem, choices)
                    hinted = _solve(provider, stem, choices, hint)
                except (ModelProviderError, ValueError, KeyError) as exc:
                    # unverified is not the same as safe; refuse rather than store it
                    stats[f"solver_failed:{type(exc).__name__}"] += 1
                    continue

                too_revealing = hint_is_too_revealing(hinted, answer_index, baseline)
                block[HINT_FIELD] = hint
                block["hint_check"] = {
                    "baseline_choice": baseline, "hinted_choice": hinted,
                    "answer_index": answer_index, "too_revealing": too_revealing,
                }
                if too_revealing:
                    block["hint_too_revealing"] = True
                    stats["refused_too_revealing"] += 1
                else:
                    block.pop("hint_too_revealing", None)
                    stats["written"] += 1
                rows.append({
                    "lesson": lesson.title,
                    "heading": block.get("heading") or "",
                    "outcome": ("refused — the solver could not answer this without the hint "
                                "and could with it") if too_revealing else "written",
                })
                changed = True
            if apply and changed:
                version.content = content
                flag_modified(version, "content")
        if apply:
            db.commit()
        else:
            db.rollback()
    return {"stats": stats, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Write and verify checkpoint hints")
    ap.add_argument("--event", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    result = run(args.event, args.apply, args.limit)
    print("=" * 78)
    print(f"CHECKPOINT HINTS — {args.event} [{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 78)
    for row in result["rows"][:20]:
        print(f"  {row['lesson'][:34]:36} {row['heading'][:20]:22} {row['outcome']}")
    print("-" * 78)
    for key, value in sorted(result["stats"].items()):
        print(f"  {key:28} {value}")
    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")
    else:
        print("\nhints stay dark until their lesson passes editor and SME review")
    print("=" * 78)


if __name__ == "__main__":
    main()
