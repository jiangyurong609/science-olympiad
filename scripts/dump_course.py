"""Print a course as readable text, for a human or an expert reviewer to read end to end.

A course lives across four tables and its lesson bodies are JSON block lists, so "read the
Botany course" is otherwise a scripting exercise before it is a reading exercise. This prints
the whole thing: units in order, lessons in order, every block's prose, every checkpoint with
its choices and keyed answer, and the citations behind each lesson.

    DATABASE_URL=... python -m scripts.dump_course --event botany-b-2027
    DATABASE_URL=... python -m scripts.dump_course --event botany-b-2027 --outline
    DATABASE_URL=... python -m scripts.dump_course --event botany-b-2027 --lesson pigments
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Course, CourseUnit, Event, Lesson, LessonVersion, Source,
)

PROSE_KEYS = ("text", "markdown", "body", "content", "summary")


def _prose(block: dict) -> str:
    for key in PROSE_KEYS:
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _render_block(block: dict) -> str:
    kind = block.get("type", "?")
    if kind == "checkpoint":
        lines = [f"  [CHECKPOINT] {block.get('heading') or ''}".rstrip(),
                 f"    Q: {block.get('question','')}"]
        choices = block.get("choices") or []
        correct = block.get("correct_index")
        for index, choice in enumerate(choices):
            mark = " <== keyed" if index == correct else ""
            lines.append(f"    {chr(65 + index)}. {choice}{mark}")
        if block.get("answer"):
            lines.append(f"    A: {block['answer']}")
        if block.get("explanation"):
            lines.append(f"    why: {block['explanation']}")
        level = block.get("cognitive_level")
        if level:
            lines.append(f"    cognitive_level: {level}")
        return "\n".join(lines)
    prose = _prose(block)
    if not prose:
        return f"  [{kind}] (no prose)"
    heading = block.get("heading")
    head = f"  [{kind}] {heading}".rstrip() if heading else f"  [{kind}]"
    return f"{head}\n    " + prose.replace("\n", "\n    ")


def dump(db, slug: str, *, outline: bool, only: str | None) -> None:
    event = db.scalar(select(Event).where(Event.slug == slug))
    if event is None:
        raise SystemExit(f"no event {slug}")
    course = db.scalar(select(Course).where(Course.event_id == event.id))
    print(f"=== {event.name} ({event.slug}) season={event.season} "
          f"status={event.season_status}")
    if course is not None:
        print(f"course: {course.title}")
        if course.summary:
            print(f"summary: {course.summary}")
    units = db.scalars(select(CourseUnit).where(
        CourseUnit.course_id == (course.id if course else -1))
        .order_by(CourseUnit.sequence)).all()
    lessons = db.scalars(select(Lesson).where(Lesson.event_id == event.id)
                         .order_by(Lesson.sequence)).all()
    by_unit: dict[int | None, list[Lesson]] = {}
    for lesson in lessons:
        concept = db.get(Concept, lesson.concept_id) if lesson.concept_id else None
        unit_id = getattr(concept, "course_unit_id", None) if concept else None
        by_unit.setdefault(unit_id, []).append(lesson)

    print(f"\n{len(units)} unit(s), {len(lessons)} lesson(s)\n")
    ordered = [(u.id, u.title, u.summary) for u in units] + [(None, "(no unit)", "")]
    for unit_id, title, summary in ordered:
        group = by_unit.get(unit_id) or []
        if not group:
            continue
        print(f"\n{'=' * 88}\nUNIT: {title}")
        if summary:
            print(f"  {summary}")
        for lesson in group:
            if only and only not in (lesson.slug or ""):
                continue
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id)
                .order_by(LessonVersion.version.desc()))
            flag = f"status={lesson.status} disposition={lesson.disposition or '-'}"
            review = version.review_status if version else "-"
            print(f"\n  ---- {lesson.slug}  [{flag} review={review}]")
            print(f"       {lesson.title}")
            if lesson.summary:
                print(f"       {lesson.summary}")
            if outline or version is None:
                continue
            for block in (version.content or []):
                if isinstance(block, dict):
                    print(_render_block(block))
            cites = version.citations or []
            if cites:
                names = []
                for cite in cites[:12]:
                    source = db.get(Source, cite.get("source_id")) if cite.get("source_id") else None
                    names.append((source.url if source else str(cite))[:96])
                print("  [citations] " + "\n              ".join(names))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--outline", action="store_true",
                        help="unit and lesson titles only")
    parser.add_argument("--lesson", help="only lessons whose slug contains this")
    args = parser.parse_args()
    with SessionLocal() as db:
        dump(db, args.event, outline=args.outline, only=args.lesson)


if __name__ == "__main__":
    main()
