from __future__ import annotations
from difflib import SequenceMatcher
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import Question, ScientificClaim, Source
from app.services.rights import can_use_for_generation


def validate_candidate(
    db: Session,
    *,
    stem: str,
    choices: list[str],
    answer_spec: dict,
    claim_ids: list[int],
    source_id: int | None,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if len(stem.strip()) < 12:
        errors.append("stem_too_short")
    if len(choices) != 4 or any(len(c.strip()) < 1 for c in choices):
        errors.append("four_meaningful_choices_required")
    if len(set(c.strip().lower() for c in choices)) != len(choices):
        errors.append("duplicate_choices")
    idx = answer_spec.get("correct_index")
    if not isinstance(idx, int) or idx < 0 or idx >= len(choices):
        errors.append("invalid_correct_index")
    claims = []
    if claim_ids:
        claims = db.scalars(
            select(ScientificClaim).where(
                ScientificClaim.id.in_(claim_ids), ScientificClaim.approved.is_(True),
                ScientificClaim.source_snapshot_id.is_not(None),
            )
        ).all()
        if len(claims) != len(set(claim_ids)):
            errors.append("unapproved_or_missing_claim")
    if source_id is not None:
        source = db.get(Source, source_id)
        if not source or not can_use_for_generation(source.rights_status, source.approved):
            errors.append("source_not_authorized_for_generation")
    previous = db.scalars(select(Question.stem)).all()
    max_similarity = max((SequenceMatcher(None, stem.lower(), old.lower()).ratio() for old in previous), default=0.0)
    if max_similarity >= 0.92:
        errors.append("near_duplicate_question")
    elif max_similarity >= 0.80:
        warnings.append("high_similarity_requires_review")
    factual_grounding = "approved_claims" if claims else "deterministic_template"
    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "factual_grounding": factual_grounding,
        "claim_ids": [c.id for c in claims],
        "answer_consistency": "invalid_correct_index" not in errors,
        "max_existing_similarity": round(max_similarity, 4),
        "rights_check": "source_not_authorized_for_generation" not in errors,
        "validator_version": "2.0",
    }


def build_similarity_report(db: Session, stem: str, choices: list[str], exclude_question_id: int | None = None) -> dict:
    """Persist explainable lexical signals; human review remains required."""
    normalized = " ".join(stem.lower().split())
    current_tokens = set(normalized.split())
    candidates = []
    for question in db.scalars(select(Question)).all():
        if question.id == exclude_question_id:
            continue
        old = " ".join(question.stem.lower().split())
        old_tokens = set(old.split())
        union = current_tokens | old_tokens
        candidates.append({
            "question_id": question.id,
            "sequence_similarity": round(SequenceMatcher(None, normalized, old).ratio(), 4),
            "token_jaccard": round(len(current_tokens & old_tokens) / len(union), 4) if union else 0.0,
            "choice_overlap": round(len(set(map(str.lower, choices)) & set(map(str.lower, question.choices or []))) / 4, 4),
        })
    candidates.sort(key=lambda item: max(item["sequence_similarity"], item["token_jaccard"]), reverse=True)
    top = candidates[:5]
    max_score = max((max(x["sequence_similarity"], x["token_jaccard"]) for x in top), default=0.0)
    return {
        "version": "1.0",
        "method": "normalized_sequence_token_and_choice_overlap",
        "top_matches": top,
        "max_similarity": round(max_score, 4),
        "outcome": "blocked" if max_score >= 0.92 else "review_required" if max_score >= 0.75 else "clear",
        "embedding_check": "not_configured",
    }
