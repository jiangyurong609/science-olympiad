"""Fix the specific error a reviewer named, then make the lesson earn its way back.

The automated reviewer withholds a lesson on a concrete finding — "places the basal ganglia in
the cerebral cortex", "treats blood glucose regulation as a hindbrain function". Those are
precise enough to repair mechanically, and repairing them is far better than leaving 75 lessons
dark.

Three rules keep this from becoming a way of laundering a rejection into an approval:

  * **the repair is narrow.** The corrector is given the finding and told to fix that and
    nothing else. A rewrite that "improves" the lesson would need reviewing as new content,
    and would quietly discard whatever a human had already decided about the rest of it.
  * **the repair makes a new version.** Rejection is scoped to the version reviewed, so a fix
    must produce a new one — otherwise the verdict either wrongly persists or is wrongly
    dropped. The prior version stays intact and readable.
  * **the repair re-earns visibility, and fail-closed.** The new version is reviewed again from
    scratch. Only a fresh `approve` restores the lesson; `revise` or `reject` leaves it dark.
    A repair that is not re-reviewed — because the model failed, the run died, anything —
    leaves the lesson withheld. Nothing here can make a lesson visible without a verdict on the
    text that would actually be served.

    PYTHONPATH=. python -m scripts.repair_rejected_lessons
    DATABASE_URL=<prod> PYTHONPATH=. python -m scripts.repair_rejected_lessons --apply
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, LessonVersion, ReviewDecision
from app.services import lesson_blocks
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider
from scripts.agentic_course_review import STAGE, _reviewer_account, _score_checkpoints, review_lesson

SYSTEM = (
    "You repair one specific defect in a Science Olympiad lesson. Return ONLY valid JSON as "
    '{"blocks": [ ... the full block list, in order ... ], "changed": [int], '
    '"what_changed": str}.\n\n'
    "You are given the lesson's blocks and a reviewer's finding. Correct ONLY what the finding "
    "identifies. Do not reword unaffected text, do not add or remove blocks, do not change any "
    "answer key unless the finding says the key is wrong, and do not introduce a fact the "
    "lesson did not already rely on. Return every block, including the untouched ones, exactly "
    "as given. `changed` lists the indexes you edited."
)


def repair(provider, lesson: Lesson, blocks: list[dict], finding: str) -> dict | None:
    payload = provider.generate_json(SYSTEM, json.dumps({
        "lesson_title": lesson.title,
        "reviewer_finding": finding,
        "blocks": blocks,
    })).payload
    if isinstance(payload, str):
        payload = json.loads(payload)
    repaired = payload.get("blocks")
    if not isinstance(repaired, list) or len(repaired) != len(blocks):
        return None                     # a repair that changes the shape is a rewrite
    for old, new in zip(blocks, repaired):
        if old.get("type") != (new or {}).get("type"):
            return None
    return {"blocks": repaired, "changed": payload.get("changed") or [],
            "what_changed": str(payload.get("what_changed") or "")[:500]}


def run(apply: bool, limit: int | None = None) -> dict:
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise SystemExit("no model provider configured")

    stats: Counter[str] = Counter()
    rows: list[dict] = []
    with SessionLocal() as db:
        events = {e.id: e for e in db.scalars(select(Event)).all()}
        reviewer = _reviewer_account(db) if apply else None
        rejects = db.scalars(select(ReviewDecision).where(
            ReviewDecision.entity_type == "lesson", ReviewDecision.stage == STAGE,
            ReviewDecision.decision == "reject")).all()
        if limit:
            rejects = rejects[:limit]

        for decision in rejects:
            lesson = db.get(Lesson, decision.entity_id)
            if lesson is None or decision.entity_version != lesson.current_version:
                stats["stale_verdict"] += 1        # already repaired or superseded
                continue
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version))
            if version is None:
                continue
            finding = (decision.notes or "").strip()
            if not finding:
                stats["no_finding_to_act_on"] += 1
                continue
            stats["examined"] += 1
            if not apply:
                rows.append({"lesson": lesson.title, "outcome": "would repair",
                             "detail": finding[:60]})
                continue

            blocks = copy.deepcopy(list(version.content or []))
            try:
                fixed = repair(provider, lesson, blocks, finding)
            except (ModelProviderError, ValueError, KeyError) as exc:
                stats[f"repair_failed:{type(exc).__name__}"] += 1
                continue
            if fixed is None:
                stats["refused_shape_changed"] += 1
                rows.append({"lesson": lesson.title, "outcome": "refused",
                             "detail": "repair altered the lesson's shape"})
                continue
            if not fixed["changed"]:
                stats["nothing_changed"] += 1
                continue

            new_version = version.version + 1
            db.add(LessonVersion(
                lesson_id=lesson.id, version=new_version,
                review_status="draft", claim_ids=version.claim_ids,
                citations=version.citations, content=fixed["blocks"]))
            lesson.current_version = new_version
            db.flush()

            reloaded = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id, LessonVersion.version == new_version))
            try:
                payload = review_lesson(provider, events.get(lesson.event_id), lesson, reloaded)
            except (ModelProviderError, ValueError, KeyError) as exc:
                # unreviewed is not repaired: the lesson stays dark on the new version too
                stats[f"rereview_failed:{type(exc).__name__}"] += 1
                db.commit()
                continue
            checks = _score_checkpoints(payload, reloaded)
            verdict = payload["verdict"]
            if checks["mismatched"] and verdict == "approve":
                verdict = "revise"
            db.add(ReviewDecision(
                entity_type="lesson", entity_id=lesson.id, entity_version=new_version,
                stage=STAGE, decision=verdict, reviewer_user_id=reviewer.id,
                checklist={"repaired_from": version.version, "checkpoints": checks},
                notes=str(payload.get("summary") or "")[:2000]))

            if verdict == "approve" and lesson.disposition == "unreviewed_practice":
                # The practice exemption was granted for text that has changed, so it is
                # re-granted only against a fresh approval of the text now being served.
                lesson.disposition_version = new_version
                stats["restored"] += 1
            else:
                stats[f"repaired_but_{verdict}"] += 1
            db.commit()
            rows.append({"lesson": lesson.title,
                         "outcome": f"v{new_version}: {verdict}",
                         "detail": fixed["what_changed"][:56]})
    return {"stats": stats, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Repair lessons the reviewer rejected")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    result = run(args.apply, args.limit)
    print("=" * 90)
    print(f"LESSON REPAIR [{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 90)
    for row in result["rows"][:25]:
        print(f"  {row['lesson'][:34]:36} {row['outcome'][:18]:20} {row['detail']}")
    print("-" * 90)
    for key, value in sorted(result["stats"].items()):
        print(f"  {key:28} {value}")
    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")
    else:
        print("\nonly a fresh approval restores a lesson; anything else leaves it withheld")
    print("=" * 90)


if __name__ == "__main__":
    main()
