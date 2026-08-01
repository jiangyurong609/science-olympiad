"""Put lesson checkpoints through the blind solver that every exam item already faces.

An exam item cannot reach `machine_validated` unless an independent solver — shown only the
stem and the choices, never the intended answer — reproduces the key. Lesson checkpoints
assess students in the same way and have never faced that gate at all: 73 in the pilot, 47 of
them model-written, none blind-solved. Assessment content was being held to two different
standards depending on which table it lived in.

This does not change any checkpoint. It records what an independent solver chose, so a
disagreement is visible to the editor reviewing that lesson. A solver disagreeing is not proof
the key is wrong — it is the single strongest signal that a human should look, which is
exactly what it is used for on the exam side.

    PYTHONPATH=. python -m scripts.solve_lesson_checkpoints --event rocks-and-minerals-b
    PYTHONPATH=. python -m scripts.solve_lesson_checkpoints --event ... --apply
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, LessonVersion
from app.services.model_generation import _independent_solve, _solver_verdict
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider


def checkpoint_key(block: dict) -> tuple[str, list, int | None]:
    """Stem, choices and answer index, across both checkpoint schemas.

    Authored blocks use `question`/`correct_index`; blocks written by `split_lessons` use
    `prompt`/`answer_index`. Assuming either one silently skips half the content.
    """
    stem = str(block.get("question") or block.get("prompt") or "").strip()
    choices = [c for c in (block.get("choices") or []) if str(c).strip()]
    index = block.get("correct_index")
    if index is None:
        index = block.get("answer_index")
    return stem, choices, index if isinstance(index, int) else None


def run(event_slug: str, apply: bool) -> dict:
    provider = OpenAICompatibleProvider()
    if apply and not provider.configured:
        raise SystemExit("no model provider configured")

    stats: Counter[str] = Counter()
    disagreements = []
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
            for block in content:
                if block.get("type") != "checkpoint":
                    continue
                stem, choices, index = checkpoint_key(block)
                if not stem or len(choices) < 2 or index is None:
                    # nothing to solve blindly; recorded rather than silently skipped
                    stats["unsolvable_shape"] += 1
                    continue
                stats["examined"] += 1
                if not apply:
                    continue
                try:
                    solved = _independent_solve(provider, stem, choices)
                except (ModelProviderError, ValueError, KeyError) as exc:
                    stats[f"failed:{type(exc).__name__}"] += 1
                    continue
                agreed, verdict = _solver_verdict(solved, index)
                block["solver_check"] = {
                    "chosen_index": solved.get("chosen_index"),
                    "confidence": solved.get("confidence"),
                    "ambiguous": bool(solved.get("ambiguous")),
                    "insufficient": bool(solved.get("insufficient")),
                    "agreed": agreed, "verdict": verdict,
                }
                changed = True
                stats[verdict] += 1
                if not agreed:
                    disagreements.append({
                        "lesson": lesson.title, "heading": block.get("heading") or "",
                        "verdict": verdict, "key": index,
                        "solver": solved.get("chosen_index"),
                        "model_written": bool(block.get("generated_by")
                                              or block.get("repaired_by")),
                    })
            if apply and changed:
                version.content = content
                flag_modified(version, "content")
        if apply:
            db.commit()
        else:
            db.rollback()
    return {"stats": stats, "disagreements": disagreements}


def main() -> None:
    ap = argparse.ArgumentParser(description="Blind-solve lesson checkpoints")
    ap.add_argument("--event", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    result = run(args.event, args.apply)
    stats = result["stats"]
    print("=" * 78)
    print(f"LESSON CHECKPOINT BLIND SOLVE — {args.event} "
          f"[{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 78)
    for key, value in sorted(stats.items()):
        print(f"  {key:34} {value}")
    if result["disagreements"]:
        print("-" * 78)
        print(f"{len(result['disagreements'])} checkpoint(s) the solver did not agree with:")
        for row in result["disagreements"]:
            flag = "model-written" if row["model_written"] else "authored"
            print(f"  [{flag:13}] {row['lesson'][:34]:36} {row['heading'][:26]:28} "
                  f"{row['verdict']} (key={row['key']} solver={row['solver']})")
    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")
    print("=" * 78)


if __name__ == "__main__":
    main()
