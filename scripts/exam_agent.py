"""An agent that writes competition-format practice items and refuses to trust itself.

Everything here was learned by shipping the mistake first, in this order:

  1. A generic pile of multiple choice is not a tournament paper. Section structure comes from
     real papers — True/False worth a point, matching columns, multiple choice, data
     interpretation, a scenario tie-breaker — because a student drilled only on four-option
     recall meets that shape for the first time at the tournament.
  2. Asking for eight items in one call truncates the reply and the last items come back
     missing fields, so a whole section can silently vanish. Batches stay small.
  3. Unsteered, a 32-item paper covered four of thirteen topics. The syllabus is written down;
     the generator walks it in slices and retries a slice that yields nothing, because losing
     one batch to validation must not cost a topic.
  4. A structural validator cannot tell you the key is wrong. A blind solver and an independent
     verifier can, and between them they caught a real physics error (groundwater flows down
     the hydraulic gradient, not pressure), a question with two correct answers, and a Strahler
     key that was not universally right.
  5. ONE verification pass is not enough. Nine passes over the same two papers never converged:
     passes four and five came back clean and pass six found two more defects. So every item is
     checked `--rounds` times independently and must clear EVERY round. A single dissent is a
     rejection, because the cost of a wrong key reaching a student is not symmetric with the
     cost of discarding a good question.

What the agent will not do: mark its own work reviewed, publish anything, or write
`factual_grounding: approved_claims`. It ends by handing a human a review packet, because
repeated stochastic checking lowers an error rate and cannot drive it to zero.

Usage:
  python -m scripts.exam_agent --event dynamic-planet-b-2027 --format invitational \\
      --target 30 --rounds 3 [--apply]
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import AuditLog, Event, Exam, ExamItem, Question
from app.services import student_visibility as sv
from app.services.model_provider import OpenAICompatibleProvider
from scripts.build_season_exam import FORMATS, build
from scripts.verify_exam_items import _check


def _verify_rounds(provider, snapshots: dict[int, dict], rounds: int,
                   workers: int) -> tuple[set[int], dict[int, list[str]]]:
    """Check every item `rounds` times. An item survives only if every round clears it.

    Unanimity, not majority: a verifier that objects once has found something, and the paper is
    cheap to top up while a wrong key in front of a student is not.
    """
    survivors = set(snapshots)
    reasons: dict[int, list[str]] = {}
    for round_number in range(1, rounds + 1):
        if not survivors:
            break
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_check, provider, item_id, snapshots[item_id]): item_id
                       for item_id in sorted(survivors)}
            failed = []
            for future in as_completed(futures):
                row = future.result()
                if row["ok"]:
                    continue
                item_id = row["item_id"]
                why = row.get("error") or row.get("solver", {}).get("verdict", "failed")
                errors = row.get("verifier", {}).get("errors") or []
                if errors:
                    why = f"{why}; {errors[0][:110]}"
                reasons.setdefault(item_id, []).append(f"round {round_number}: {why}")
                failed.append(item_id)
        survivors -= set(failed)
        print(f"   round {round_number}: {len(survivors)} still clean, "
              f"{len(failed)} rejected this round", flush=True)
    return survivors, reasons


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True)
    ap.add_argument("--format", default="invitational", choices=sorted(FORMATS))
    ap.add_argument("--target", type=int, default=30,
                    help="how many fully verified items the paper should end with")
    ap.add_argument("--rounds", type=int, default=3,
                    help="independent verification rounds each item must clear")
    ap.add_argument("--attempts", type=int, default=3,
                    help="generate-and-verify cycles before giving up")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    event = db.scalar(select(Event).where(Event.slug == args.event))
    if not event:
        raise SystemExit(f"unknown event {args.event!r}")
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise SystemExit("model provider is not configured")

    print(f"agent: {event.name} · {args.format} · target {args.target} verified items · "
          f"{args.rounds} independent rounds each\n")

    kept: list[dict] = []
    rejected: list[dict] = []
    for attempt in range(1, args.attempts + 1):
        if len(kept) >= args.target:
            break
        print(f"— cycle {attempt} — writing a paper", flush=True)
        report = build(args.event, args.format, apply=args.apply)
        exam_id = report.get("exam_id")
        if not exam_id:
            print("   nothing written (dry run); stopping"); break
        items = db.scalars(select(ExamItem).where(ExamItem.exam_id == exam_id)).all()
        snapshots = {i.id: {**i.snapshot, "position": i.position} for i in items}
        print(f"   {len(items)} items written; verifying", flush=True)
        survivors, reasons = _verify_rounds(provider, snapshots, args.rounds, args.workers)

        exam = db.get(Exam, exam_id)
        for item in items:
            question = db.get(Question, item.question_id)
            record = {"exam_id": exam_id, "stem": item.snapshot["stem"][:120],
                      "section": item.snapshot.get("section")}
            if item.id in survivors:
                report_json = dict(question.validation_report or {})
                report_json.update(passed=True, structural_checks="passed",
                                   verification_rounds=args.rounds)
                report_json["errors"] = [e for e in report_json.get("errors", [])
                                         if e != "unreviewed_machine_authored"]
                question.validation_report = report_json
                question.status = "machine_validated"
                kept.append(record)
            else:
                record["reasons"] = reasons.get(item.id, ["rejected"])
                rejected.append(record)
                question.status = "draft"
                db.delete(item)
        db.flush()

        remaining = db.scalars(select(ExamItem).where(ExamItem.exam_id == exam_id)
                               .order_by(ExamItem.position)).all()
        for offset, row in enumerate(remaining):      # two-phase: uq_exam_item_position
            row.position = 10_000 + offset
        db.flush()
        for offset, row in enumerate(remaining):
            row.position = offset
        exam.question_ids = [row.question_id for row in remaining]
        blueprint = dict(exam.blueprint or {})
        blueprint.update(question_count=len(remaining),
                         verification_rounds=args.rounds,
                         gates_outstanding=["grounding_in_approved_claims", "human_review"])
        exam.blueprint = blueprint
        exam.published = False
        db.add(AuditLog(
            actor_user_id=None, action="exam.agent_cycle",
            entity_type="exam", entity_id=str(exam_id),
            details={"cycle": attempt, "written": len(items), "kept": len(remaining),
                     "rejected": len(items) - len(remaining), "rounds": args.rounds,
                     "note": "every kept item cleared every round; this is not human review"}))
        db.commit()
        print(f"   cycle {attempt}: kept {len(remaining)} of {len(items)}", flush=True)

    print(f"\n{len(kept)} verified items · {len(rejected)} rejected")
    if rejected:
        print("\nwhy items were rejected (the agent's own output, discarded):")
        for row in rejected[:12]:
            print(f"   [{(row['section'] or '')[:20]:20}] {row['reasons'][0][:104]}")
            print(f"      {row['stem'][:96]}")

    out = Path(f"review-packet-{args.event}-{args.format}.json")
    out.write_text(json.dumps({"event": args.event, "format": args.format,
                               "verified": kept, "rejected": rejected,
                               "rounds": args.rounds}, indent=1))
    print(f"\nreview packet: {out}")
    print("Nothing was published. Every item still needs a human read before it is served as "
          "reviewed content; repeated checking lowers the error rate, it does not zero it.")


if __name__ == "__main__":
    main()
