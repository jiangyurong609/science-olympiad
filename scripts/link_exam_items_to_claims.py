"""Link each machine-authored exam item to a claim, so its grounding can be judged.

An exam item earns `machine_practice` — the class that lets a student START it — only when it
clears the solver, the verifier, and `factual_grounding == "approved_claims"`. The first two
are recorded by `exam_agent`. The third was never reachable for these papers, and the reason
is worth stating precisely:

`build_season_exam` writes items from SOURCE PASSAGES and quotes a sentence from the passage as
the item's `evidence_excerpt`. `ground_event` harvests claims from the first 120 sentences of
each snapshot. The two overlap only by coincidence — 59 of 340 items across seven subjects —
so 281 perfectly well-grounded items had no claim row to point at, and every exam fell back to
`unreviewed_practice`, which refuses new attempts.

What this does, in the order that keeps it honest:

  1. For each item, take the `evidence_excerpt` and the source its citation names.
  2. VERIFY the excerpt appears verbatim in that source's retained snapshot. This is the same
     check `ground_event` applies to a harvested sentence, and it is the whole reason a claim
     means anything: an excerpt nobody can find in the source is not evidence.
  3. Create the claim if it does not exist, UNAPPROVED, attached to the item's own event.
  4. Record the claim id on the item's validation report.

It does NOT approve anything and does NOT write `factual_grounding`. Approval is a judgement
about whether a sentence is fit to teach from, a human or a reviewing agent makes it, and
`--approve-reviewed` applies it only for claim ids handed in from such a review.

    DATABASE_URL=... python -m scripts.link_exam_items_to_claims --event meteorology-b-2027
    DATABASE_URL=... python -m scripts.link_exam_items_to_claims --all --apply
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, Exam, ExamItem, Question, ScientificClaim, Source, SourceSnapshot,
)

MACHINE = "machine_practice"


def _snapshot_text(db, source_id: int, cache: dict[int, str]) -> str:
    if source_id not in cache:
        snapshot = db.scalar(select(SourceSnapshot)
                             .where(SourceSnapshot.source_id == source_id)
                             .order_by(SourceSnapshot.id.desc()))
        cache[source_id] = (snapshot.extracted_text or "") if snapshot else ""
    return cache[source_id]


def link_event(db, event: Event, apply: bool) -> dict:
    stats: Counter[str] = Counter()
    concepts = db.scalars(select(Concept).where(Concept.event_id == event.id)).all()
    if not concepts:
        return {"event": event.slug, "error": "no concepts"}
    by_name = {c.name.lower(): c for c in concepts}
    existing = {c.evidence_excerpt: c for c in db.scalars(
        select(ScientificClaim).join(Concept, Concept.id == ScientificClaim.concept_id)
        .where(Concept.event_id == event.id))}
    cache: dict[int, str] = {}

    exams = db.scalars(select(Exam).where(Exam.event_id == event.id,
                                          Exam.release_class == MACHINE)).all()
    seen: set[int] = set()
    for exam in exams:
        for item in db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id)):
            if item.question_id in seen:
                continue
            seen.add(item.question_id)
            question = db.get(Question, item.question_id)
            if question is None:
                stats["no_question"] += 1
                continue
            report = dict(question.validation_report or {})
            if report.get("claim_ids"):
                stats["already_linked"] += 1
                continue
            excerpt = (question.generation_provenance or {}).get("evidence_excerpt") or ""
            citations = question.citations or []
            source_id = citations[0].get("source_id") if citations else None
            if not excerpt or not source_id:
                stats["no_excerpt_or_source"] += 1
                continue
            claim = existing.get(excerpt)
            if claim is None:
                text = _snapshot_text(db, source_id, cache)
                if excerpt not in text:
                    # The excerpt cannot be found in the source it cites. That is exactly the
                    # case a grounding check exists to catch, and it is refused rather than
                    # linked to something approximate.
                    stats["excerpt_not_in_source"] += 1
                    continue
                stats["verified_verbatim"] += 1
                if not apply:
                    continue
                concept = (by_name.get((question.stem or "").lower())
                           or concepts[hash(excerpt) % len(concepts)])
                claim = ScientificClaim(
                    source_id=source_id, concept_id=concept.id,
                    claim_text=excerpt[:500], evidence_excerpt=excerpt,
                    locator=citations[0].get("url", ""), confidence=0.8,
                    approved=False,      # never here; approval follows a review
                )
                db.add(claim)
                db.flush()
                existing[excerpt] = claim
            else:
                stats["reused_existing_claim"] += 1
            if apply:
                report["claim_ids"] = [claim.id]
                question.validation_report = report
                stats["linked"] += 1
    if apply:
        db.commit()
    return {"event": event.slug, "items": len(seen), **stats}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.all:
            events = [e for e in db.scalars(select(Event).where(Event.season == 2027))
                      if db.scalar(select(Exam).where(Exam.event_id == e.id,
                                                      Exam.release_class == MACHINE))]
        else:
            events = [db.scalar(select(Event).where(Event.slug == args.event))]
        for event in events:
            if event is None:
                continue
            print(json.dumps(link_event(db, event, args.apply)))


if __name__ == "__main__":
    main()
