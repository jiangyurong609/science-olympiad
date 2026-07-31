from __future__ import annotations
import math
from difflib import SequenceMatcher
from typing import Callable, Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import Question, ScientificClaim, Source
from app.services.rights import can_use_for_generation

EMBED_BLOCK = 0.92
EMBED_REVIEW = 0.80


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


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


def build_similarity_report(
    db: Session,
    stem: str,
    choices: list[str],
    exclude_question_id: int | None = None,
    embed: Callable[[list[str]], list[list[float]]] | None = None,
) -> dict:
    """Persist explainable lexical signals; human review remains required.

    When an `embed` function is supplied, a semantic embedding check is added: the stem is
    compared by cosine similarity against every other stem's embedding. `embed` maps a list of
    texts to a list of vectors (injected so the provider/model is a config choice, and so tests
    can supply a deterministic stub). Without it the embedding check stays "not_configured"."""
    normalized = " ".join(stem.lower().split())
    current_tokens = set(normalized.split())
    others = [q for q in db.scalars(select(Question)).all() if q.id != exclude_question_id]
    candidates = []
    for question in others:
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
        "version": "1.1",
        "method": "normalized_sequence_token_and_choice_overlap",
        "top_matches": top,
        "max_similarity": round(max_score, 4),
        "outcome": "blocked" if max_score >= 0.92 else "review_required" if max_score >= 0.75 else "clear",
        "embedding_check": _embedding_check(stem, others, embed),
    }


def _embedding_check(stem: str, others, embed) -> dict | str:
    """Semantic near-duplicate signal via cosine over embeddings. 'not_configured' if no embedder."""
    if embed is None:
        return "not_configured"
    other_stems = [q.stem for q in others]
    if not other_stems:
        return {"max_cosine": 0.0, "outcome": "clear", "nearest_question_id": None}
    try:
        vectors = embed([stem, *other_stems])
    except Exception as exc:  # never let embedding failure sink generation
        return {"error": f"embedding_failed: {type(exc).__name__}", "outcome": "unavailable"}
    query, rest = vectors[0], vectors[1:]
    best_score, best_id = 0.0, None
    for q, vec in zip(others, rest):
        score = _cosine(query, vec)
        if score > best_score:
            best_score, best_id = score, q.id
    outcome = "blocked" if best_score >= EMBED_BLOCK else "review_required" if best_score >= EMBED_REVIEW else "clear"
    return {"max_cosine": round(best_score, 4), "outcome": outcome, "nearest_question_id": best_id}
