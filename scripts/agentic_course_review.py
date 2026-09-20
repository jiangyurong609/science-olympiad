"""Walk a lesson the way a student does, and record an honest verdict.

Human review is the constraint on this catalog and there are 474 lessons. This reviews them
automatically — but it is not a way of getting a human's signature without a human. The
decision it writes is recorded at stage `automated`, attributed to a dedicated reviewer
account, and it does **not** satisfy `lesson_is_student_visible`, which still wants editor and
SME. What it does is find the content that should not be served at all, and mark what a human
should look at first.

The reviewer is shown the lesson as the reader presents it — blocks in order, checkpoints with
their choices, the answer key withheld until it has committed — and asked the questions a
student's experience actually turns on:

  * **teaches** — does the reading before a checkpoint contain what the checkpoint tests?
    The commonest defect in generated courses is a question about material the lesson never
    presented, which reads fine in isolation and is unanswerable in place.
  * **coherent** — do the blocks follow, or is it eight paragraphs that could be shuffled?
  * **correct** — anything factually wrong, in the reading or in a key.
  * **on topic** — is this the subject the event says it is.
  * **answerable** — the reviewer answers each checkpoint from the lesson alone, before seeing
    the key. A checkpoint it cannot answer from the lesson is the finding, not the reviewer's
    failure.

**A gate that never fails is not a gate.** The hint checker in this codebase reported a 0.1%
refusal rate and a direct measurement found the true rate was 42% — it had been measuring
something that stopped varying. So this records its verdict distribution every run, and
`--calibrate` feeds it deliberately broken lessons to confirm it still rejects them. If the
approval rate approaches 100%, distrust it before trusting the content.

    PYTHONPATH=. python -m scripts.agentic_course_review --event rocks-and-minerals-b
    DATABASE_URL=<prod> PYTHONPATH=. python -m scripts.agentic_course_review --all --apply
    PYTHONPATH=. python -m scripts.agentic_course_review --calibrate
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Event, Lesson, LessonVersion, ReviewDecision, User,
)
from app.services import lesson_blocks
from app.services.course_quality import block_text
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

REVIEWER_EMAIL = "automated-reviewer@fieldstone.invalid"
REVIEWER_NAME = "Automated reviewer"
STAGE = "automated"

SYSTEM = (
    "You are reviewing one lesson of a Science Olympiad study course, as an attentive student "
    "would experience it: you read the blocks in order and answer each knowledge check from "
    "the lesson alone. You have NOT been given the answer key.\n\n"
    "Return ONLY valid JSON:\n"
    '{"verdict": "approve"|"revise"|"reject", "teaches": bool, "coherent": bool, '
    '"on_topic": bool, "factual_errors": [str], "unanswerable_checkpoints": [str], '
    '"checkpoint_answers": [{"heading": str, "chosen_index": int, "from_lesson": bool}], '
    '"summary": str}\n\n'
    "Judge strictly and specifically.\n"
    "- reject: teaches the wrong subject, contains a clear factual error, or asks about "
    "material the lesson never presents.\n"
    "- revise: usable but with a real defect a student would notice — an unexplained term, a "
    "check that needs outside knowledge, incoherent ordering.\n"
    "- approve: a student could learn the stated topic from this and answer its checks.\n"
    "Approving weak material is a worse error than flagging good material."
)


def lesson_as_a_student_sees_it(version: LessonVersion) -> list[dict]:
    """The reader's view: no answer key, no authoring metadata."""
    out = []
    for index, block in enumerate(version.content or []):
        safe = lesson_blocks.student_safe(block, index)
        entry = {"type": safe.get("type"), "heading": safe.get("heading") or ""}
        if safe.get("type") == lesson_blocks.CHECKPOINT:
            entry["question"] = safe.get("question")
            entry["choices"] = [str(c) for c in safe.get("choices") or []]
        else:
            entry["text"] = block_text(block)[:2500]
        out.append(entry)
    return out


def review_lesson(provider, event: Event, lesson: Lesson, version: LessonVersion) -> dict:
    payload = provider.generate_json(SYSTEM, json.dumps({
        "event": f"{event.name} (Division {event.division or '?'})",
        "lesson_title": lesson.title,
        "lesson_summary": lesson.summary or "",
        "blocks": lesson_as_a_student_sees_it(version),
    })).payload
    if isinstance(payload, str):
        payload = json.loads(payload)
    verdict = str(payload.get("verdict") or "").lower()
    if verdict not in {"approve", "revise", "reject"}:
        verdict = "revise"                 # an unreadable verdict is not an approval
    payload["verdict"] = verdict
    return payload


def _score_checkpoints(payload: dict, version: LessonVersion) -> dict:
    """Did the reviewer, answering from the lesson alone, reproduce each key?

    This is the part that cannot be talked around: a checkpoint the reviewer answers wrongly
    from the lesson is either mis-keyed or untaught, and both are defects.
    """
    keys = [lesson_blocks.checkpoint_answer_index(b)
            for b in (version.content or []) if b.get("type") == lesson_blocks.CHECKPOINT]
    answers = payload.get("checkpoint_answers") or []
    agreed = mismatched = 0
    for index, answer in enumerate(answers):
        if index >= len(keys) or keys[index] is None:
            continue
        if answer.get("chosen_index") == keys[index]:
            agreed += 1
        else:
            mismatched += 1
    return {"agreed": agreed, "mismatched": mismatched, "keys": len(keys)}


def _reviewer_account(db) -> User:
    user = db.scalar(select(User).where(User.email == REVIEWER_EMAIL))
    if user is None:
        # a distinct identity, so nothing here is ever mistaken for a person's decision
        user = User(email=REVIEWER_EMAIL, full_name=REVIEWER_NAME, role="editor")
        db.add(user)
        db.flush()
    return user


def run(event_slug: str | None, apply: bool, limit: int | None = None,
        include_drafts: bool = False) -> dict:
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise SystemExit("no model provider configured; cannot review")

    stats: Counter[str] = Counter()
    rows: list[dict] = []
    with SessionLocal() as db:
        reviewer = _reviewer_account(db) if apply else None
        # Reviewing only what is already published was right when every lesson in the catalog
        # was live and the job was finding what should never have been served. It is backwards
        # for a course being built: a draft is precisely the thing that wants reading BEFORE a
        # student sees it. A 26-lesson subject authored this morning was skipped entirely, and
        # the run reported "already_reviewed: 1" and looked like it had done its job.
        statuses = ["published", "draft"] if include_drafts else ["published"]
        query = select(Lesson).where(Lesson.status.in_(statuses))
        if event_slug:
            event = db.scalar(select(Event).where(Event.slug == event_slug))
            if not event:
                raise SystemExit(f"unknown event {event_slug!r}")
            query = query.where(Lesson.event_id == event.id)
        lessons = db.scalars(query.order_by(Lesson.id)).all()
        if limit:
            lessons = lessons[:limit]
        events = {e.id: e for e in db.scalars(select(Event)).all()}

        for lesson in lessons:
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version))
            if version is None:
                continue
            already = db.scalar(select(ReviewDecision).where(
                ReviewDecision.entity_type == "lesson", ReviewDecision.entity_id == lesson.id,
                ReviewDecision.entity_version == version.version,
                ReviewDecision.stage == STAGE))
            if already is not None:
                stats["already_reviewed"] += 1
                continue

            event = events.get(lesson.event_id)
            try:
                payload = review_lesson(provider, event, lesson, version)
            except (ModelProviderError, ValueError, KeyError) as exc:
                stats[f"failed:{type(exc).__name__}"] += 1
                continue

            checks = _score_checkpoints(payload, version)
            verdict = payload["verdict"]
            # The reviewer's own prose verdict does not override what it demonstrably could
            # not do: if it could not answer the lesson's own checkpoints from the lesson,
            # that is a defect regardless of how it summarised the lesson.
            if checks["mismatched"] and verdict == "approve":
                verdict = "revise"
                payload["summary"] = (f"[downgraded] could not reproduce "
                                      f"{checks['mismatched']} key(s) from the lesson. "
                                      + str(payload.get("summary") or ""))[:900]
            stats[verdict] += 1
            stats["checkpoint_keys_missed"] += checks["mismatched"]
            rows.append({
                "event": event.slug if event else "?", "lesson": lesson.title,
                "verdict": verdict,
                "why": (payload.get("factual_errors") or
                        payload.get("unanswerable_checkpoints") or
                        [payload.get("summary", "")])[0] if verdict != "approve" else "",
            })

            if apply:
                db.add(ReviewDecision(
                    entity_type="lesson", entity_id=lesson.id,
                    entity_version=version.version, stage=STAGE, decision=verdict,
                    reviewer_user_id=reviewer.id,
                    checklist={"teaches": payload.get("teaches"),
                               "coherent": payload.get("coherent"),
                               "on_topic": payload.get("on_topic"),
                               "checkpoints": checks},
                    notes=str(payload.get("summary") or "")[:2000],
                ))
                db.commit()
    return {"stats": stats, "rows": rows}


CALIBRATION = [
    ("wrong subject", "Photosynthesis in C4 Plants",
     "Plants fix carbon using PEP carboxylase in mesophyll cells.", "approve_is_wrong"),
    ("factual error", "Mohs Hardness",
     "Talc is the hardest mineral on the Mohs scale, rated 10, and scratches diamond.",
     "approve_is_wrong"),
]


def calibrate() -> None:
    """Feed the reviewer material it must reject, and report whether it did."""
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise SystemExit("no model provider configured")
    print("=" * 78)
    print("CALIBRATION — the reviewer must reject these")
    print("=" * 78)
    caught = 0
    for label, title, text, _ in CALIBRATION:
        payload = provider.generate_json(SYSTEM, json.dumps({
            "event": "Rocks and Minerals (Division B)",
            "lesson_title": title, "lesson_summary": "",
            "blocks": [{"type": "opening", "heading": title, "text": text},
                       {"type": "checkpoint", "heading": "Check",
                        "question": "Which statement is correct?",
                        "choices": ["The statement above", "Something else"]}],
        })).payload
        if isinstance(payload, str):
            payload = json.loads(payload)
        verdict = str(payload.get("verdict") or "?")
        ok = verdict in {"reject", "revise"}
        caught += ok
        print(f"  [{'caught' if ok else 'MISSED'}] {label:16} -> {verdict}: "
              f"{str(payload.get('summary'))[:60]}")
    print("-" * 78)
    print(f"  {caught}/{len(CALIBRATION)} rejected. A reviewer that approves these is inert.")
    print("=" * 78)


def main() -> None:
    ap = argparse.ArgumentParser(description="Review lessons as a student would")
    ap.add_argument("--event", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--include-drafts", action="store_true",
                    help="also review unpublished drafts, which is what a course being built "
                         "consists of")
    args = ap.parse_args()

    if args.calibrate:
        calibrate()
        return
    if not args.event and not args.all:
        raise SystemExit("pass --event <slug> or --all")

    result = run(args.event, args.apply, args.limit, args.include_drafts)
    stats = result["stats"]
    print("=" * 92)
    print(f"AGENTIC COURSE REVIEW [{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 92)
    for row in result["rows"][:30]:
        if row["verdict"] != "approve":
            print(f"  {row['verdict']:8} {row['event'][:22]:24} {row['lesson'][:30]:32} "
                  f"{str(row['why'])[:34]}")
    print("-" * 92)
    total = sum(stats[v] for v in ("approve", "revise", "reject"))
    for key, value in sorted(stats.items()):
        print(f"  {key:26} {value}")
    if total:
        rate = 100 * stats["approve"] / total
        print(f"\n  approval rate {rate:.0f}%")
        if rate > 95:
            print("  WARNING: near-total approval is what an inert gate looks like. "
                  "Run --calibrate before trusting this.")
    if not args.apply:
        print("\ndry run — no decisions recorded. re-run with --apply")
    else:
        print(f"\ndecisions recorded at stage '{STAGE}' by {REVIEWER_NAME}; these do NOT "
              f"make a lesson student-visible on their own")
    print("=" * 92)


if __name__ == "__main__":
    main()
