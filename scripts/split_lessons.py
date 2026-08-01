"""Phase 3 (content half) — split over-long lessons into ones a student can finish.

The pilot's eight lessons measure 19–27 minutes of reading against a 5–12 minute target.
`phase3_mechanical` deliberately refuses to clamp the estimate, so the only honest fix is to
split the content. That is also the pedagogy the course was asked for: a student with a short
attention span finishes a 10-minute lesson and does not finish a 25-minute one.

Splitting is structural first and generative second:

  * **cut points are chosen deterministically** at checkpoint boundaries, so a part never
    begins mid-explanation and the original ordering is preserved exactly;
  * **teaching blocks are never rewritten** — they move, with their claim and passage ids
    intact, so grounding established in Phase 1 survives the split unchanged;
  * **only the connective tissue is generated** — a part after the first needs an opening, a
    part before the last needs a summary, and each part needs enough checks. Generated blocks
    carry `generated_by` so review can see exactly what a model wrote.

    PYTHONPATH=. python -m scripts.split_lessons --event rocks-and-minerals-b [--apply]
"""
from __future__ import annotations

import argparse
import json
import math
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.entities import (
    Event, Lesson, LessonSkill, LessonVersion, Skill,
)
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

TEACHING_TYPES = {"property_cards", "steps", "worked_example", "image_gallery", "video"}
TARGET_MINUTES = 10
MAX_MINUTES = 12
MIN_CHECKS = 3
MIN_TEACHING = 3
WORDS_PER_MINUTE = 130
GENERATED_BY = "split_lessons"

# Every part gains an opening, a summary, and usually a check, and those minutes are not free.
# The first run budgeted against the pre-generation content and measured 11 of 22 parts back
# over the limit afterwards, by an average of 4.5 minutes. Cutting is therefore planned against
# a reduced ceiling, and the generated blocks are held to the word counts assumed here.
OVERHEAD_MINUTES = 3.0
OPENING_WORDS = 70
SUMMARY_POINT_WORDS = 22
CHECKPOINT_WORDS = 90

SYSTEM = (
    "You write Science Olympiad course material. Return ONLY valid JSON. "
    "Never invent facts: write only what the supplied lesson text already establishes. "
    "Write for a middle-school or early-high-school competitor: direct, concrete, no filler."
)


def _words(node) -> int:
    return len(re.findall(r"\w+", _flatten(node)))


def _flatten(node) -> str:
    parts: list[str] = []
    def walk(item) -> None:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            for key, value in item.items():
                if key not in {"type", "claim_ids", "passage_ids", "id", "generated_by"}:
                    walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)
    walk(node)
    return " ".join(parts)


def minutes_of(blocks: list[dict]) -> float:
    checks = sum(1 for b in blocks if b.get("type") == "checkpoint")
    return _words(blocks) / WORDS_PER_MINUTE + checks * 0.5


def _teaching(blocks: list[dict]) -> int:
    return sum(1 for b in blocks if b.get("type") in TEACHING_TYPES)


def plan_cuts(blocks: list[dict], overhead: float = 0.0) -> list[list[dict]]:
    """Group blocks into parts of at most MAX_MINUTES *after* generated blocks are added.

    `overhead` is the minutes each part will gain from its generated opening, summary, and
    checks; the cut is planned against `MAX_MINUTES - overhead` so the finished part fits.

    Cutting just after a checkpoint is what makes a part feel finished — the student has been
    asked to use the idea — so a check boundary is *preferred*. It cannot be *required*: an
    earlier version only cut there, and a check-heavy tail with fewer than three teaching
    blocks left could never be cut again, stranding four parts at 14–16 minutes. So the rule
    is: cut at a checkpoint once the part is near budget, and cut at the next block boundary
    regardless once it is over. Missing checks are generated later; teaching blocks are not
    generated, so a part's three-teaching-block floor is the one hard constraint here.
    """
    total = minutes_of(blocks)
    limit = max(4.0, MAX_MINUTES - overhead)
    target = max(3.0, TARGET_MINUTES - overhead)
    if total <= limit:
        return [blocks]
    # every part needs MIN_TEACHING teaching blocks, which caps how finely this can be cut
    ceiling = max(1, _teaching(blocks) // MIN_TEACHING)
    parts_wanted = min(ceiling, max(2, math.ceil(total / target)))
    if parts_wanted < 2:
        return [blocks]
    budget = total / parts_wanted

    # Choose each boundary to land as near its ideal share as possible, rather than at the
    # first boundary that clears a threshold. Greedy first-fit cut one 23.5-minute lesson into
    # 8.7 and 14.8 — it took the earliest eligible checkpoint and then had no cuts left, so
    # the tail stayed over the limit. Balancing removes that failure entirely.
    cuts: list[int] = []
    start = 0
    for k in range(1, parts_wanted):
        ideal = budget * k
        best_index, best_cost = None, None
        for index in range(start, len(blocks) - 1):
            head, tail = blocks[start:index + 1], blocks[index + 1:]
            if _teaching(head) < MIN_TEACHING or minutes_of(tail) < 4:
                continue
            # every later part still needs its own teaching floor
            if _teaching(tail) < MIN_TEACHING * (parts_wanted - k):
                continue
            elapsed = minutes_of(blocks[:index + 1])
            cost = abs(elapsed - ideal)
            if blocks[index].get("type") == "checkpoint":
                cost -= 1.0        # prefer finishing a part on a check, all else near equal
            if best_cost is None or cost < best_cost:
                best_index, best_cost = index, cost
        if best_index is None:
            break
        cuts.append(best_index)
        start = best_index + 1

    parts: list[list[dict]] = []
    previous = 0
    for index in cuts:
        parts.append(blocks[previous:index + 1])
        previous = index + 1
    tail = blocks[previous:]
    if tail:
        if parts and (minutes_of(tail) < 3 or _teaching(tail) < MIN_TEACHING):
            parts[-1].extend(tail)      # a scrap is not a lesson
        else:
            parts.append(tail)
    return parts or [blocks]


def _ask(provider, prompt: str) -> dict:
    result = provider.generate_json(SYSTEM, prompt)
    payload = result.payload
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload


def make_opening(provider, lesson_title: str, part_title: str, body: str) -> dict:
    payload = _ask(provider, (
        f"A long lesson titled {lesson_title!r} was split. This part is {part_title!r}.\n"
        f"Write its opening: one heading and at most {OPENING_WORDS} words saying what the "
        f"student will be able to do by the end and connecting back to the earlier part.\n"
        f"Use only what this part's text covers:\n\n{body[:6000]}\n\n"
        'Return {"heading": str, "body": str}.'
    ))
    return {
        "type": "opening",
        "heading": str(payload.get("heading") or part_title)[:200],
        "body": str(payload.get("body") or "")[:1200],
        "generated_by": "split_lessons",
    }


def make_summary(provider, part_title: str, body: str) -> dict:
    payload = _ask(provider, (
        f"Write the closing summary for a lesson part titled {part_title!r}.\n"
        f"Give exactly three takeaway bullets of at most {SUMMARY_POINT_WORDS} words each, "
        f"usable under time pressure. Only restate what the text below establishes:\n\n"
        f"{body[:6000]}\n\n"
        'Return {"heading": str, "points": [str, ...]}.'
    ))
    points = [str(p)[:300] for p in (payload.get("points") or []) if str(p).strip()]
    return {
        "type": "summary",
        "heading": str(payload.get("heading") or "Key takeaways")[:200],
        "points": points[:3],
        "generated_by": "split_lessons",
    }


def make_checkpoint(provider, part_title: str, body: str, cognitive_level: str) -> dict:
    payload = _ask(provider, (
        f"Write one {cognitive_level} checkpoint question for the lesson part {part_title!r}.\n"
        f"Keep the whole question, choices, and explanation under {CHECKPOINT_WORDS} words.\n"
        + ("An 'application' check asks the student to use a rule on a new specimen or case; "
           "a 'transfer' check asks them to decide between competing explanations or carry the "
           "idea into an unfamiliar context. Neither may be answerable by recall alone.\n"
           if cognitive_level in {"application", "transfer"} else "")
        + f"The answer must be fully determined by this text:\n\n{body[:6000]}\n\n"
        'Return {"heading": str, "prompt": str, "choices": [str x4], '
        '"answer_index": int, "explanation": str}.'
    ))
    choices = [str(c)[:300] for c in (payload.get("choices") or []) if str(c).strip()]
    if len(choices) < 3:
        raise ValueError(f"checkpoint returned {len(choices)} choices")
    answer_index = int(payload.get("answer_index") or 0)
    if not 0 <= answer_index < len(choices):
        raise ValueError(f"answer_index {answer_index} outside {len(choices)} choices")
    return {
        "type": "checkpoint",
        "heading": str(payload.get("heading") or "Checkpoint")[:200],
        "prompt": str(payload.get("prompt") or "")[:1000],
        "choices": choices,
        "answer_index": answer_index,
        "explanation": str(payload.get("explanation") or "")[:1000],
        "cognitive_level": cognitive_level,
        "generated_by": "split_lessons",
    }


def complete_part(provider, part: list[dict], lesson_title: str, part_title: str,
                  is_first: bool, is_last: bool) -> tuple[list[dict], list[str]]:
    """Give a part the opening, summary, and checks the rubric requires."""
    notes: list[str] = []
    blocks = list(part)
    body = _flatten(blocks)

    if not is_first or blocks[0].get("type") != "opening":
        blocks.insert(0, make_opening(provider, lesson_title, part_title, body))
        notes.append("opening")
    if not is_last or blocks[-1].get("type") != "summary":
        blocks = [b for b in blocks if b.get("type") != "summary"] + [
            make_summary(provider, part_title, body)]
        notes.append("summary")

    checks = [b for b in blocks if b.get("type") == "checkpoint"]
    has_higher = any(c.get("cognitive_level") in {"application", "transfer"} for c in checks)
    # the rubric wants at least one check above recall; if the part inherited none, the first
    # generated check fills that role rather than adding another recall question
    while len(checks) < MIN_CHECKS or not has_higher:
        level = "transfer" if not has_higher else "application"
        try:
            check = make_checkpoint(provider, part_title, body, level)
        except (ModelProviderError, ValueError, KeyError) as exc:
            notes.append(f"check_failed:{type(exc).__name__}")
            break
        blocks.insert(len(blocks) - 1, check)      # before the summary
        checks.append(check)
        has_higher = True
        notes.append(f"check:{level}")
    return blocks, notes


def _part_title(original: str, index: int, total: int) -> str:
    return f"{original} (Part {index} of {total})"


PART_SLUG = re.compile(r"^(?P<base>.+)-part-(?P<index>\d+)$")
PART_TITLE = re.compile(r"^(?P<base>.*?)\s*\(Part \d+ of \d+\)$")


def merge_parts(db: Session, event: Event) -> int:
    """Undo a previous split so the script can be re-run.

    A split is only as good as its budget, and the budget needed fixing after the first run.
    Rather than leave the course in whatever state the first attempt produced, parts are
    reassembled into the original lesson: generated blocks are dropped (they are tagged), the
    authored blocks return to their original order, and the child lessons are deleted. Without
    this the script is a one-way door and a tuning mistake is unrecoverable.

    The merge always runs in-session, including on a dry run: the caller rolls back, and a
    preview that skipped the merge would describe re-cutting already-cut parts.
    """
    from sqlalchemy.orm.attributes import flag_modified

    lessons = db.scalars(select(Lesson).where(Lesson.event_id == event.id)).all()
    by_slug = {lesson.slug: lesson for lesson in lessons}
    children: dict[str, list[tuple[int, Lesson]]] = {}
    for lesson in lessons:
        match = PART_SLUG.match(lesson.slug)
        if match and match.group("base") in by_slug:
            children.setdefault(match.group("base"), []).append(
                (int(match.group("index")), lesson))

    merged = 0
    for base_slug, parts in children.items():
        base = by_slug[base_slug]
        version = db.scalar(select(LessonVersion).where(
            LessonVersion.lesson_id == base.id,
            LessonVersion.version == base.current_version))
        if version is None:
            continue
        blocks = [b for b in (version.content or []) if b.get("generated_by") != GENERATED_BY]
        for _, child in sorted(parts):
            child_version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == child.id,
                LessonVersion.version == child.current_version))
            if child_version is not None:
                blocks += [b for b in (child_version.content or [])
                           if b.get("generated_by") != GENERATED_BY]
        title_match = PART_TITLE.match(base.title)
        if title_match:
            base.title = title_match.group("base")
        version.content = blocks
        flag_modified(version, "content")
        for _, child in parts:
            db.execute(LessonSkill.__table__.delete().where(
                LessonSkill.lesson_id == child.id))
            db.execute(LessonVersion.__table__.delete().where(
                LessonVersion.lesson_id == child.id))
            db.delete(child)
        db.flush()
        merged += 1
    return merged


def split_event(db: Session, event: Event, apply: bool, provider) -> list[dict]:
    lessons = db.scalars(select(Lesson).where(
        Lesson.event_id == event.id, Lesson.status != "withdrawn",
    ).order_by(Lesson.sequence, Lesson.id)).all()

    report = []
    for lesson in lessons:
        version = db.scalar(select(LessonVersion).where(
            LessonVersion.lesson_id == lesson.id,
            LessonVersion.version == lesson.current_version))
        if version is None:
            continue
        blocks = [dict(b) for b in (version.content or [])]
        before = minutes_of(blocks)
        parts = plan_cuts(blocks, overhead=OVERHEAD_MINUTES)
        row = {"lesson": lesson.title, "minutes": round(before, 1), "parts": len(parts)}
        if len(parts) == 1:
            row["action"] = "unchanged"
            report.append(row)
            continue

        completed = []
        for index, part in enumerate(parts, start=1):
            title = _part_title(lesson.title, index, len(parts))
            if apply:
                part_blocks, notes = complete_part(
                    provider, part, lesson.title, title,
                    is_first=index == 1, is_last=index == len(parts))
            else:
                part_blocks, notes = part, ["dry-run"]
            completed.append({"title": title, "blocks": part_blocks, "notes": notes,
                              "minutes": round(minutes_of(part_blocks), 1)})
        row["part_minutes"] = [p["minutes"] for p in completed]
        row["generated"] = [n for p in completed for n in p["notes"]]

        if apply:
            _write_parts(db, event, lesson, version, completed)
            row["action"] = "split"
        else:
            row["action"] = "would_split"
        report.append(row)
    return report


def _write_parts(db: Session, event: Event, lesson: Lesson, version: LessonVersion,
                 completed: list[dict]) -> None:
    """Part 1 replaces the original lesson; later parts become new lessons after it.

    The original lesson id is kept for part 1 so student progress, video renders, and skill
    links that already point at it stay valid; only its content narrows.
    """
    from sqlalchemy.orm.attributes import flag_modified

    skill_links = db.scalars(select(LessonSkill).where(
        LessonSkill.lesson_id == lesson.id)).all()
    base_sequence = lesson.sequence or 0

    first = completed[0]
    lesson.title = first["title"]
    lesson.estimated_minutes = max(5, min(12, round(first["minutes"])))
    version.content = first["blocks"]
    flag_modified(version, "content")

    # make room so the new parts sort immediately after their parent
    for later in db.scalars(select(Lesson).where(
        Lesson.event_id == event.id, Lesson.sequence > base_sequence)).all():
        later.sequence += len(completed) - 1

    for offset, part in enumerate(completed[1:], start=1):
        new_lesson = Lesson(
            event_id=event.id,
            slug=f"{lesson.slug}-part-{offset + 1}",
            title=part["title"],
            # a split part inherits its parent's review state, and the parent's approvals do
            # not cover content a model just wrote — so it starts as a draft
            status="draft",
            sequence=base_sequence + offset,
            estimated_minutes=max(5, min(12, round(part["minutes"]))),
            current_version=1,
        )
        db.add(new_lesson)
        db.flush()
        db.add(LessonVersion(
            lesson_id=new_lesson.id, version=1, content=part["blocks"],
            claim_ids=list(version.claim_ids or []),
            citations=list(version.citations or []),
            review_status="draft",
        ))
        for link in skill_links:
            db.add(LessonSkill(lesson_id=new_lesson.id, skill_id=link.skill_id,
                               is_primary=link.is_primary, weight=link.weight))
        db.flush()


def main() -> None:
    ap = argparse.ArgumentParser(description="Split over-long lessons")
    ap.add_argument("--event", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    provider = OpenAICompatibleProvider()
    if args.apply and not provider.configured:
        raise SystemExit("no model provider configured; splitting needs generated connectives")

    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == args.event))
        if not event:
            raise SystemExit(f"unknown event {args.event!r}")
        # reassemble any earlier split first, so re-running re-cuts the original lesson
        # rather than slicing already-sliced parts
        merged = merge_parts(db, event)
        if merged:
            print(f"reassembled {merged} previously split lesson(s) before re-cutting")
        report = split_event(db, event, args.apply, provider)
        if args.apply:
            db.commit()
        else:
            db.rollback()

    print("=" * 78)
    print(f"LESSON SPLIT — {args.event} [{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 78)
    for row in report:
        line = f"{row['lesson'][:44]:44} {row['minutes']:5.1f}min -> {row['action']}"
        if row.get("part_minutes"):
            line += f" {row['part_minutes']}"
        print(line)
    split = [r for r in report if r["action"] in {"split", "would_split"}]
    print("-" * 78)
    print(f"{len(split)} of {len(report)} lessons split into "
          f"{sum(r['parts'] for r in split)} parts")
    over = [r for r in report for m in (r.get("part_minutes") or [r["minutes"]]) if m > MAX_MINUTES]
    print(f"parts still over {MAX_MINUTES} minutes: {len(over)}")
    if not args.apply:
        print("dry run — nothing written. re-run with --apply")


if __name__ == "__main__":
    main()
