"""Phase 6 sizing — how much of the catalog has the defects the pilot had.

Fixing the pilot answered "can this be fixed". This answers "how much of it is there", which
is the number that decides whether Phase 6 is a week or a quarter. It exists because the
pilot's worst finding was not visible from any screen: no skill had a `concept_id`, and since
`audit_course` reads a skill's items through it, every skill reported zero questions however
many existed. A defect that silent is worth counting everywhere before planning around it.

Nothing is written. This only measures.

    PYTHONPATH=. python -m scripts.audit_catalog_structure
    PYTHONPATH=. python -m scripts.audit_catalog_structure --json docs/history/structure.json
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    AssessmentBlueprint, Course, CourseUnit, Event, Lesson, LessonVersion, Skill,
)
from scripts.phase3_mechanical import MAX_MINUTES, MIN_MINUTES, estimate_minutes

MAX_SKILLS_PER_UNIT = 3


def audit(db) -> dict:
    events = db.scalars(select(Event).where(Event.active.is_(True))
                        .order_by(Event.slug)).all()
    if not events:
        raise SystemExit("FAIL: no active events. An empty population is not a clean bill.")

    rows, lessons_total, lessons_over, lessons_under = [], 0, 0, 0
    for event in events:
        course = db.scalar(select(Course).where(Course.event_id == event.id))
        skills = db.scalars(select(Skill).where(
            Skill.course_id == course.id, Skill.status != "withdrawn",
        )).all() if course else []
        units = db.scalars(select(CourseUnit).where(
            CourseUnit.course_id == course.id, CourseUnit.status != "withdrawn",
        )).all() if course else []

        problems = []
        if course is None:
            problems.append("no_course")
        elif not skills:
            problems.append("course_without_skills")
        else:
            if any(skill.concept_id is None for skill in skills):
                problems.append("skills_without_a_concept")
            oversized = [u for u in units
                         if len([s for s in skills if s.unit_id == u.id]) > MAX_SKILLS_PER_UNIT]
            if oversized:
                problems.append("unit_holding_too_many_skills")
            quizzes = db.scalars(select(AssessmentBlueprint).where(
                AssessmentBlueprint.course_id == course.id,
                AssessmentBlueprint.assessment_type == "unit_quiz",
            )).all()
            if not quizzes:
                problems.append("no_unit_quiz_blueprint")

        over = under = counted = 0
        for lesson in db.scalars(select(Lesson).where(
            Lesson.event_id == event.id, Lesson.status != "withdrawn",
        )).all():
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version))
            if version is None:
                continue
            counted += 1
            minutes = estimate_minutes(version)
            if minutes > MAX_MINUTES:
                over += 1
            elif minutes < MIN_MINUTES:
                under += 1
        lessons_total += counted
        lessons_over += over
        lessons_under += under
        if over:
            problems.append("lessons_over_the_time_target")

        rows.append({
            "event": event.slug, "skills": len(skills), "units": len(units),
            "lessons": counted, "lessons_over": over, "lessons_under": under,
            "problems": problems,
        })

    def count(code: str) -> int:
        return sum(1 for row in rows if code in row["problems"])

    return {
        "events": len(rows),
        "totals": {
            "no_course": count("no_course"),
            "course_without_skills": count("course_without_skills"),
            "skills_without_a_concept": count("skills_without_a_concept"),
            "unit_holding_too_many_skills": count("unit_holding_too_many_skills"),
            "no_unit_quiz_blueprint": count("no_unit_quiz_blueprint"),
            "lessons": lessons_total,
            "lessons_over_target": lessons_over,
            "lessons_under_target": lessons_under,
            "clean_events": sum(1 for row in rows if not row["problems"]),
        },
        "by_event": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Catalog structural defect census")
    ap.add_argument("--json", dest="json_path", default=None)
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    with SessionLocal() as db:
        result = audit(db)
    t = result["totals"]
    pct = (100 * t["lessons_over_target"] / t["lessons"]) if t["lessons"] else 0

    print("=" * 76)
    print("CATALOG STRUCTURE CENSUS (Phase 6 sizing)")
    print("=" * 76)
    print(f"live events                            : {result['events']}")
    print(f"  with no course                       : {t['no_course']}")
    print(f"  course carrying no skills            : {t['course_without_skills']}")
    print(f"  skills with no concept (items unseen): {t['skills_without_a_concept']}")
    print(f"  a unit holding >{MAX_SKILLS_PER_UNIT} skills            : "
          f"{t['unit_holding_too_many_skills']}")
    print(f"  no unit-quiz blueprint               : {t['no_unit_quiz_blueprint']}")
    print(f"  free of all of the above             : {t['clean_events']}")
    print("-" * 76)
    print(f"lessons measured                       : {t['lessons']}")
    print(f"  over the {MAX_MINUTES}-minute target             : "
          f"{t['lessons_over_target']} ({pct:.0f}%)")
    print(f"  under the {MIN_MINUTES}-minute floor              : {t['lessons_under_target']}")
    print("-" * 76)
    worst = sorted(result["by_event"], key=lambda r: -len(r["problems"]))[:args.limit]
    print("most affected events:")
    for row in worst:
        print(f"  {row['event'][:30]:32} lessons {row['lessons']:3} "
              f"(over {row['lessons_over']:3})  {', '.join(row['problems'][:3])}")
    print("=" * 76)

    if args.json_path:
        with open(args.json_path, "w") as fh:
            json.dump(result, fh, indent=2)
        print(f"wrote {args.json_path}")


if __name__ == "__main__":
    main()
