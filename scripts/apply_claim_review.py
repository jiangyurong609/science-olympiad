"""Apply a reviewer's verdicts on grounding claims, and drop the items that lose their evidence.

A claim is approved because someone judged the sentence fit to teach from. This records that
judgement, and then does the part that is easy to skip: an exam item whose only claim was
REJECTED has no evidence any more, so it comes out of the paper. Leaving it in would mean the
review changed a database field and nothing a student sees.

Three reviewers judged 276 claims behind 340 items across seven subjects and rejected 52. The
rejections were not stylistic. Among them: a combined gas law whose fraction bars extraction
had deleted, backing an item that computes 3 where the law gives 12; "greywackes and other
volcanic rocks", filing a clastic sandstone as volcanic in the event about rock classification;
a definition of catchment area taken from a bottled-water policy that contradicts the drainage
basin definition taught elsewhere in the same event; and one sentence keyed to "Travertine" on
one item and "Tufa" on another.

`factual_grounding` is written here only where the linked claims are in fact approved, which is
the same condition `app.services.validation.validate_question` computes. It is recorded, never
assumed.

    DATABASE_URL=... python -m scripts.apply_claim_review --verdicts verdicts.json
    DATABASE_URL=... python -m scripts.apply_claim_review --verdicts verdicts.json --apply
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Exam, ExamItem, Question, ScientificClaim

MACHINE = "machine_practice"


def apply_verdicts(db, approve: set[int], reject: set[int], apply: bool) -> dict:
    stats: Counter[str] = Counter()
    for claim_id in sorted(approve | reject):
        claim = db.get(ScientificClaim, claim_id)
        if claim is None:
            stats["claim_missing"] += 1
            continue
        wanted = claim_id in approve
        if claim.approved != wanted:
            stats["approved" if wanted else "unapproved"] += 1
            if apply:
                claim.approved = wanted
        else:
            stats["already_correct"] += 1
    if apply:
        db.flush()

    dropped_by_exam: dict[int, list[int]] = {}
    for exam in db.scalars(select(Exam).where(Exam.release_class == MACHINE)):
        items = db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id)
                           .order_by(ExamItem.position)).all()
        keep, drop = [], []
        for item in items:
            question = db.get(Question, item.question_id)
            report = dict((question.validation_report or {}) if question else {})
            claim_ids = report.get("claim_ids") or []
            claims = [db.get(ScientificClaim, c) for c in claim_ids]
            # In a dry run the approvals above were not written, so `claim.approved` still
            # reads the old value and every item would look unsupported. Judge against the
            # verdicts themselves, which is what the state WILL be, or the preview reports
            # the opposite of what applying does — it claimed 394 items would be dropped
            # when the real answer is 52 claims' worth.
            def is_ok(claim: ScientificClaim | None) -> bool:
                if claim is None:
                    return False
                if claim.id in approve:
                    return True
                if claim.id in reject:
                    return False
                return bool(claim.approved)
            ok = bool(claims) and all(is_ok(c) for c in claims)
            if ok:
                if report.get("factual_grounding") != "approved_claims":
                    stats["grounding_recorded"] += 1
                    if apply and question is not None:
                        report["factual_grounding"] = "approved_claims"
                        question.validation_report = report
                keep.append(item)
            else:
                drop.append(item)
        if not drop:
            continue
        dropped_by_exam[exam.id] = [i.question_id for i in drop]
        stats["items_dropped"] += len(drop)
        if apply:
            for item in drop:
                db.delete(item)
            db.flush()
            # Positions must stay contiguous: the runner serves items in position order and a
            # gap is a question a student never reaches. Renumber in TWO phases — there is a
            # unique constraint on (exam_id, position), and assigning 0..n-1 directly collides
            # with the rows still holding those positions partway through the UPDATE.
            for offset, item in enumerate(keep):
                item.position = 100_000 + offset
            db.flush()
            for position, item in enumerate(keep):
                item.position = position
            db.flush()
            exam.question_ids = [i.question_id for i in keep]
    if apply:
        db.commit()
    return {**stats, "exams_touched": len(dropped_by_exam)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verdicts", required=True,
                        help='JSON: {"approve": [...], "reject": [...]}')
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    data = json.loads(open(args.verdicts).read())
    approve, reject = set(data["approve"]), set(data["reject"])
    overlap = approve & reject
    if overlap:
        raise SystemExit(f"a claim cannot be both approved and rejected: {sorted(overlap)}")
    print(f"verdicts: {len(approve)} approve, {len(reject)} reject")
    with SessionLocal() as db:
        print(json.dumps(apply_verdicts(db, approve, reject, args.apply), indent=2))


if __name__ == "__main__":
    main()
