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
from app.models.entities import Event, Exam, ExamItem, Question, QuestionStatus
from app.services import student_visibility as sv
from app.services.blueprint import derive_blueprint, select_for_blueprint

DEFAULT_SIZE = 30
LAUNCH_SLICE = [
    "rocks-and-minerals-b", "meteorology-b", "chemistry-lab-c", "remote-sensing-b",
    "circuit-lab-b", "water-quality-b", "dynamic-planet-b", "anatomy-and-physiology-b",
    "heredity-b", "disease-detectives-b", "machines-b",
]


def _structure_only(blueprint: dict) -> dict:
    """Proportions and counts, never text lifted from an imported test.

    `derive_blueprint` carries `top_sections` — raw `generation_provenance.section` strings.
    When the blueprint is derived from the imported past-test pool those are *their* section
    headings, and persisting them on the exam put past-test text into a published record while
    the surrounding code claimed only numeric structure was kept. The counts are facts; the
    headings are not ours to store.
    """
    return {k: v for k, v in (blueprint or {}).items() if k != "top_sections"}


def _past_test_pool(db, event: Event) -> list[Question]:
    """Imported past-test items — read for their shape, never copied into an exam."""
    return [q for q in db.scalars(select(Question).where(Question.event_id == event.id)).all()
            if (q.generation_provenance or {}).get("import_kind") == "past_test"]


def item_clears_every_gate(question: Question) -> bool:
    """Every gate, checked independently — not `passed` plus one of them.

    The first version of this checked `validation_report.passed` and a solver flag, and the
    docstring claimed the item had "cleared every machine gate". It had not: the independent
    verifier and the grounding requirement were never consulted. `validation_report` is an
    untyped JSON blob written by several paths, so an item can carry `passed: true` beside an
    absent or failed verifier. The accompanying test built exactly that weak report, so it
    confirmed the relabelled gate rather than the real one — the precise failure this project
    keeps having, committed here by the person cataloguing it.

    Each component is now required on its own terms, and anything missing is a refusal rather
    than a pass.
    """
    provenance = question.generation_provenance or {}
    if provenance.get("import_kind") == "past_test":
        return False
    if question.status not in {QuestionStatus.MACHINE_VALIDATED.value,
                               QuestionStatus.PUBLISHED.value,
                               QuestionStatus.CALIBRATED.value}:
        return False

    report = question.validation_report or {}
    if report.get("passed") is not True:
        return False

    solver = report.get("independent_solver") or {}
    if not (solver.get("verdict") == "solver_agrees" or solver.get("passed") is True):
        return False

    verifier = report.get("independent_verifier")
    if not verifier:
        return False                        # never verified is not the same as verified clean
    if verifier.get("errors"):
        return False
    verdict = verifier.get("passed")
    if verdict is False:
        return False
    if not (verdict is True or isinstance(verdict, list)):
        return False                        # unrecognised shape: refuse rather than assume

    if report.get("factual_grounding") != "approved_claims":
        return False
    return bool(question.citations)


def _our_items(db, event: Event) -> list[Question]:
    """Our own items that clear every gate independently."""
    return [q for q in db.scalars(select(Question).where(Question.event_id == event.id)).all()
            if item_clears_every_gate(q)]


def build(event_slug: str, size: int, apply: bool) -> dict:
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == event_slug))
        if event is None:
            return {"event": event_slug, "outcome": "unknown event"}

        pool = _our_items(db, event)
        past = _past_test_pool(db, event)
        blueprint = _structure_only(
            derive_blueprint(past) if len(past) >= 10 else derive_blueprint(pool))
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
            # Replacing only `question_ids` left the exam's ExamItem snapshots — the rows
            # `start_exam` actually serves — untouched, and left `published`/`disposition`
            # alone. A previously published exam would have kept serving its old snapshots,
            # which for these events could hold imported past-test text, while its declared id
            # list pointed at new items. The snapshots are the exam; rebuild means rebuild.
            for stale in db.scalars(select(ExamItem).where(ExamItem.exam_id == existing.id)).all():
                db.delete(stale)
            existing.question_ids = [q.id for q in chosen]
            existing.blueprint = {**blueprint, "shape_source": shape}
            existing.published = False
            existing.disposition = sv.DISPOSITION_PENDING
            existing.published_at = None
            existing.published_by_user_id = None
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
        # "would build" is a dry run succeeding, not a refusal; counting it as
        # blocked made a clean dry run read like a failure.
        ok = "exam of" in row["outcome"] or "would build" in row["outcome"]
        stats["ready" if ok else "blocked"] += 1
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
