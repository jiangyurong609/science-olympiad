"""Put lesson checkpoints through the same gates every exam item already faces.

An exam item cannot reach `machine_validated` unless an independent solver — shown only the
stem and the choices, never the intended answer — reproduces the key. Lesson checkpoints
assess students in the same way and have never faced that gate at all: 73 in the pilot, 47 of
them model-written, none blind-solved. Assessment content was being held to two different
standards depending on which table it lived in.

Both halves of that gate run here: the blind solver asks whether the key is reproducible, and
the independent verifier asks whether the item is sound at all — factually supported,
unambiguous, internally consistent, age-appropriate. Running only the solver would leave these
half-gated.

This changes no checkpoint. It records what each judge concluded, so a disagreement is visible
to the editor reviewing that lesson. A judge objecting is not proof the key is wrong — it is
the strongest available signal that a human should look, which is exactly how it is used on
the exam side.

    PYTHONPATH=. python -m scripts.solve_lesson_checkpoints --event rocks-and-minerals-b
    PYTHONPATH=. python -m scripts.solve_lesson_checkpoints --event ... --apply
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, LessonVersion, ScientificClaim
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

VERIFIER_SYSTEM = (
    "Act as an independent scientific and assessment verifier. Return JSON with passed "
    "(boolean), errors (array), and warnings (array)."
)
VERIFIER_CHECKS = ["factual support", "single unambiguous answer", "answer consistency",
                   "age appropriateness"]


def _verify(provider, block: dict, stem: str, choices: list, index: int,
            claims: list) -> dict:
    """The second half of the gate exam items pass.

    The solver asks whether the key is reproducible; the verifier asks whether the item is
    sound — factually supported, unambiguous, internally consistent, age-appropriate. Running
    only the solver would leave lesson checkpoints half-gated, which is the asymmetry this
    script exists to remove.
    """
    return provider.generate_json(VERIFIER_SYSTEM, json.dumps({
        "claims": [{"id": c.id, "text": c.claim_text} for c in claims],
        "item": {"stem": stem, "choices": [str(c) for c in choices],
                 "correct_index": index, "explanation": block.get("explanation", "")},
        "checks": VERIFIER_CHECKS,
    })).payload


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
                claims = db.scalars(select(ScientificClaim).where(
                    ScientificClaim.id.in_(block.get("claim_ids") or [-1]))).all()
                try:
                    verified = _verify(provider, block, stem, choices, index, claims)
                except (ModelProviderError, ValueError, KeyError) as exc:
                    verified = {"passed": None, "errors": [f"verifier_failed:{type(exc).__name__}"]}
                verifier_errors = verified.get("errors") or []
                # some payloads put per-check findings in `passed`; a truthy list is not a pass
                verifier_passed = (verified.get("passed")
                                   if isinstance(verified.get("passed"), bool)
                                   else (not verifier_errors))
                block["verifier_check"] = {
                    "passed": verifier_passed,
                    "errors": verifier_errors,
                    "warnings": verified.get("warnings") or [],
                    "checks": (verified.get("passed")
                               if isinstance(verified.get("passed"), list) else []),
                }
                if verifier_passed is False:
                    stats["verifier_objected"] += 1
                    disagreements.append({
                        "lesson": lesson.title, "heading": block.get("heading") or "",
                        "verdict": f"verifier: {'; '.join(str(e)[:60] for e in verifier_errors)}",
                        "key": index, "solver": solved.get("chosen_index"),
                        "model_written": bool(block.get("generated_by")
                                              or block.get("repaired_by")),
                    })
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
