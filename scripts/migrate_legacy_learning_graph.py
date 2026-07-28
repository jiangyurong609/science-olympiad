"""Build the course/unit/skill migration graph without rewriting legacy content.

Dry-run by default. ``--apply`` creates sidecar course structures and migration
records while preserving lesson IDs, exam snapshots, attempts, responses, and
mastery rows.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    AssessmentBlueprint, ContentMigrationMap, Course, CourseUnit, CourseVersion,
    Event, EventSourceMap, Exam, Lesson, LessonSkill, Question, RawArtifact,
    Skill, Source, SourceSnapshot,
)


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return (slug[:120] or fallback).strip("-")


def _course_slug(event: Event) -> str:
    suffix = f"-{event.season}"
    return event.slug if event.slug.endswith(suffix) else f"{event.slug}{suffix}"


def _migration_state(entity, *, season: int | None = None) -> str:
    if isinstance(entity, Lesson):
        if season == 2027:
            return "needs_editor_and_sme_review"
        return "verified_legacy_identity_needs_content_audit"
    if isinstance(entity, Exam):
        return "immutable_snapshot_preserve"
    if isinstance(entity, Question):
        return "exam_snapshot_preserve_and_audit"
    if isinstance(entity, Source):
        if not entity.approved:
            return "rights_review_required"
        return "source_mapping_required"
    if isinstance(entity, RawArtifact):
        return "artifact_lineage_preserve"
    return "legacy_preserve_and_map"


def _record(
    db, legacy_type: str, legacy_id: int, state: str,
    *, target_type: str = "", target_id: int | None = None,
    redirect_path: str = "", notes: str = "",
):
    row = db.scalar(select(ContentMigrationMap).where(
        ContentMigrationMap.legacy_type == legacy_type,
        ContentMigrationMap.legacy_id == legacy_id,
    ))
    if row is None:
        row = ContentMigrationMap(
            legacy_type=legacy_type, legacy_id=legacy_id,
            target_type=target_type, target_id=target_id,
            migration_state=state, redirect_path=redirect_path,
            notes=notes,
        )
        db.add(row)
    else:
        row.target_type = target_type or row.target_type
        row.target_id = target_id if target_id is not None else row.target_id
        row.migration_state = state
        row.redirect_path = redirect_path or row.redirect_path
        row.notes = notes or row.notes
    return row


def migrate(db, apply: bool) -> dict:
    events = db.scalars(select(Event).order_by(Event.season, Event.id)).all()
    lessons = db.scalars(select(Lesson).order_by(Lesson.event_id, Lesson.sequence, Lesson.id)).all()
    exams = db.scalars(select(Exam).order_by(Exam.event_id, Exam.id)).all()
    questions = db.scalars(select(Question).order_by(Question.id)).all()
    sources = db.scalars(select(Source).order_by(Source.id)).all()
    artifacts = db.scalars(select(RawArtifact).order_by(RawArtifact.id)).all()
    snapshots = {row.id: row for row in db.scalars(select(SourceSnapshot)).all()}
    event_maps = db.scalars(select(EventSourceMap)).all()
    source_event_ids: dict[int, set[int]] = defaultdict(set)
    for mapping in event_maps:
        source_event_ids[mapping.source_id].add(mapping.event_id)
    lessons_by_event: dict[int, list[Lesson]] = defaultdict(list)
    exams_by_event: dict[int, list[Exam]] = defaultdict(list)
    for lesson in lessons:
        lessons_by_event[lesson.event_id].append(lesson)
    for exam in exams:
        exams_by_event[exam.event_id].append(exam)

    report = {
        "mode": "apply" if apply else "dry_run",
        "events": len(events),
        "courses": len(events) if not apply else 0,
        "units": len(events) if not apply else 0,
        "skills": len(lessons) if not apply else 0,
        "lesson_links": len(lessons) if not apply else 0,
        "assessment_blueprints": (
            sum(bool(rows) for rows in exams_by_event.values()) if not apply else 0
        ),
        "migration_records": {
            "event": len(events), "lesson": len(lessons), "exam": len(exams),
            "question": len(questions), "source": len(sources), "raw_artifact": len(artifacts),
        },
        "student_history_rewritten": False,
        "exam_snapshots_rewritten": False,
    }
    if not apply:
        return report

    for event in events:
        course = db.scalar(select(Course).where(Course.event_id == event.id))
        if course is None:
            course = Course(
                event_id=event.id,
                slug=_course_slug(event),
                title=event.name,
                summary=event.topic_focus or event.description or f"{event.name} course archive",
                status="published" if event.season == 2026 else "review_required",
                current_version=1,
            )
            db.add(course)
            db.flush()
            db.add(CourseVersion(
                course_id=course.id, version=1,
                objectives=[],
                release_notes="Legacy migration shell; instructional review remains required.",
                review_status="legacy_preserved" if event.season == 2026 else "review_required",
            ))
        report["courses"] += 1
        redirect = f"/courses/{event.season}/{event.slug}"
        _record(
            db, "event", event.id,
            "legacy_preserve_and_map" if event.season == 2026 else "current_course_review_required",
            target_type="course", target_id=course.id, redirect_path=redirect,
        )

        unit = db.scalar(select(CourseUnit).where(
            CourseUnit.course_id == course.id,
            CourseUnit.slug == "legacy-learning-path",
        ))
        if unit is None:
            unit = CourseUnit(
                course_id=course.id,
                slug="legacy-learning-path",
                title="Legacy Learning Path",
                summary="Existing lessons preserved during the course-model migration.",
                sequence=10,
                status="published" if event.season == 2026 else "review_required",
                objectives=[],
                prerequisites=[],
            )
            db.add(unit)
            db.flush()
        report["units"] += 1

        used_slugs: set[str] = set(
            db.scalars(select(Skill.slug).where(Skill.course_id == course.id)).all()
        )
        for position, lesson in enumerate(lessons_by_event[event.id], start=1):
            # LessonSkill is the stable mapping identity. Most imported legacy
            # lessons have no concept_id, so matching only on concepts would
            # create a new skill every time the migration is rerun.
            skill = db.scalar(
                select(Skill)
                .join(LessonSkill, LessonSkill.skill_id == Skill.id)
                .where(
                    Skill.course_id == course.id,
                    LessonSkill.lesson_id == lesson.id,
                )
            )
            if skill is None and lesson.concept_id:
                skill = db.scalar(select(Skill).where(
                    Skill.course_id == course.id,
                    Skill.concept_id == lesson.concept_id,
                ))
            if skill is None:
                base = _slug(lesson.title, f"lesson-{lesson.id}")
                candidate = base
                suffix = 2
                while candidate in used_slugs:
                    candidate = f"{base[:110]}-{suffix}"
                    suffix += 1
                used_slugs.add(candidate)
                skill = Skill(
                    course_id=course.id, unit_id=unit.id,
                    concept_id=lesson.concept_id,
                    slug=candidate, name=lesson.title,
                    description=lesson.summary,
                    sequence=position * 10, weight=1.0,
                    status="published" if event.season == 2026 else "review_required",
                    prerequisites=[],
                )
                db.add(skill)
                db.flush()
            report["skills"] += 1
            link = db.scalar(select(LessonSkill).where(
                LessonSkill.lesson_id == lesson.id,
                LessonSkill.skill_id == skill.id,
            ))
            if link is None:
                db.add(LessonSkill(
                    lesson_id=lesson.id, skill_id=skill.id,
                    is_primary=True, weight=1.0,
                ))
            report["lesson_links"] += 1
            _record(
                db, "lesson", lesson.id, _migration_state(lesson, season=event.season),
                target_type="skill", target_id=skill.id,
                redirect_path=f"{redirect}/lesson/{lesson.slug}",
                notes="Legacy lesson ID and progress relationship preserved.",
            )

        event_exams = exams_by_event[event.id]
        if event_exams:
            blueprint = db.scalar(select(AssessmentBlueprint).where(
                AssessmentBlueprint.course_id == course.id,
                AssessmentBlueprint.unit_id.is_(None),
                AssessmentBlueprint.assessment_type == "historical_exam_catalog",
                AssessmentBlueprint.version == 1,
            ))
            if blueprint is None:
                blueprint = AssessmentBlueprint(
                    course_id=course.id, unit_id=None,
                    assessment_type="historical_exam_catalog", version=1,
                    title="Past Tests & Reviewed Practice",
                    specification={
                        "exam_ids": [exam.id for exam in event_exams],
                        "immutable_snapshots": True,
                        "student_history_preserved": True,
                    },
                    status="published" if event.season == 2026 else "review_required",
                )
                db.add(blueprint)
            report["assessment_blueprints"] += 1
        for exam in event_exams:
            _record(
                db, "exam", exam.id, _migration_state(exam),
                target_type="course", target_id=course.id,
                redirect_path=f"{redirect}/exam/{exam.id}",
                notes="ExamItem snapshots, attempts, and responses remain unchanged.",
            )

    event_by_id = {event.id: event for event in events}
    for question in questions:
        event = event_by_id.get(question.event_id)
        _record(
            db, "question", question.id, _migration_state(question),
            target_type="course" if event else "",
            target_id=(
                db.scalar(select(Course.id).where(Course.event_id == event.id))
                if event else None
            ),
            notes="Question content and exam snapshots remain unchanged; review/calibration required.",
        )
    for source in sources:
        event_ids = sorted(source_event_ids[source.id])
        _record(
            db, "source", source.id, _migration_state(source),
            notes=f"Mapped event IDs: {event_ids}" if event_ids else "Unmapped source; editorial disposition required.",
        )
    for artifact in artifacts:
        snapshot = snapshots.get(artifact.snapshot_id)
        _record(
            db, "raw_artifact", artifact.id, _migration_state(artifact),
            target_type="source", target_id=snapshot.source_id if snapshot else None,
            notes="Raw artifact retained; hash and snapshot lineage unchanged.",
        )
    db.commit()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        report = migrate(db, apply=args.apply)
        if not args.apply:
            db.rollback()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
