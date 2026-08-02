"""Give every published lesson a concept, so finishing it records that it was finished.

`MasteryState` is keyed on `Concept`, and the only mastery evidence reading produces is this,
in the checkpoint route:

    if lesson.concept_id:
        mastery = ...

**450 of production's 474 published lessons have no `concept_id`.** A student can read one,
answer every checkpoint correctly, complete it — and the system records nothing it can act on.
The daily plan has no next thing to schedule, remediation has no concept to route to, and the
progress view has nothing to show. Phase 8's learn -> practice -> prove chain is severed for
95% of the catalog, in the same way and for the same reason it was severed for the pilot's
checkpoints: a field that some content path fills in and most do not.

This does not invent pedagogy. `build_course_structure` refuses to guess unit boundaries and
still should; a concept here is only the handle mastery is recorded against. Three strategies,
in descending order of how much they assume:

  1. **inherit** — the lesson is already linked to a skill that has a concept. Nothing is
     decided; an existing association is followed.
  2. **match** — the lesson's event already has a concept whose name matches the lesson's
     title or slug. Only an exact normalised match counts; near-matches are not attempted,
     because "close enough" is how a lesson ends up filed under the wrong idea.
  3. **create** — the event has **no concepts at all**, so one is created named for the
     lesson. Creating a concept where none exists groups nothing and asserts nothing; it makes
     mastery recordable without claiming the lesson shares an idea with any other.

Anything left over is **refused**, not guessed. An event that already has real concepts —
`ecology` has "Energy flow", "Population ecology" and two more — cannot take a lesson-named
fifth without asserting the lesson belongs to none of them, and mapping it onto one of the
four is a pedagogical decision this layer does not make. Those are reported for a human.

Every row written is tagged in the concept's description so the decision is auditable and
reversible. Nothing here publishes, unpublishes, or changes what a student can see.

    PYTHONPATH=. python -m scripts.link_lessons_to_concepts
    DATABASE_URL=<target> PYTHONPATH=. python -m scripts.link_lessons_to_concepts --apply
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Concept, Event, Lesson, LessonSkill, Skill

MARKER = "[auto-linked by link_lessons_to_concepts]"


def _norm(text: str) -> str:
    return " ".join(str(text or "").split()).lower()


def run(apply: bool, limit: int | None = None) -> dict:
    stats: Counter[str] = Counter()
    rows: list[dict] = []
    with SessionLocal() as db:
        lessons = [l for l in db.scalars(
            select(Lesson).where(Lesson.status == "published").order_by(Lesson.id)).all()
            if not l.concept_id]
        if limit:
            lessons = lessons[:limit]
        stats["lessons_needing_a_concept"] = len(lessons)

        skills = {s.id: s for s in db.scalars(select(Skill)).all()}
        links: dict[int, list[int]] = {}
        for link in db.scalars(select(LessonSkill)).all():
            links.setdefault(link.lesson_id, []).append(link.skill_id)
        by_event: dict[int, dict[str, Concept]] = {}
        for concept in db.scalars(select(Concept)).all():
            by_event.setdefault(concept.event_id, {}).setdefault(_norm(concept.name), concept)
        events = {e.id: e for e in db.scalars(select(Event)).all()}
        # Which events had concepts *before* this run. Testing `by_event` directly meant the
        # first lesson of a concept-less event got one created, and every later lesson of the
        # same event then saw that creation as pre-existing pedagogy and deferred to a human —
        # so an 8-lesson event linked 1 and refused 7. The question is whether a human ever
        # authored concepts here, and that answer cannot change while this loop runs.
        # Concepts this script created are not authored pedagogy and must not make a later run
        # — or a later lesson in the same event — defer to a human who never decided anything.
        # That is what MARKER exists for, and it is what makes this re-runnable.
        authored = {}
        for concept in db.scalars(select(Concept)).all():
            if MARKER not in (concept.description or ""):
                authored.setdefault(concept.event_id, []).append(concept)
        had_concepts = set(authored)

        for lesson in lessons:
            concept = None
            how = ""

            for skill_id in links.get(lesson.id, []):
                skill = skills.get(skill_id)
                if not (skill and skill.concept_id):
                    continue
                candidate = db.get(Concept, skill.concept_id)
                # A LessonSkill row can outlive a migration and point at another event's
                # concept. Following it would file the lesson under an idea nobody chose for
                # this event, and it would look deliberate in every report afterwards.
                if candidate is None or candidate.event_id != lesson.event_id:
                    stats["skill_concept_from_another_event"] += 1
                    continue
                concept, how = candidate, "inherit"
                break

            if concept is None:
                candidates = by_event.get(lesson.event_id, {})
                # an exact normalised match only; a fuzzy one files a lesson under a
                # neighbouring idea and looks correct in every report afterwards
                concept = candidates.get(_norm(lesson.title)) or candidates.get(
                    _norm(lesson.slug.replace("-", " ")))
                if concept is not None:
                    how = "match"

            if concept is None:
                # Creating a lesson-named concept where the event already has real ones is not
                # a neutral act: `ecology` has "Energy flow", "Population ecology" and two more,
                # and adding a fifth named after a lesson asserts that lesson belongs to none of
                # them. That is a pedagogical claim, and the plan is explicit that this layer
                # does not make those. Where an event has no concepts at all, creating one
                # groups nothing and asserts nothing — so only that case proceeds.
                if lesson.event_id in had_concepts:
                    stats["needs_human_mapping"] += 1
                    rows.append({
                        "event": events[lesson.event_id].slug if lesson.event_id in events else "?",
                        "lesson": lesson.title, "how": "needs_human",
                        "concept": f"{len(authored.get(lesson.event_id, []))} authored concept(s) to choose from",
                    })
                    continue
                how = "create"
                if apply:
                    concept = Concept(
                        event_id=lesson.event_id,
                        name=lesson.title[:255],
                        description=(f"{lesson.summary or ''} {MARKER}").strip()[:2000],
                    )
                    db.add(concept)
                    db.flush()
                    by_event.setdefault(lesson.event_id, {})[_norm(concept.name)] = concept

            stats[how] += 1
            rows.append({
                "event": events[lesson.event_id].slug if lesson.event_id in events else "?",
                "lesson": lesson.title, "how": how,
                "concept": concept.name if concept is not None else "(would create)",
            })
            if apply and concept is not None:
                lesson.concept_id = concept.id
                stats["linked"] += 1
        if apply:
            db.commit()
        else:
            db.rollback()
    return {"stats": stats, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Link published lessons to a mastery concept")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--show", type=int, default=15, help="how many rows to print")
    args = ap.parse_args()

    result = run(args.apply, args.limit)
    print("=" * 78)
    print(f"LESSON -> CONCEPT LINKING [{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 78)
    for row in result["rows"][:args.show]:
        print(f"  {row['how']:8} {row['event'][:22]:24} {row['lesson'][:30]:32} "
              f"-> {row['concept'][:24]}")
    if len(result["rows"]) > args.show:
        print(f"  … {len(result['rows']) - args.show} more")
    print("-" * 78)
    for key, value in sorted(result["stats"].items()):
        print(f"  {key:30} {value}")
    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")
    print("=" * 78)


if __name__ == "__main__":
    main()
