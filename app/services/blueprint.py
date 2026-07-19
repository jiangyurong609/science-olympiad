"""Per-event test blueprints for structure-aware mock assembly.

A blueprint describes the shape of an event's real tests: the mix of question
types, cognitive levels, difficulty bands, and topical sections. It is either
DERIVED deterministically from the event's question pool, or produced by an LLM
structure analysis (scripts/analyze_structure) and cached as JSON under
data/blueprints/. Mock assembly uses it to sample a representative exam instead
of a flat random draw.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.entities import Event, Question

BLUEPRINT_DIR = Path("data/blueprints")


def _band(difficulty: float) -> str:
    return "easy" if difficulty < 0.4 else ("hard" if difficulty > 0.7 else "medium")


def _fractions(counter: Counter, total: int) -> dict:
    return {k: round(v / total, 3) for k, v in counter.items()} if total else {}


def derive_blueprint(pool: list[Question]) -> dict:
    """Deterministic structural profile computed from the question pool."""
    n = len(pool)
    types = Counter(q.question_type for q in pool)
    cognitive = Counter((q.cognitive_level or "application") for q in pool)
    difficulty = Counter(_band(q.difficulty if q.difficulty is not None else 0.5) for q in pool)
    sections = Counter(
        (q.generation_provenance or {}).get("section")
        for q in pool if (q.generation_provenance or {}).get("section")
    )
    return {
        "source": "derived",
        "pool_size": n,
        "type_mix": _fractions(types, n),
        "cognitive_mix": _fractions(cognitive, n),
        "difficulty_mix": _fractions(difficulty, n),
        "top_sections": [s for s, _ in sections.most_common(8)],
    }


def _blueprint_path(event: Event) -> Path:
    return BLUEPRINT_DIR / f"{event.slug}-{event.division}.json"


def load_blueprint(event: Event) -> dict | None:
    path = _blueprint_path(event)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_blueprint(event: Event, blueprint: dict) -> Path:
    BLUEPRINT_DIR.mkdir(parents=True, exist_ok=True)
    path = _blueprint_path(event)
    path.write_text(json.dumps(blueprint, indent=2))
    return path


def blueprint_for(db: Session, event: Event, pool: list[Question]) -> dict:
    """Persisted LLM blueprint if available, otherwise derived from the pool.
    Always carries a live derived summary so proportions reflect the real pool."""
    derived = derive_blueprint(pool)
    stored = load_blueprint(event)
    if stored:
        merged = {**derived, **stored, "derived": derived, "source": stored.get("source", "llm")}
        return merged
    return derived


def _target_counts(size: int, distribution: dict) -> dict:
    """Largest-remainder allocation of `size` across a proportional distribution."""
    raw = {k: size * f for k, f in distribution.items()}
    counts = {k: int(v) for k, v in raw.items()}
    remainder = size - sum(counts.values())
    for key in sorted(distribution, key=lambda k: -(raw[k] - counts[k]))[:max(0, remainder)]:
        counts[key] += 1
    return counts


def _stratified(pool: list[Question], size: int, distribution: dict, key_fn) -> list[Question] | None:
    """Sample `size` questions to match `distribution` over key_fn(q); top up
    randomly when a stratum is too small. Returns None if the axis is unusable."""
    buckets: dict[str, list[Question]] = {}
    for q in pool:
        buckets.setdefault(key_fn(q), []).append(q)
    distribution = {k: v for k, v in (distribution or {}).items() if k in buckets and v > 0}
    if len(distribution) < 2:  # nothing to stratify (single or no matching bucket)
        return None
    scale = sum(distribution.values())
    distribution = {k: v / scale for k, v in distribution.items()}
    targets = _target_counts(size, distribution)
    picked: list[Question] = []
    for key, count in targets.items():
        bucket = list(buckets[key])
        random.shuffle(bucket)
        picked.extend(bucket[:count])
    if len(picked) < size:
        chosen = {q.id for q in picked}
        remaining = [q for q in pool if q.id not in chosen]
        random.shuffle(remaining)
        picked.extend(remaining[:size - len(picked)])
    random.shuffle(picked)
    return picked[:size]


def select_for_blueprint(pool: list[Question], size: int, blueprint: dict) -> list[Question]:
    """Mirror the blueprint's structure — by question type first (varies in every
    pool), then cognitive level — falling back to a flat random sample."""
    size = min(size, len(pool))
    for mix_key, key_fn in (
        ("type_mix", lambda q: q.question_type),
        ("cognitive_mix", lambda q: q.cognitive_level or "application"),
    ):
        result = _stratified(pool, size, blueprint.get(mix_key) or {}, key_fn)
        if result is not None:
            return result
    return random.sample(pool, size)
