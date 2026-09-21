"""Repair checkpoint defects that reach a student as wrong feedback or a wrong key.

Three subject-matter reviewers each found one of these by reading; `audit_checkpoints`
found five. They are repaired here rather than by re-authoring, because re-authoring
creates a new LessonVersion and `disposition_version` pins a lesson's publication decision
to the version it was made about — a new version takes the lesson dark until it is
re-dispositioned. These are surgical edits to the text of the version already published.

What it repairs:

* **off_by_one_notes** — `misconception_by_choice` keyed 1..n against choices 0..n-1. The
  API serves `misconception_by_choice[str(selected_index)]`, so every rationale lands on
  the choice after the one it was written for. In Thermodynamics a student who picked
  `eta = 1 - T_H/T_C`, the inverted ratio, was shown "Correct: this is the Carnot
  efficiency formula." Only applied when the keys are exactly {1..n} for n choices, which
  is the unambiguous signature of a 1-indexed map.
* **nul_bytes** — U+0000 where an arrow or symbol belongs, reaching the student as a blank
  in items whose whole point is the sequence the arrows express.

Everything else a reviewer found — a mis-keyed answer, a wrong definition — needs a human
decision and is NOT touched here.

    DATABASE_URL=... python -m scripts.repair_checkpoint_defects
    DATABASE_URL=... python -m scripts.repair_checkpoint_defects --apply
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.entities import AuditLog, Event, Lesson, LessonVersion

ARROW = "→"


def _fix_notes(block: dict) -> str | None:
    choices = block.get("choices") or []
    notes = block.get("misconception_by_choice") or {}
    if not choices or not notes:
        return None
    keys = {str(k) for k in notes}
    expected_one_indexed = {str(i) for i in range(1, len(choices) + 1)}
    if keys != expected_one_indexed:
        return None
    block["misconception_by_choice"] = {str(int(k) - 1): v for k, v in notes.items()}
    return (f"re-keyed {len(notes)} misconception notes from 1..{len(choices)} "
            f"to 0..{len(choices) - 1}")


def _walk_strings(value, replace):
    """Rewrite every string in a nested structure. NUL bytes hide anywhere, not just in
    the keys a checkpoint happens to use."""
    if isinstance(value, str):
        return replace(value)
    if isinstance(value, list):
        return [_walk_strings(v, replace) for v in value]
    if isinstance(value, dict):
        return {k: _walk_strings(v, replace) for k, v in value.items()}
    return value


def _count_nuls(value) -> int:
    if isinstance(value, str):
        return value.count("\x00")
    if isinstance(value, list):
        return sum(_count_nuls(v) for v in value)
    if isinstance(value, dict):
        return sum(_count_nuls(v) for v in value.values())
    return 0


# A NUL stands where a symbol was lost, and the symbol is NOT always the same one. In the
# Disease Detectives causal-graph item the text is "X _ Z _ Y, where Z causes both X and Y",
# so the graph is X <- Z -> Y: a confounder. Replacing both with a forward arrow would make
# it X -> Z -> Y, a causal CHAIN, which is precisely the distinction the item tests. Items
# whose arrows are not uniform are listed here and everything else takes the forward arrow.
DIRECTED_FIXES: dict[str, list[str]] = {
    "dags-component-causes-and-grade-check-1": ["\u2190", "\u2192"],
}


def _fix_nuls(block: dict) -> str | None:
    # NOT `"\x00" in json.dumps(block)` — dumps escapes a NUL to the six characters
    # \u0000, so that test is always False and the first version of this script reported
    # zero NULs in two lessons that each had several. Walk the strings themselves.
    count = _count_nuls(block)
    if not count:
        return None
    sequence = DIRECTED_FIXES.get(str(block.get("id")))
    if sequence:
        def replace(text: str) -> str:
            out, index = [], 0
            for char in text:
                if char == "\x00":
                    out.append(sequence[index % len(sequence)])
                    index += 1
                else:
                    out.append(char)
            return "".join(out)
    else:
        def replace(text: str) -> str:
            return text.replace("\x00", ARROW)
    repaired = _walk_strings(block, replace)
    block.clear()
    block.update(repaired)
    symbol = "".join(sequence) if sequence else ARROW
    return f"replaced {count} NUL byte(s) with '{symbol}'"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    tally: Counter[str] = Counter()
    with SessionLocal() as db:
        for event in db.scalars(select(Event).where(Event.season == 2027)
                                .order_by(Event.slug)).all():
            for lesson in db.scalars(select(Lesson).where(
                    Lesson.event_id == event.id)).all():
                version = db.scalar(select(LessonVersion).where(
                    LessonVersion.lesson_id == lesson.id)
                    .order_by(LessonVersion.version.desc()))
                if version is None or not version.content:
                    continue
                content = copy.deepcopy(version.content)
                changes: list[str] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    where = block.get("id") or block.get("type")
                    for fixer, kind in ((_fix_nuls, "nul_bytes"),
                                        (_fix_notes, "off_by_one_notes")):
                        if kind == "off_by_one_notes" and block.get("type") != "checkpoint":
                            continue
                        note = fixer(block)
                        if note:
                            changes.append(f"{where}: {note}")
                            tally[kind] += 1
                if not changes:
                    continue
                print(f"{event.slug} / {lesson.slug}")
                for change in changes:
                    print(f"    {change}")
                if args.apply:
                    version.content = content
                    flag_modified(version, "content")
                    db.add(AuditLog(
                        actor_user_id=None, action="lesson.checkpoint_defect_repaired",
                        entity_type="lesson_version", entity_id=str(version.id),
                        details={"event": event.slug, "lesson": lesson.slug,
                                 "version": version.version, "changes": changes}))
        if args.apply:
            db.commit()
    print(f"\n{'applied' if args.apply else 'dry run'}: {dict(tally)}")


if __name__ == "__main__":
    main()
