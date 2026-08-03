"""Give every event with reviewed items a Skill Lab, from the items it already has.

Skill Labs read `PracticeSet`, and the whole catalog held three — all hand-written in the
seed. So every event's practice page said "Guided practice is being calibrated" no matter how
many gated items sat behind it: the items were in `Question`, and nothing ever turned them
into the thing the page reads.

This is assembly, not authoring. Items that already cleared the validator, the blind solver,
the independent verifier, grounding in approved claims, and same-event provenance are grouped
by concept into short sets. Nothing new is generated and no gate is loosened — an item that
cannot enter an exam cannot enter a lab either, because it is the same bar and the same call.

Sets are `published` because the items in them are what Phase 0 already permits a student to
be scored on; the labelling students see comes from the item status, exactly as it does for
exams.

    PYTHONPATH=. python -m scripts.build_practice_sets
    DATABASE_URL=<prod> PYTHONPATH=. python -m scripts.build_practice_sets --apply
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, PracticeSet, PracticeSetVersion, Question,
)
from scripts.build_launch_exams import grounded_in_its_own_event, item_clears_every_gate

MIN_ITEMS = 4          # below this it is a quiz, not a lab
MAX_ITEMS = 8          # a lab should be finishable in one sitting
SECONDS_PER_ITEM = 45


def _item_payload(question: Question, index: int) -> dict | None:
    """A `Question` in the shape the practice runner reads."""
    choices = [str(c) for c in (question.choices or []) if str(c).strip()]
    key = (question.answer_spec or {}).get("correct_index")
    if len(choices) < 2 or not isinstance(key, int) or not 0 <= key < len(choices):
        return None
    return {
        "id": f"q{question.id}",
        "prompt": question.stem,
        # The runner draws an evidence board from `property_profile`. Generated items carry
        # their reasoning in the stem instead, so the board is omitted rather than faked —
        # an empty labelled tile is the "Concept" placeholder defect in another costume.
        "property_profile": [],
        "choices": choices,
        "correct_index": key,
        "explanation": question.explanation or "",
        "misconception_by_choice": {},
        "question_id": question.id,
    }


def run(apply: bool) -> dict:
    stats: Counter[str] = Counter()
    rows: list[dict] = []
    with SessionLocal() as db:
        events = {e.id: e for e in db.scalars(select(Event).where(Event.active.is_(True))).all()}
        concepts = {c.id: c for c in db.scalars(select(Concept)).all()}
        existing = {(p.event_id, p.slug) for p in db.scalars(select(PracticeSet)).all()}

        by_event: dict[int, list[Question]] = defaultdict(list)
        for question in db.scalars(select(Question)).all():
            if question.event_id not in events:
                continue
            if not item_clears_every_gate(question):
                continue
            if not grounded_in_its_own_event(db, question):
                continue
            by_event[question.event_id].append(question)

        for event_id, questions in sorted(by_event.items()):
            event = events[event_id]
            grouped: dict[int | None, list[Question]] = defaultdict(list)
            for question in questions:
                grouped[question.concept_id].append(question)

            made = 0
            for concept_id, pool in sorted(grouped.items(), key=lambda kv: (kv[0] or 0)):
                if len(pool) < MIN_ITEMS:
                    stats["concepts_with_too_few_items"] += 1
                    continue
                concept = concepts.get(concept_id) if concept_id else None
                name = concept.name if concept else event.name
                slug = f"lab-{(concept.id if concept else 0)}-{event.slug}"[:140]
                if (event_id, slug) in existing:
                    stats["already_built"] += 1
                    continue

                chosen = pool[:MAX_ITEMS]
                items = [p for p in (_item_payload(q, i) for i, q in enumerate(chosen)) if p]
                if len(items) < MIN_ITEMS:
                    stats["items_unusable_in_a_lab"] += 1
                    continue
                claim_ids = sorted({c for q in chosen
                                    for c in ((q.validation_report or {}).get("claim_ids") or [])
                                    if isinstance(c, int)})
                citations = []
                for question in chosen:
                    for citation in question.citations or []:
                        if citation not in citations:
                            citations.append(citation)

                stats["sets"] += 1
                made += 1
                rows.append({"event": event.slug, "title": f"{name} Skill Lab",
                             "items": len(items)})
                if not apply:
                    continue
                practice_set = PracticeSet(
                    event_id=event_id, concept_id=concept_id, slug=slug,
                    title=f"{name} Skill Lab"[:255],
                    summary=(f"{len(items)} reviewed questions on {name}, with feedback in "
                             f"study mode or {SECONDS_PER_ITEM}s per item under station "
                             f"timing.")[:500],
                    practice_type="classification", status="published",
                    current_version=1,
                    estimated_minutes=max(3, round(len(items) * SECONDS_PER_ITEM / 60)),
                )
                db.add(practice_set)
                db.flush()
                db.add(PracticeSetVersion(
                    practice_set_id=practice_set.id, version=1,
                    review_status="machine_validated", items=items,
                    claim_ids=claim_ids, citations=citations[:8]))
                existing.add((event_id, slug))
            if made:
                stats["events_with_a_lab"] += 1
        if apply:
            db.commit()
        else:
            db.rollback()
    return {"stats": stats, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Assemble Skill Labs from reviewed items")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    result = run(args.apply)
    print("=" * 80)
    print(f"SKILL LABS [{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 80)
    for row in result["rows"][:24]:
        print(f"  {row['event'][:26]:28} {row['title'][:34]:36} {row['items']} items")
    if len(result["rows"]) > 24:
        print(f"  … {len(result['rows']) - 24} more")
    print("-" * 80)
    for key, value in sorted(result["stats"].items()):
        print(f"  {key:30} {value}")
    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")
    print("=" * 80)


if __name__ == "__main__":
    main()
