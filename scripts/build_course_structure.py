"""Phase 3 (structural half) — give a course real units, skill→concept links, and quizzes.

The pilot's audit blamed thin question coverage on generation. The cause was structural: all
eight skills sat in a single unit named "Legacy Learning Path", and **not one skill had a
`concept_id`**. `audit_course` reads a skill's items via `questions_by_concept[skill.concept_id]`,
so with a null concept every skill reported zero questions no matter how many were generated —
the 33 items from the Phase 2 run were unreachable from the course. Grouping skills into units
of 2–3 and giving each a concept fixes the measurement and the generation target at once.

Unit boundaries come from the course's own subject matter and are declared below rather than
inferred, because a wrong grouping is a pedagogical error a heuristic cannot catch.

    PYTHONPATH=. python -m scripts.build_course_structure --event rocks-and-minerals-b [--apply]
"""
from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.entities import (
    AssessmentBlueprint, Concept, Course, CourseUnit, Event, Skill,
)

# skill-slug prefix → unit. Prefixes are matched against the existing skill slugs so the
# grouping survives slug edits that only touch the tail.
UNIT_PLANS: dict[str, list[dict]] = {
    "rocks-and-minerals-b": [
        {
            "slug": "minerals-identification-and-properties",
            "title": "Minerals: Identification and Properties",
            "summary": "Observe, test, and name minerals using properties that repeat.",
            "skills": ["mineral-identification-foundations",
                       "crystal-chemistry-habits",
                       "mineral-groups-uses-hazards"],
        },
        {
            "slug": "igneous-systems",
            "title": "Igneous Systems",
            "summary": "From silicate structures and Bowen's series to magma, eruption, and landform.",
            "skills": ["silicate-structures-bowen",
                       "igneous-rocks-magma-processes",
                       "tectonics-magma-origins"],
        },
        {
            "slug": "sedimentary-and-metamorphic-systems",
            "title": "Sedimentary and Metamorphic Systems",
            "summary": "Surface processes, burial, and the pressure-temperature record in rock.",
            "skills": ["sedimentary-rocks-environments",
                       "metamorphism-facies"],
        },
    ],
}

QUIZ_SPEC_ITEMS_PER_SKILL = 4


def _match(skill: Skill, prefix: str) -> bool:
    return skill.slug.startswith(prefix)


def build(db: Session, event: Event, apply: bool) -> dict:
    course = db.scalar(select(Course).where(Course.event_id == event.id))
    if not course:
        raise SystemExit(f"{event.slug} has no course")
    plan = UNIT_PLANS.get(event.slug)
    if not plan:
        raise SystemExit(
            f"no unit plan declared for {event.slug!r}. Add one to UNIT_PLANS — unit "
            "boundaries are a pedagogical decision, not something to infer."
        )

    skills = db.scalars(select(Skill).where(
        Skill.course_id == course.id, Skill.status != "withdrawn",
    ).order_by(Skill.sequence)).all()
    by_slug = {s.slug: s for s in skills}
    report = {"units": [], "concepts_created": 0, "skills_moved": 0,
              "quizzes_created": 0, "unplaced": []}

    placed: set[int] = set()
    for index, spec in enumerate(plan, start=1):
        members = [s for prefix in spec["skills"] for s in skills if _match(s, prefix)]
        # a prefix matching two skills would silently overfill a unit
        seen, deduped = set(), []
        for skill in members:
            if skill.id not in seen:
                seen.add(skill.id)
                deduped.append(skill)
        members = deduped
        if not 2 <= len(members) <= 3:
            raise SystemExit(
                f"unit {spec['slug']!r} resolved to {len(members)} skills "
                f"({[s.slug for s in members]}); the rubric requires 2–3. Fix UNIT_PLANS."
            )

        unit = db.scalar(select(CourseUnit).where(
            CourseUnit.course_id == course.id, CourseUnit.slug == spec["slug"]))
        if unit is None and apply:
            unit = CourseUnit(course_id=course.id, slug=spec["slug"], title=spec["title"],
                              summary=spec["summary"], sequence=index, status="published")
            db.add(unit)
            db.flush()
        elif unit is not None and apply:
            unit.title, unit.summary = spec["title"], spec["summary"]
            unit.sequence, unit.status = index, "published"

        for order, skill in enumerate(members, start=1):
            placed.add(skill.id)
            if skill.concept_id is None:
                # one concept per skill: generation and the audit both key items by concept,
                # so a skill without one can neither receive nor report questions
                concept = db.scalar(select(Concept).where(
                    Concept.event_id == event.id, Concept.name == skill.name))
                if concept is None:
                    report["concepts_created"] += 1
                    if apply:
                        concept = Concept(event_id=event.id, name=skill.name,
                                          description=skill.description or "")
                        db.add(concept)
                        db.flush()
                if apply and concept is not None:
                    skill.concept_id = concept.id
            if apply and unit is not None:
                if skill.unit_id != unit.id:
                    report["skills_moved"] += 1
                skill.unit_id = unit.id
                skill.sequence = index * 10 + order
                if skill.status == "draft":
                    skill.status = "published"

        if apply and unit is not None:
            quiz = db.scalar(select(AssessmentBlueprint).where(
                AssessmentBlueprint.course_id == course.id,
                AssessmentBlueprint.unit_id == unit.id,
                AssessmentBlueprint.assessment_type == "unit_quiz"))
            if quiz is None:
                report["quizzes_created"] += 1
                db.add(AssessmentBlueprint(
                    course_id=course.id, unit_id=unit.id, assessment_type="unit_quiz",
                    title=f"{spec['title']} — Unit Quiz",
                    specification={
                        "skills": [{"skill_slug": s.slug, "items": QUIZ_SPEC_ITEMS_PER_SKILL,
                                    "cognitive_mix": {"recall": 1, "application": 2,
                                                      "transfer": 1}}
                                   for s in members],
                        "total_items": QUIZ_SPEC_ITEMS_PER_SKILL * len(members),
                    },
                    # the blueprint says what the quiz must contain; it is only publishable
                    # once items exist to satisfy it, which is Phase 3's review work
                    status="draft",
                ))
        report["units"].append({"slug": spec["slug"], "skills": [s.slug for s in members]})

    report["unplaced"] = [s.slug for s in skills if s.id not in placed]
    if report["unplaced"]:
        raise SystemExit(
            f"{len(report['unplaced'])} skills are in no unit: {report['unplaced']}. "
            "Every skill must be placed or explicitly withdrawn."
        )

    # the catch-all unit only existed to hold skills that now live somewhere real.
    # The reassignments above must reach the database before "is this unit empty?" is asked,
    # or the first run sees the old unit_ids, leaves the unit standing, and only a second
    # run withdraws it.
    if apply:
        db.flush()
    for unit in db.scalars(select(CourseUnit).where(
        CourseUnit.course_id == course.id, CourseUnit.status != "withdrawn",
    )).all():
        if unit.slug not in {spec["slug"] for spec in plan}:
            remaining = db.scalars(select(Skill).where(
                Skill.unit_id == unit.id, Skill.status != "withdrawn")).all()
            if apply and not remaining:
                unit.status = "withdrawn"
                report.setdefault("units_withdrawn", []).append(unit.slug)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Build course units, concepts, and quizzes")
    ap.add_argument("--event", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from app.services.course_quality import audit_course

    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == args.event))
        if not event:
            raise SystemExit(f"unknown event {args.event!r}")
        course = db.scalar(select(Course).where(Course.event_id == event.id))
        before = audit_course(db, course.id)["counts"]["blockers"]

        report = build(db, event, args.apply)
        print("=" * 72)
        print(f"COURSE STRUCTURE — {args.event} [{'APPLY' if args.apply else 'DRY RUN'}]")
        print("=" * 72)
        for unit in report["units"]:
            print(f"  {unit['slug']}")
            for slug in unit["skills"]:
                print(f"      - {slug}")
        print(f"\nconcepts created : {report['concepts_created']}")
        print(f"skills moved     : {report['skills_moved']}")
        print(f"unit quizzes     : {report['quizzes_created']}")
        if report.get("units_withdrawn"):
            print(f"units withdrawn  : {report['units_withdrawn']}")

        if args.apply:
            db.commit()
            after = audit_course(db, course.id)
            print(f"\nblockers: {before} -> {after['counts']['blockers']}")
            for code, count in sorted(after["blocker_counts"].items(), key=lambda kv: -kv[1]):
                print(f"   {code:28} {count}")
        else:
            db.rollback()
            print("\ndry run — nothing written. re-run with --apply")


if __name__ == "__main__":
    main()
