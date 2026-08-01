"""Phase 2 — regenerate a course's items through the rigorous generation path.

The live catalog was written by a single-shot generator that skipped validation and review.
This routes generation through `model_generation.generate_model_questions`, which grounds on
approved claims and then applies a deterministic validator, an independent blind solver, an
independent verifier, and lexical/embedding similarity checks.

Output stays at `machine_validated`. Nothing here publishes — that is Phase 3's review ladder.

    PYTHONPATH=. python -m scripts.regenerate_course --event rocks-and-minerals-b --per-concept 5
"""
from __future__ import annotations

import argparse
import uuid
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Concept, Event, Question, QuestionStatus, User
from app.services.model_generation import generate_model_questions
from app.services.model_provider import ModelProviderError


def main() -> None:
    ap = argparse.ArgumentParser(description="Regenerate a course through the rigorous path")
    ap.add_argument("--event", required=True)
    ap.add_argument("--per-concept", type=int, default=5)
    ap.add_argument("--difficulty", type=float, default=0.5)
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    run_id = args.run_id or f"regen-{uuid.uuid4().hex[:10]}"
    outcomes: Counter[str] = Counter()

    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == args.event))
        if not event:
            raise SystemExit(f"unknown event {args.event!r}")
        actor = db.scalar(select(User).where(User.role.in_(("editor", "admin"))))
        if not actor:
            raise SystemExit("no editor/admin account to attribute the run to")
        concepts = db.scalars(select(Concept).where(Concept.event_id == event.id)).all()
        if not concepts:
            raise SystemExit(f"{event.slug} has no concepts to generate against")

        print(f"regenerating {event.slug} | run {run_id} | {len(concepts)} concepts")
        produced: list[Question] = []
        for concept in concepts:
            for level in ("recall", "application", "transfer"):
                try:
                    items = generate_model_questions(
                        db, actor, event, concept,
                        count=args.per_concept, difficulty=args.difficulty,
                        cognitive_level=level,
                    )
                except (ModelProviderError, ValueError) as exc:
                    outcomes[f"failed:{type(exc).__name__}"] += 1
                    print(f"  {concept.name[:28]:28} {level:12} -> {type(exc).__name__}: "
                          f"{str(exc)[:70]}")
                    continue
                for item in items:
                    provenance = dict(item.generation_provenance or {})
                    provenance["generation_run"] = run_id
                    item.generation_provenance = provenance
                    outcomes[item.status] += 1
                produced.extend(items)
                db.commit()
                print(f"  {concept.name[:28]:28} {level:12} -> {len(items)} items "
                      f"({sum(1 for i in items if i.status == QuestionStatus.MACHINE_VALIDATED.value)} validated)")

        print(f"\nrun {run_id}: {len(produced)} items")
        for status, count in outcomes.most_common():
            print(f"  {status}: {count}")
        print(f"\naudit with: python -m scripts.audit_content_quality "
              f"--status machine_validated --generation-run {run_id}")


if __name__ == "__main__":
    main()
