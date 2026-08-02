"""Phase 8 — the placement diagnostic, sequenced last because it depends on everything else.

A placement diagnostic asks a student a short set of questions and decides where to start them.
It is worth building only once the things it writes into are real: concepts to place against
(Phase 6/8 — 450 lessons had none until this session), items that a human has accepted
(Phase 0), and calibration data to choose items by (Phase 3).

Three refusals define it, and each one is a Phase 0 rule restated rather than a new invention:

  * **only student-ready items.** `student_visibility.item_is_student_ready` is the single rule
    for what a student may be scored on, and a diagnostic scores. Sampling `draft` items here
    would be the mock-exam sampler's original defect, rebuilt in a new place.
  * **only concepts a student can then act on.** Placing someone into a concept with no
    student-visible lesson tells them where they stand and gives them nowhere to go. Those
    concepts are excluded and counted, so the gap is visible rather than silently absorbed.
  * **it refuses to run rather than run thin.** A diagnostic drawn from two items across one
    concept is not a weak diagnostic, it is a misleading one — it reports a placement with the
    authority of a measurement it did not make.

What it writes is deliberately weak: `MasteryState.mastery_probability` seeded from the
proportion correct, with `evidence_count` set to the number of items actually asked, and it
**never overwrites mastery a student earned by doing the work**. A diagnostic is the least
reliable evidence in the system; it may fill a vacuum, not overrule practice.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Concept, Event, Lesson, LessonVersion, MasteryState, Question, User,
)
from app.services import student_visibility as sv

MIN_CONCEPTS = 2          # below this it is a quiz about one idea, not a placement
MIN_ITEMS = 4             # below this the proportion correct is noise
ITEMS_PER_CONCEPT = 2
MAX_ITEMS = 12

# What a diagnostic may claim. It is evidence, but the weakest kind the system has.
DIAGNOSTIC_CONFIDENCE = 0.6
DIAGNOSTIC_FLOOR, DIAGNOSTIC_CEILING = 0.15, 0.75


class PlacementError(ValueError):
    pass


def _placeable_concepts(db: Session, event: Event) -> tuple[list[Concept], int]:
    """Concepts with at least one lesson a student could actually be sent to.

    A placement into a concept with nothing readable behind it is a dead end, so those are
    excluded — and counted, because the count is the interesting number.
    """
    concepts = db.scalars(select(Concept).where(Concept.event_id == event.id)).all()
    if not concepts:
        return [], 0
    lessons = db.scalars(select(Lesson).where(
        Lesson.event_id == event.id, Lesson.status == "published",
        Lesson.concept_id.in_([c.id for c in concepts]))).all()
    versions = {v.lesson_id: v for v in db.scalars(select(LessonVersion).where(
        LessonVersion.lesson_id.in_([l.id for l in lessons] or [-1]))).all()}
    probe = User(id=-1, email="placement@invalid", full_name="Placement", role="student")
    reachable = set()
    for lesson in lessons:
        version = versions.get(lesson.id)
        if version is not None and sv.lesson_is_student_visible(db, probe, lesson, version):
            reachable.add(lesson.concept_id)
    placeable = [c for c in concepts if c.id in reachable]
    return placeable, len(concepts) - len(placeable)


def build_diagnostic(db: Session, event_slug: str) -> dict:
    """The items to ask, or a refusal saying exactly what was missing."""
    event = db.scalar(select(Event).where(Event.slug == event_slug))
    if event is None:
        raise PlacementError(f"unknown event {event_slug!r}")

    concepts, unreachable = _placeable_concepts(db, event)
    if len(concepts) < MIN_CONCEPTS:
        raise PlacementError(
            f"{event_slug} has {len(concepts)} concept(s) a student could be placed into "
            f"({unreachable} more have no student-visible lesson). A placement needs at least "
            f"{MIN_CONCEPTS} to say anything."
        )

    items, by_concept = [], {}
    for concept in sorted(concepts, key=lambda c: c.id):
        candidates = [
            q for q in db.scalars(select(Question).where(
                Question.concept_id == concept.id).order_by(Question.id)).all()
            # the single rule for what a student may be scored on; a diagnostic scores
            if sv.item_is_student_ready(q)
        ]
        chosen = candidates[:ITEMS_PER_CONCEPT]
        if chosen:
            by_concept[concept.id] = [q.id for q in chosen]
            items.extend(chosen)
        if len(items) >= MAX_ITEMS:
            break

    if len(items) < MIN_ITEMS or len(by_concept) < MIN_CONCEPTS:
        raise PlacementError(
            f"{event_slug} yields {len(items)} reviewed item(s) across {len(by_concept)} "
            f"concept(s); a placement needs {MIN_ITEMS} across {MIN_CONCEPTS}. Reporting a "
            f"placement from less would claim a measurement it did not make."
        )

    return {
        "event": event_slug,
        "concepts_placeable": len(concepts),
        "concepts_without_a_visible_lesson": unreachable,
        "items": [{"id": q.id, "concept_id": q.concept_id, "stem": q.stem,
                   "choices": list(q.choices or [])} for q in items],
        "items_by_concept": by_concept,
    }


def record_placement(db: Session, user: User, event_slug: str,
                     responses: dict[int, int]) -> dict:
    """Seed mastery from a diagnostic, without ever overruling work the student did."""
    diagnostic = build_diagnostic(db, event_slug)
    asked_ids = {i["id"] for i in diagnostic["items"]}
    # `build_diagnostic` refuses below MIN_ITEMS/MIN_CONCEPTS, but nothing re-checked what was
    # actually *answered*. A single response was enough to seed a concept, which reintroduces
    # the exact "placement from too little evidence" this refuses to do at build time.
    answered = {qid for qid in responses if qid in asked_ids}
    if len(answered) < MIN_ITEMS:
        raise PlacementError(
            f"{len(answered)} item(s) answered; a placement needs {MIN_ITEMS}. Scoring fewer "
            f"would report a placement the responses cannot support."
        )
    questions = {q.id: q for q in db.scalars(select(Question).where(
        Question.id.in_([i["id"] for i in diagnostic["items"]] or [-1]))).all()}

    seeded, skipped, per_concept = 0, 0, {}
    for concept_id, question_ids in diagnostic["items_by_concept"].items():
        asked = [qid for qid in question_ids if qid in responses]
        if not asked:
            continue
        correct = 0
        for qid in asked:
            question = questions.get(qid)
            key = (question.answer_spec or {}).get("correct_index") if question else None
            if key is not None and responses.get(qid) == key:
                correct += 1
        share = correct / len(asked)
        per_concept[concept_id] = {"asked": len(asked), "correct": correct}

        # Locked for the read-check-write below. Without it, a practice completion landing
        # between the `evidence_count` check and this write is silently overwritten — the
        # diagnostic would reset earned evidence to zero and revise the probability down.
        existing = db.scalar(select(MasteryState).where(
            MasteryState.user_id == user.id,
            MasteryState.concept_id == concept_id).with_for_update())
        if existing is not None and existing.evidence_count > 0:
            # they have already shown what they can do; a diagnostic does not get to revise it
            skipped += 1
            continue
        probability = min(DIAGNOSTIC_CEILING,
                          max(DIAGNOSTIC_FLOOR, share * DIAGNOSTIC_CONFIDENCE))
        state = existing or MasteryState(user_id=user.id, concept_id=concept_id)
        state.mastery_probability = probability
        state.evidence_count = 0          # a diagnostic is not practice; it seeds, not counts
        state.misconception_risk = round(1.0 - share, 3)
        state.last_practiced_at = datetime.now(timezone.utc)
        db.add(state)
        seeded += 1
    db.flush()
    return {
        "event": event_slug,
        "concepts_seeded": seeded,
        "concepts_left_alone_because_the_student_had_evidence": skipped,
        "per_concept": per_concept,
    }
