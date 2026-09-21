"""Find checkpoints that are broken in ways a reader will not notice but a student will.

Subject-matter reviewers found three of these by reading. They are mechanical, so they
should be found mechanically, across every course at once:

* `correct_index` out of range, or missing — the item cannot be graded.
* `misconception_by_choice` keyed OUTSIDE the choice range. The map is keyed by choice
  index as a string, and `app/api/routes.py` serves `misconception_by_choice[selected]` to
  whoever picked that choice. A map keyed 1..4 against four choices (0..3) is shifted by
  one, so every rationale lands on the choice after the one it was written for. In
  Thermodynamics this told a student who picked `eta = 1 - T_H/T_C` — the inverted ratio —
  "Correct: this is the Carnot efficiency formula."
* A note on the CORRECT choice that reads like a correction, or a note on a WRONG choice
  that reads like praise. Either way the feedback contradicts the key.
* Duplicate choices — two identical options, one of which can never be right.
* An explanation that states a different answer than the key (e.g. the key is 40% and the
  explanation computes 60%).
* NUL bytes and replacement characters, which reach the student as a blank where a symbol
  such as an arrow should be.

    DATABASE_URL=... python -m scripts.audit_checkpoints
    DATABASE_URL=... python -m scripts.audit_checkpoints --event heredity-b-2027
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, LessonVersion

PRAISE = re.compile(r"^\W*(correct|that's right|right[:.]|yes[:.]|this is the correct)", re.I)
CORRECTION = re.compile(r"\b(this is (not|incorrect)|not the|reverses|inverts|instead of|"
                        r"omits|mistake|wrong|confuses|does not)\b", re.I)
BAD_CHARS = re.compile(r"[\x00�]")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def audit_lesson(slug: str, content: list) -> list[dict]:
    issues: list[dict] = []

    def add(kind: str, checkpoint: dict, detail: str) -> None:
        issues.append({"lesson": slug, "checkpoint": checkpoint.get("id") or
                       (checkpoint.get("heading") or "")[:40], "kind": kind, "detail": detail})

    for block in content or []:
        if not isinstance(block, dict) or block.get("type") != "checkpoint":
            if isinstance(block, dict) and BAD_CHARS.search(json.dumps(block)):
                issues.append({"lesson": slug, "checkpoint": f"[{block.get('type')}]",
                               "kind": "bad_characters", "detail": "NUL or replacement char"})
            continue
        choices = block.get("choices") or []
        correct = block.get("correct_index")
        notes = block.get("misconception_by_choice") or {}
        raw = json.dumps(block)

        if BAD_CHARS.search(raw):
            add("bad_characters", block, "NUL or replacement char in the item")
        if choices:
            if not isinstance(correct, int) or not (0 <= correct < len(choices)):
                add("ungradeable", block,
                    f"correct_index={correct!r} against {len(choices)} choices")
            duplicates = [c for c, n in Counter(choices).items() if n > 1]
            for choice in duplicates:
                add("duplicate_choice", block, f"choice appears twice: {choice[:70]!r}")
            for key in notes:
                if not str(key).isdigit() or not (0 <= int(key) < len(choices)):
                    add("note_key_out_of_range", block,
                        f"misconception key {key!r} against {len(choices)} choices "
                        f"(0..{len(choices) - 1})")
            for key, note in notes.items():
                if not str(key).isdigit():
                    continue
                index, text = int(key), str(note)
                if index == correct and CORRECTION.search(text):
                    add("note_corrects_the_key", block,
                        f"note on the KEYED choice reads like a correction: {text[:90]!r}")
                if index != correct and PRAISE.search(text):
                    add("note_praises_a_wrong_choice", block,
                        f"note on wrong choice {index} reads like praise: {text[:90]!r}")

        explanation = str(block.get("explanation") or "")
        if explanation and isinstance(correct, int) and 0 <= correct < len(choices):
            keyed = PERCENT.findall(str(choices[correct]))
            stated = PERCENT.findall(explanation)
            if keyed and stated and not (set(keyed) & set(stated)):
                add("explanation_disagrees_with_key", block,
                    f"key says {keyed}, explanation says {stated}")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    found: list[dict] = []
    with SessionLocal() as db:
        query = select(Event).where(Event.season == 2027)
        if args.event:
            query = select(Event).where(Event.slug == args.event)
        for event in db.scalars(query.order_by(Event.slug)).all():
            for lesson in db.scalars(select(Lesson).where(Lesson.event_id == event.id)).all():
                version = db.scalar(select(LessonVersion).where(
                    LessonVersion.lesson_id == lesson.id)
                    .order_by(LessonVersion.version.desc()))
                if version is None:
                    continue
                for issue in audit_lesson(lesson.slug or str(lesson.id), version.content or []):
                    found.append({"event": event.slug, **issue})
    if args.json:
        print(json.dumps(found, indent=2))
        return
    by_kind = Counter(i["kind"] for i in found)
    print(f"{len(found)} issue(s) across {len({i['event'] for i in found})} event(s)\n")
    for kind, count in by_kind.most_common():
        print(f"  {count:4d}  {kind}")
    print()
    for issue in found:
        print(f"[{issue['kind']}] {issue['event']} / {issue['lesson']} / "
              f"{issue['checkpoint']}\n      {issue['detail']}")


if __name__ == "__main__":
    main()
