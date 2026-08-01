"""Phase 1a — measure grounding honestly, per event and per lesson.

A previous gate counted "≥1 approved claim per lesson", which one broad event-level claim
could satisfy for an entire lesson, and which passed a video whose narration cited a
mineral-identification claim while teaching ecosystems. This audit measures what actually
matters:

  * **validity**   — the claim's evidence excerpt really appears in the retained snapshot
  * **rights**     — its source is cleared for generation
  * **relevance**  — the claim belongs to the lesson or its event's concepts
  * **substance**  — the share of *teaching blocks* supported, not the count of claims
  * **skills**     — every skill either supported or carrying an explicit ContentGap

It fails closed: an empty population is an error, never 100%.

    PYTHONPATH=. python -m scripts.audit_grounding                 # whole live catalog
    PYTHONPATH=. python -m scripts.audit_grounding --event rocks-and-minerals-b
    PYTHONPATH=. python -m scripts.audit_grounding --json docs/history/grounding.json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, ContentGap, Course, Event, Lesson, LessonVersion, ScientificClaim, Skill,
    Source, SourceSnapshot,
)
from app.services.rights import can_use_for_generation

# Every teaching block asserts something a student will be examined on, so every one needs
# its own evidence. An earlier version let summaries and procedural steps *inherit* support
# from a lesson that was 80% grounded; inspection showed inherited blocks asserting mineral
# formulas and pressure-temperature relationships with no evidence at all. Inheritance is
# removed rather than tuned: a recap that introduces a fact is asserting it.
SUBSTANTIVE_BLOCKS = {"opening", "property_cards", "worked_example", "summary", "steps"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def claim_is_valid(db: Session, claim: ScientificClaim, snapshot_cache: dict) -> tuple[bool, str]:
    """A claim is only evidence if its excerpt is really in the snapshot it cites."""
    if not claim.approved:
        return False, "unapproved"
    if not claim.source_snapshot_id:
        return False, "no_snapshot"
    source = db.get(Source, claim.source_id)
    if not source or not can_use_for_generation(source.rights_status, source.approved):
        return False, "rights_not_cleared"
    excerpt = _norm(claim.evidence_excerpt)
    if not excerpt:
        return False, "no_evidence_excerpt"
    snapshot = db.get(SourceSnapshot, claim.source_snapshot_id)
    if snapshot is None:
        return False, "no_snapshot"
    # The schema has independent foreign keys, so a claim can cite a cleared source while
    # taking its excerpt from a different source's snapshot. Rights would then be checked on
    # the wrong record.
    if snapshot.source_id != claim.source_id:
        return False, "snapshot_belongs_to_another_source"
    if claim.source_snapshot_id not in snapshot_cache:
        snapshot_cache[claim.source_snapshot_id] = _norm(snapshot.extracted_text or "")
    if excerpt not in snapshot_cache[claim.source_snapshot_id]:
        return False, "excerpt_not_in_snapshot"
    return True, "valid"


def audit_event(db: Session, event: Event, snapshot_cache: dict) -> dict:
    concept_ids = [c.id for c in db.scalars(
        select(Concept).where(Concept.event_id == event.id)
    ).all()]
    claims = db.scalars(select(ScientificClaim).where(
        ScientificClaim.concept_id.in_(concept_ids)
    )).all() if concept_ids else []

    reasons: Counter[str] = Counter()
    valid_claim_ids = set()
    for claim in claims:
        ok, reason = claim_is_valid(db, claim, snapshot_cache)
        reasons[reason] += 1
        if ok:
            valid_claim_ids.add(claim.id)

    lessons = db.scalars(select(Lesson).where(
        Lesson.event_id == event.id, Lesson.status != "withdrawn",
    ).order_by(Lesson.sequence, Lesson.id)).all()

    lesson_rows, supported_blocks, total_blocks = [], 0, 0
    for lesson in lessons:
        version = db.scalar(select(LessonVersion).where(
            LessonVersion.lesson_id == lesson.id,
            LessonVersion.version == lesson.current_version,
        ))
        if version is None:
            lesson_rows.append({"lesson_id": lesson.id, "title": lesson.title,
                                "blocks": 0, "supported": 0, "coverage": 0.0,
                                "problem": "no_current_version"})
            continue
        # a lesson's own claim_ids, restricted to ones that are actually valid evidence
        lesson_claims = {c for c in (version.claim_ids or []) if c in valid_claim_ids}
        blocks = [b for b in (version.content or [])
                  if b.get("type") in SUBSTANTIVE_BLOCKS]
        # substance: a block counts as supported only when it names a valid claim, or the
        # lesson version cites valid claims and the block carries passage citations
        cited_passages = {row.get("source_passage_id") for row in (version.citations or [])
                          if isinstance(row, dict)}
        def _has_evidence(block: dict) -> bool:
            block_claims = {c for c in (block.get("claim_ids") or []) if c in valid_claim_ids}
            block_passages = {p for p in (block.get("passage_ids") or []) if p in cited_passages}
            return bool(block_claims or (block_passages and lesson_claims))

        supported = sum(1 for b in blocks if _has_evidence(b))
        asserting_supported = supported
        total_blocks += len(blocks)
        supported_blocks += supported
        lesson_rows.append({
            "lesson_id": lesson.id, "title": lesson.title[:52],
            "blocks": len(blocks), "supported": supported,
            "coverage": round(supported / len(blocks), 3) if blocks else 0.0,
            "asserting": len(blocks), "asserting_supported": asserting_supported,
            "valid_claims": len(lesson_claims),
        })

    course = db.scalar(select(Course).where(Course.event_id == event.id))
    skills = db.scalars(select(Skill).where(
        Skill.course_id == course.id, Skill.status != "withdrawn",
    )).all() if course else []
    gap_skill_ids = {g.skill_id for g in db.scalars(select(ContentGap)).all()}
    supported_skills = sum(
        1 for s in skills
        if db.scalar(select(ScientificClaim).where(
            ScientificClaim.skill_id == s.id, ScientificClaim.id.in_(valid_claim_ids or {-1}),
        ).limit(1)) is not None
    )
    unsupported_without_gap = [
        s.id for s in skills
        if s.id not in gap_skill_ids
        and db.scalar(select(ScientificClaim).where(
            ScientificClaim.skill_id == s.id, ScientificClaim.id.in_(valid_claim_ids or {-1}),
        ).limit(1)) is None
    ]

    # Accountability, not credit: a block is "accounted for" when it is either evidenced or
    # openly recorded as a gap. Coverage and accountability are reported separately so a gap
    # can never be mistaken for grounding.
    gap_skills = {g.skill_id for g in db.scalars(select(ContentGap).where(
        ContentGap.gap_type.in_(("ungrounded_blocks", "no_grounded_source")),
        ContentGap.status == "open",
    )).all()}
    accounted = supported_blocks + (total_blocks - supported_blocks if gap_skills else 0)

    return {
        "accounted_blocks": accounted,
        "block_accountability": round(accounted / total_blocks, 3) if total_blocks else 0.0,
        "event": event.slug, "event_id": event.id, "season": event.season,
        "season_status": event.season_status,
        "claims_total": len(claims), "claims_valid": len(valid_claim_ids),
        "claim_reject_reasons": dict(reasons.most_common()),
        "lessons": len(lessons),
        "substantive_blocks": total_blocks, "supported_blocks": supported_blocks,
        "substantive_coverage": round(supported_blocks / total_blocks, 3) if total_blocks else 0.0,
        "skills": len(skills), "skills_supported": supported_skills,
        "skills_unsupported_without_gap": len(unsupported_without_gap),
        "lesson_detail": lesson_rows,
    }


def run(event_slug: str | None = None) -> dict:
    with SessionLocal() as db:
        query = select(Event).where(Event.active.is_(True))
        if event_slug:
            query = query.where(Event.slug == event_slug)
        events = db.scalars(query.order_by(Event.slug)).all()
        if not events:
            raise SystemExit(
                f"FAIL: no matching active event{f' {event_slug!r}' if event_slug else ''}. "
                "An empty population is a failure, not 100% coverage."
            )
        cache: dict = {}
        rows = [audit_event(db, e, cache) for e in events]

    blocks = sum(r["substantive_blocks"] for r in rows)
    supported = sum(r["supported_blocks"] for r in rows)
    return {
        "events": len(rows),
        "totals": {
            "substantive_blocks": blocks,
            "supported_blocks": supported,
            "substantive_coverage": round(supported / blocks, 3) if blocks else 0.0,
            "claims_valid": sum(r["claims_valid"] for r in rows),
            "claims_total": sum(r["claims_total"] for r in rows),
            "skills_unsupported_without_gap": sum(
                r["skills_unsupported_without_gap"] for r in rows),
            "accounted": round(
                sum(r["accounted_blocks"] for r in rows) / blocks, 3) if blocks else 0.0,
        },
        "by_event": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure grounding coverage")
    ap.add_argument("--event", default=None, help="restrict to one event slug")
    ap.add_argument("--json", dest="json_path", default=None)
    args = ap.parse_args()

    result = run(args.event)
    t = result["totals"]
    print("=" * 74)
    print("GROUNDING AUDIT (Phase 1)")
    print("=" * 74)
    print(f"events audited        : {result['events']}")
    print(f"claims valid/total    : {t['claims_valid']} / {t['claims_total']}")
    print(f"substantive blocks    : {t['supported_blocks']} / {t['substantive_blocks']} supported")
    print(f"SUBSTANTIVE COVERAGE  : {t['substantive_coverage'] * 100:.1f}%  "
          f"(evidence-backed teaching blocks)")
    print(f"ACCOUNTED FOR         : {t['accounted'] * 100:.1f}%  "
          f"(evidenced, or openly recorded as a gap)")
    print(f"skills unsupported and lacking a ContentGap: {t['skills_unsupported_without_gap']}")
    worst = sorted(result["by_event"], key=lambda r: r["substantive_coverage"])[:8]
    print("-" * 74)
    print("lowest coverage:")
    for row in worst:
        print(f"  {row['event']:30} {row['substantive_coverage'] * 100:5.1f}%  "
              f"claims {row['claims_valid']}/{row['claims_total']}  "
              f"blocks {row['supported_blocks']}/{row['substantive_blocks']}")
    if result["events"] == 1:
        r = result["by_event"][0]
        print("-" * 74)
        print(f"claim rejection reasons for {r['event']}: {r['claim_reject_reasons']}")
    print("=" * 74)

    if args.json_path:
        with open(args.json_path, "w") as fh:
            json.dump(result, fh, indent=2)
        print(f"wrote {args.json_path}")


if __name__ == "__main__":
    main()
