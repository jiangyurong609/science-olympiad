"""Hunt for wrong keys and bad questions in an authored exam, before a student meets one.

A structural validator says an item is well-formed. It cannot say the key is right. These two
passes can, and they disagree with the author often enough to be worth running:

  * an INDEPENDENT BLIND SOLVER answers the item from the stem and choices alone, never seeing
    the intended key. If it picks a different choice, either the key is wrong or the item is
    ambiguous — both are defects, and both reach a student as a question they cannot get right.
  * an INDEPENDENT VERIFIER reads the item WITH its key and explanation and looks for factual
    errors, a second defensible answer, an explanation that contradicts the key, and whether
    the level suits the division.

Neither pass makes machine-written content correct, and passing both is not review. It is the
difference between "nothing checked this" and "two independent passes checked this and found
nothing", which is the bar `student_visibility.item_clears_every_gate` sets for serving an item
as labelled machine practice at all.

Items that fail are quarantined out of the exam rather than silently left in it.

Usage: --exam <id> [--apply] [--workers N]
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.models.entities import AuditLog, Exam, ExamItem, Question
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

SOLVER_SYSTEM = (
    "You are an INDEPENDENT solver. You receive ONLY a question stem and its answer choices — "
    "never the intended answer or any explanation. Solve it yourself from first principles. "
    'Return strict JSON: {"chosen_index": int, "confidence": number 0..1, '
    '"ambiguous": boolean, "insufficient": boolean}. Set "ambiguous" if more than one choice is '
    'defensibly correct; set "insufficient" if the stem lacks the information needed to answer.'
)

SHORT_ANSWER_SOLVER_SYSTEM = (
    "You are an INDEPENDENT solver. You receive ONLY a question stem — never the intended "
    'answer. Answer it in one or two words. Return strict JSON: {"answer": str, '
    '"ambiguous": boolean, "insufficient": boolean}.'
)

VERIFIER_SYSTEM = (
    "You are an independent Science Olympiad assessment verifier reviewing ONE item for a "
    "Division B student (grades 6-9). Check, independently: (1) is every factual statement in "
    "the stem, the key and the explanation correct; (2) is the keyed answer the single best "
    "answer, with no second defensible choice; (3) does the explanation actually justify the "
    "key rather than contradict it; (4) is the item answerable without material the student "
    "cannot see; (5) is it appropriate for the division. "
    'Return strict JSON: {"passed": boolean, "errors": [str], "warnings": [str]}. '
    "Put anything that would make a student's correct reasoning score wrong in `errors`. "
    "Be specific and terse. An item with no problems has an empty errors list."
)


def _solve(provider, snapshot: dict) -> tuple[bool, str, dict]:
    """Blind-solve, and say whether the solver reproduces the key."""
    stem = snapshot["stem"]
    if snapshot["question_type"] == "short_answer":
        payload = provider.generate_json(
            SHORT_ANSWER_SOLVER_SYSTEM, json.dumps({"stem": stem})).payload
        if payload.get("insufficient"):
            return False, "solver_insufficient_information", payload
        if payload.get("ambiguous"):
            return False, "solver_reports_ambiguous", payload
        spec = snapshot["answer_spec"]
        accepted = {str(spec.get("answer", "")).strip().casefold()}
        accepted |= {str(a).strip().casefold() for a in (spec.get("accepted") or [])}
        got = str(payload.get("answer", "")).strip().casefold()
        # A short answer the solver reaches by a different wording is still the same answer;
        # substring either way catches "divide" against "drainage divide".
        ok = any(got == a or (len(a) > 3 and (a in got or got in a)) for a in accepted if a)
        return ok, "solver_agrees" if ok else "solver_disagrees_with_key", payload

    payload = provider.generate_json(
        SOLVER_SYSTEM, json.dumps({"stem": stem, "choices": snapshot["choices"]})).payload
    if payload.get("insufficient"):
        return False, "solver_insufficient_information", payload
    if payload.get("ambiguous"):
        return False, "solver_reports_ambiguous", payload
    chosen = payload.get("chosen_index")
    key = snapshot["answer_spec"].get("correct_index")
    if not isinstance(chosen, int):
        return False, "solver_returned_no_choice", payload
    return (chosen == key,
            "solver_agrees" if chosen == key else "solver_disagrees_with_key", payload)


def _verify(provider, snapshot: dict) -> dict:
    spec = snapshot["answer_spec"]
    key = (snapshot["choices"][spec["correct_index"]]
           if snapshot.get("choices") else spec.get("answer"))
    return provider.generate_json(VERIFIER_SYSTEM, json.dumps({
        "stem": snapshot["stem"],
        "choices": snapshot.get("choices") or None,
        "keyed_answer": key,
        "explanation": snapshot.get("explanation", ""),
        "division": "B",
    }, ensure_ascii=False)).payload


def _check(provider, item_id: int, snapshot: dict) -> dict:
    out = {"item_id": item_id, "position": snapshot.get("position"),
           "section": snapshot.get("section"), "stem": snapshot["stem"][:110]}
    try:
        ok, reason, payload = _solve(provider, snapshot)
        out["solver"] = {**payload, "verdict": reason, "passed": ok}
        verifier = _verify(provider, snapshot)
        errors = [str(e) for e in (verifier.get("errors") or []) if str(e).strip()]
        out["verifier"] = {"passed": bool(verifier.get("passed")) and not errors,
                           "errors": errors,
                           "warnings": [str(w) for w in (verifier.get("warnings") or [])]}
        out["ok"] = ok and out["verifier"]["passed"]
    except (ModelProviderError, KeyError, TypeError) as exc:
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exam", type=int, required=True)
    ap.add_argument("--apply", action="store_true",
                    help="record results on the questions and quarantine failures")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    db = SessionLocal()
    exam = db.get(Exam, args.exam)
    if not exam:
        raise SystemExit(f"no exam {args.exam}")
    items = db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id)
                       .order_by(ExamItem.position)).all()
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise SystemExit("model provider is not configured")
    print(f"exam {exam.id}: checking {len(items)} items "
          f"(blind solver + independent verifier)\n")

    results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_check, provider, i.id,
                               {**i.snapshot, "position": i.position}): i for i in items}
        for future in as_completed(futures):
            row = future.result()
            results[row["item_id"]] = row
            if not row["ok"]:
                why = row.get("error") or row["solver"]["verdict"]
                if row.get("verifier", {}).get("errors"):
                    why = f"{why}; verifier: {row['verifier']['errors'][0][:90]}"
                print(f"  FAIL pos {row['position']:>3} [{(row['section'] or '')[:22]:22}] {why}")
                print(f"       {row['stem']}")

    failed = [r for r in results.values() if not r["ok"]]
    passed = [r for r in results.values() if r["ok"]]
    solver_disagreed = [r for r in failed
                        if r.get("solver", {}).get("verdict") == "solver_disagrees_with_key"]
    ambiguous = [r for r in failed
                 if r.get("solver", {}).get("verdict") == "solver_reports_ambiguous"]
    factual = [r for r in failed if r.get("verifier", {}).get("errors")]
    print(f"\n{len(passed)}/{len(items)} cleared both passes")
    print(f"  key disputed by the blind solver : {len(solver_disagreed)}")
    print(f"  solver calls the item ambiguous  : {len(ambiguous)}")
    print(f"  verifier reports a factual error : {len(factual)}")

    if not args.apply:
        print("\ndry run — rerun with --apply to record results and quarantine failures")
        return

    quarantined = 0
    for item in items:
        row = results.get(item.id)
        if not row:
            continue
        question = db.get(Question, item.question_id)
        if question is None:
            continue
        report = dict(question.validation_report or {})
        report["independent_solver"] = row.get("solver", {"passed": False})
        report["independent_verifier"] = row.get("verifier", {"passed": False,
                                                              "errors": ["not_run"]})
        report["structural_checks"] = "passed"
        if row["ok"]:
            report["passed"] = True
            report["errors"] = [e for e in report.get("errors", [])
                                if e != "unreviewed_machine_authored"]
            question.validation_report = report
            # `machine_validated` is what the serving gate requires, and it now means what it
            # says: the deterministic validator, a blind solver and an independent verifier all
            # cleared this item. It is still not human review.
            question.status = "machine_validated"
        else:
            report["passed"] = False
            question.validation_report = report
            question.status = "draft"
            db.delete(item)
            quarantined += 1
    db.flush()

    survivors = db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id)
                           .order_by(ExamItem.position)).all()
    for offset, row in enumerate(survivors):      # two-phase: uq_exam_item_position
        row.position = 10_000 + offset
    db.flush()
    for offset, row in enumerate(survivors):
        row.position = offset
    exam.question_ids = [row.question_id for row in survivors]
    blueprint = dict(exam.blueprint or {})
    blueprint["question_count"] = len(survivors)
    blueprint["gates_cleared"] = ["structural_validator", "verbatim_evidence_excerpt",
                                 "auto_gradeable", "no_source_reference",
                                 "independent_blind_solver", "independent_verifier"]
    blueprint["gates_outstanding"] = ["grounding_in_approved_claims", "human_review"]
    exam.blueprint = blueprint
    db.add(AuditLog(
        actor_user_id=None, action="exam.items_verified_and_quarantined",
        entity_type="exam", entity_id=str(exam.id),
        details={"checked": len(items), "cleared": len(passed), "quarantined": quarantined,
                 "key_disputed_by_solver": len(solver_disagreed),
                 "ambiguous": len(ambiguous), "factual_errors": len(factual),
                 "note": "cleared means two independent passes found nothing; it is not review"}))
    db.commit()
    print(f"\nquarantined {quarantined} item(s); exam now holds {len(survivors)}")


if __name__ == "__main__":
    main()
