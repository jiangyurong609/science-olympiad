"""Phase 0 — item-level content quality audit.

The course-level rubric is `scripts/audit_catalog_quality.py` (Phase Q). This is the
*item-level* half: it re-checks every Question for structural validity, grounding, and
duplication, and reports exams that fall under their blueprint. Parameterized by status and
generation-run so Phase 2 can audit exactly the rows it produced (R1), with a census proving
zero rows went unaudited.

Read-only. Never mutates content.

NB: `app.services.validation.validate_candidate` cannot be used verbatim for a retroactive
audit — its similarity check compares each stem against ALL stems including itself, so every
stored question would self-match as a near-duplicate. This auditor mirrors the structural
checks and computes duplication with self excluded.

Usage:
    PYTHONPATH=. python -m scripts.audit_content_quality
    PYTHONPATH=. python -m scripts.audit_content_quality --status machine_validated --generation-run <id>
    PYTHONPATH=. python -m scripts.audit_content_quality --json docs/history/item_audit.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.entities import Exam, Question, ScientificClaim, Source
from app.services.rights import can_use_for_generation

SINGLE_SHOT_MARKERS = {"catalog-2026-generated"}


def _norm_stem(stem: str) -> str:
    return " ".join((stem or "").lower().split())


def _structural_errors(question_type: str, stem: str, choices: list, answer_spec: dict) -> list[str]:
    """Type-aware structural gate. The catalog mixes single_choice (MCQ), short_answer, and
    numeric items — applying MCQ rules to all of them is wrong, so each type is checked on its
    own contract."""
    errors: list[str] = []
    choices = choices or []
    answer_spec = answer_spec or {}
    if len((stem or "").strip()) < 12:
        errors.append("stem_too_short")

    if question_type == "single_choice":
        if len(choices) != 4 or any(len(str(c).strip()) < 1 for c in choices):
            errors.append("four_meaningful_choices_required")
        if len({str(c).strip().lower() for c in choices}) != len(choices):
            errors.append("duplicate_choices")
        idx = answer_spec.get("correct_index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(choices):
            errors.append("invalid_correct_index")
    elif question_type == "short_answer":
        if not str(answer_spec.get("answer", "")).strip():
            errors.append("missing_answer")
        if not isinstance(answer_spec.get("accepted"), list) or not answer_spec.get("accepted"):
            errors.append("missing_accepted_answers")
    elif question_type == "numeric":
        if answer_spec.get("answer") in (None, ""):
            errors.append("missing_numeric_answer")
        tol = answer_spec.get("tolerance")
        if not isinstance(tol, (int, float)) or tol < 0:
            errors.append("missing_or_invalid_tolerance")
    else:
        errors.append("unknown_question_type")
    return errors


def _is_grounded(db: Session, q: Question, approved_claim_ids: set[int]) -> bool:
    """Grounded if it cites an approved claim, or its source is rights-cleared for generation,
    or its own validation report already recorded approved-claim grounding."""
    if (q.validation_report or {}).get("factual_grounding") == "approved_claims":
        return True
    for cite in q.citations or []:
        cid = cite.get("claim_id") if isinstance(cite, dict) else None
        if cid in approved_claim_ids:
            return True
    if q.source_id is not None:
        src = db.get(Source, q.source_id)
        if src and can_use_for_generation(src.rights_status, src.approved):
            return True
    return False


def run(status: str | None = None, generation_run: str | None = None) -> dict:
    with SessionLocal() as db:
        query = select(Question)
        if status:
            query = query.where(Question.status == status)
        questions = db.scalars(query.order_by(Question.id)).all()

        # generation-run filter (provenance marker or explicit run id)
        if generation_run:
            questions = [
                q for q in questions
                if generation_run in {
                    (q.generation_provenance or {}).get("generation_run"),
                    (q.generation_provenance or {}).get("marker"),
                }
            ]

        approved_claim_ids = set(
            db.scalars(select(ScientificClaim.id).where(ScientificClaim.approved.is_(True))).all()
        )

        audited = 0
        passed = 0
        grounded = 0
        single_shot = 0
        error_histogram: Counter[str] = Counter()
        stem_buckets: dict[str, list[int]] = defaultdict(list)
        per_question = []

        for q in questions:
            audited += 1
            errors = _structural_errors(q.question_type, q.stem, q.choices, q.answer_spec)
            is_grounded = _is_grounded(db, q, approved_claim_ids)
            is_single_shot = (q.generation_provenance or {}).get("marker") in SINGLE_SHOT_MARKERS
            if not errors:
                passed += 1
            if is_grounded:
                grounded += 1
            if is_single_shot:
                single_shot += 1
            error_histogram.update(errors)
            stem_buckets[_norm_stem(q.stem)].append(q.id)
            if errors or not is_grounded:
                per_question.append({
                    "id": q.id, "status": q.status, "event_id": q.event_id,
                    "errors": errors, "grounded": is_grounded, "single_shot": is_single_shot,
                })

        # exact-normalized-stem duplicate clusters (self excluded; ≥2 in a bucket = a cluster).
        # A cheap, deterministic lower bound; embedding-level near-dup detection is Phase 1.
        dup_clusters = [ids for ids in stem_buckets.values() if len(ids) > 1]
        duplicate_questions = sum(len(ids) for ids in dup_clusters)

        # exams under their blueprint's expected item count
        exams_under_blueprint = []
        for exam in db.scalars(select(Exam)).all():
            expected = _blueprint_expected(exam.blueprint or {})
            have = len(exam.question_ids or [])
            if expected is not None and have < expected:
                exams_under_blueprint.append({
                    "exam_id": exam.id, "event_id": exam.event_id,
                    "have": have, "expected": expected,
                })

        return {
            "filter": {"status": status, "generation_run": generation_run},
            "census": {
                "matched": len(questions),
                "audited": audited,
                "unaudited": len(questions) - audited,  # must be 0
            },
            "totals": {
                "questions": audited,
                "passing_structural": passed,
                "passing_pct": round(100 * passed / audited, 1) if audited else 0.0,
                "grounded": grounded,
                "grounded_pct": round(100 * grounded / audited, 1) if audited else 0.0,
                "single_shot_provenance": single_shot,
                "near_dup_clusters": len(dup_clusters),
                "duplicate_questions": duplicate_questions,
                "exams_under_blueprint": len(exams_under_blueprint),
            },
            "error_histogram": dict(error_histogram.most_common()),
            "duplicate_clusters": dup_clusters[:50],
            "exams_under_blueprint_detail": exams_under_blueprint[:50],
            "flagged_questions": per_question[:200],
        }


def _blueprint_expected(blueprint: dict) -> int | None:
    """Best-effort expected item count from a blueprint JSON. Returns None if not derivable."""
    if not isinstance(blueprint, dict):
        return None
    for key in ("total", "total_items", "item_count", "question_count"):
        v = blueprint.get(key)
        if isinstance(v, int) and v > 0:
            return v
    # sum of a per-type/per-concept distribution if present and numeric
    dist = blueprint.get("distribution") or blueprint.get("counts")
    if isinstance(dist, dict):
        nums = [v for v in dist.values() if isinstance(v, int)]
        if nums:
            return sum(nums)
    return None


def _print(result: dict) -> None:
    c, t = result["census"], result["totals"]
    print("=" * 68)
    print("ITEM-LEVEL CONTENT AUDIT (Phase 0)")
    f = result["filter"]
    if f["status"] or f["generation_run"]:
        print(f"filter: status={f['status']} generation_run={f['generation_run']}")
    print("=" * 68)
    print(f"census: matched={c['matched']} audited={c['audited']} unaudited={c['unaudited']}")
    print(f"structural pass : {t['passing_structural']}/{t['questions']} ({t['passing_pct']}%)")
    print(f"grounded        : {t['grounded']}/{t['questions']} ({t['grounded_pct']}%)")
    print(f"single-shot prov: {t['single_shot_provenance']}")
    print(f"near-dup clusters: {t['near_dup_clusters']} ({t['duplicate_questions']} questions)")
    print(f"exams under blueprint: {t['exams_under_blueprint']}")
    if result["error_histogram"]:
        print("-" * 68)
        print("structural error histogram:")
        for code, n in result["error_histogram"].items():
            print(f"  {n:>5}  {code}")
    print("=" * 68)


def main() -> None:
    ap = argparse.ArgumentParser(description="Item-level content quality audit")
    ap.add_argument("--status", default=None)
    ap.add_argument("--generation-run", dest="generation_run", default=None)
    ap.add_argument("--json", dest="json_path", default=None)
    args = ap.parse_args()

    result = run(status=args.status, generation_run=args.generation_run)
    _print(result)
    if args.json_path:
        with open(args.json_path, "w") as fh:
            json.dump(result, fh, indent=2)
        print(f"\nWrote full report -> {args.json_path}")


if __name__ == "__main__":
    main()
