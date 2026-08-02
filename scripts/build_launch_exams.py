"""Assemble practice exams that look like the real thing, without reusing anyone's text.

"Exams based on past exams" has two readings and only one of them is ours to ship. The
platform holds 4,755 imported past-test items — Science Olympiad's own question text.
Republishing those as our exam content redistributes their expression, which is why
`open_sources.py` already records that the official rules and past exams "stay link-only".

The other reading is the one that actually helps a competitor, and it is fully available to
us: a past test's *structure* is fact, not expression. How many items, in what proportions of
recall / application / transfer, across which difficulty bands, over which topics — none of
that is protected, and it is what makes a practice test feel like the real event.
`blueprint.derive_blueprint` already computes exactly that profile from a pool.

So: derive the blueprint from the imported past-test pool, then fill it with **our own items**,
generated from claims grounded in cited public-domain sources and gated by the blind solver and
independent verifier. The student gets a test shaped like the real one, built entirely from
material we are permitted to publish.

Exams are created unpublished. Phase 0 decides when they may be served, and it will refuse
until their items have been accepted by a human — which is correct, and is the point.

    PYTHONPATH=. python -m scripts.build_launch_exams --event meteorology-b
    DATABASE_URL=<prod> PYTHONPATH=. python -m scripts.build_launch_exams --all --apply
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Exam, Question
from app.services import student_visibility as sv
from app.services.blueprint import derive_blueprint, select_for_blueprint

DEFAULT_SIZE = 30
LAUNCH_SLICE = [
    "rocks-and-minerals-b", "meteorology-b", "chemistry-lab-c", "remote-sensing-b",
    "circuit-lab-b", "water-quality-b", "dynamic-planet-b", "anatomy-and-physiology-b",
    "heredity-b", "disease-detectives-b", "machines-b",
]


def _past_test_pool(db, event: Event) -> list[Question]:
    """Imported past-test items — read for their shape, never copied into an exam."""
    return [q for q in db.scalars(select(Question).where(Question.event_id == event.id)).all()
            if (q.generation_provenance or {}).get("import_kind") == "past_test"]


def _our_items(db, event: Event) -> list[Question]:
    """Items we generated and that cleared every machine gate.

    Deliberately excludes anything imported: the blueprint may be learned from a past test, the
    content may not come from one.
    """
    out = []
    for question in db.scalars(select(Question).where(Question.event_id == event.id)).all():
        provenance = question.generation_provenance or {}
        if provenance.get("import_kind") == "past_test":
            continue
        report = question.validation_report or {}
        solver = report.get("independent_solver") or {}
        if report.get("passed") is not True:
            continue
        if not (solver.get("verdict") == "solver_agrees" or solver.get("passed") is True):
            continue
        out.append(question)
    return out


def build(event_slug: str, size: int, apply: bool) -> dict:
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == event_slug))
        if event is None:
            return {"event": event_slug, "outcome": "unknown event"}

        pool = _our_items(db, event)
        past = _past_test_pool(db, event)
        blueprint = derive_blueprint(past) if len(past) >= 10 else derive_blueprint(pool)
        shape = "past_test" if len(past) >= 10 else "our_own_pool"

        if len(pool) < 10:
            return {"event": event_slug, "outcome":
                    f"only {len(pool)} gate-passing item(s) of our own; need 10",
                    "our_items": len(pool), "past_pool": len(past)}

        target = min(size, len(pool))
        chosen = select_for_blueprint(pool, target, blueprint)
        existing = db.scalar(select(Exam).where(
            Exam.event_id == event.id, Exam.title.like("Practice Test%")))
        if not apply:
            return {"event": event_slug, "outcome":
                    f"would build a {len(chosen)}-item exam shaped by {shape}",
                    "our_items": len(pool), "past_pool": len(past)}
        if existing is not None:
            existing.question_ids = [q.id for q in chosen]
            exam = existing
        else:
            exam = Exam(
                event_id=event.id,
                title=f"Practice Test — {event.name}",
                question_ids=[q.id for q in chosen],
                # The blueprint is kept on the exam: it is the record of what the test's shape
                # was learned from, and the only thing taken from a released test.
                blueprint={**blueprint, "shape_source": shape},
                published=False,
                # Phase 0 decides serving. Left explicitly undecided rather than asserted here.
                disposition=sv.DISPOSITION_PENDING,
            )
            db.add(exam)
        db.commit()
        return {"event": event_slug, "outcome":
                f"exam of {len(chosen)} item(s), shaped by {shape}",
                "our_items": len(pool), "past_pool": len(past), "exam_id": exam.id}


def main() -> None:
    ap = argparse.ArgumentParser(description="Assemble practice exams for the launch slice")
    ap.add_argument("--event", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--size", type=int, default=DEFAULT_SIZE)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    events = LAUNCH_SLICE if args.all else [args.event] if args.event else []
    if not events:
        raise SystemExit("pass --event <slug> or --all")

    print("=" * 84)
    print(f"LAUNCH EXAMS [{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 84)
    stats: Counter[str] = Counter()
    for slug in events:
        row = build(slug, args.size, args.apply)
        stats["built" if "exam of" in row["outcome"] else "blocked"] += 1
        print(f"  {slug[:28]:30} ours={row.get('our_items', 0):<5} "
              f"past_pool={row.get('past_pool', 0):<5} {row['outcome']}")
    print("-" * 84)
    for key, value in sorted(stats.items()):
        print(f"  {key:10} {value}")
    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")
    else:
        print("\nexams are unpublished; Phase 0 refuses them until their items are accepted")
    print("=" * 84)


if __name__ == "__main__":
    main()
