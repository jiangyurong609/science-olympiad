"""Does each lesson and item actually teach the event it is filed under?

Nothing has ever checked this. Content is generated per event, so the *filing* is correct by
construction — but the content itself is model-written, and a generator asked for "Water
Quality" can drift into general ecology, or produce eight lessons that are really the same
lesson. Neither shows up in any existing gate: grounding checks that a claim is supported,
the solver checks that a key is reproducible, and both are perfectly happy with an on-topic
sentence about the wrong topic.

Two failures are worth separating:

  * **drift** — the lesson is about something else. Measured against the event's own
    vocabulary, drawn from its name, its skills and its concepts, not from a hand-written
    keyword list that would just encode my guess about the subject.
  * **redundancy** — several lessons in an event are near-duplicates of each other, which is
    how an eight-lesson course ends up teaching two things. Measured as pairwise vocabulary
    overlap between lessons of the same event.

This is a cheap screen, deliberately. It is meant to find the handful worth a human's
attention among 474, not to grade prose. Anything it flags should be read, not deleted.

    PYTHONPATH=. python -m scripts.audit_topical_fit
    DATABASE_URL=<prod> PYTHONPATH=. python -m scripts.audit_topical_fit --event water-quality-b
"""
from __future__ import annotations

import argparse
import re
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Course, Event, Lesson, LessonVersion, Question, Skill,
)
from app.services.course_quality import block_text

STOP = {
    "the", "and", "for", "that", "this", "with", "from", "which", "their", "these", "those",
    "when", "what", "where", "have", "has", "had", "are", "was", "were", "will", "would",
    "can", "could", "should", "must", "not", "but", "its", "it's", "you", "your", "they",
    "them", "than", "then", "into", "onto", "over", "under", "about", "more", "most", "some",
    "each", "both", "also", "such", "how", "why", "who", "one", "two", "three", "may", "any",
    "all", "because", "between", "during", "while", "there", "here", "does", "did", "been",
    "being", "other", "same", "different", "example", "students", "lesson", "section",
    "question", "answer", "correct", "following", "best", "часть",
}


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z\-]{3,}", (text or "").lower()) if w not in STOP}


def _fit(content_words: set[str], topic_words: set[str]) -> float:
    """Share of the event's own vocabulary the lesson actually uses."""
    if not topic_words:
        return -1.0            # nothing to judge against; reported separately, never as a pass
    return len(content_words & topic_words) / len(topic_words)


def run(only: str | None) -> dict:
    rows, stats = [], Counter()
    with SessionLocal() as db:
        events = {e.id: e for e in db.scalars(select(Event)).all()}
        concepts: dict[int, list[str]] = {}
        for concept in db.scalars(select(Concept)).all():
            concepts.setdefault(concept.event_id, []).append(
                f"{concept.name} {concept.description or ''}")
        skills: dict[int, list[str]] = {}
        courses = {c.id: c for c in db.scalars(select(Course)).all()}
        for skill in db.scalars(select(Skill)).all():
            course = courses.get(skill.course_id)
            if course:
                skills.setdefault(course.event_id, []).append(
                    f"{skill.name} {skill.description or ''}")

        versions = {(v.lesson_id, v.version): v for v in db.scalars(select(LessonVersion)).all()}
        by_event: dict[int, list[tuple[Lesson, set[str]]]] = {}
        for lesson in db.scalars(select(Lesson).where(Lesson.status == "published")).all():
            if only and events.get(lesson.event_id) and events[lesson.event_id].slug != only:
                continue
            version = versions.get((lesson.id, lesson.current_version))
            text = " ".join(block_text(b) for b in (version.content if version else []) or [])
            by_event.setdefault(lesson.event_id, []).append(
                (lesson, words(f"{lesson.title} {lesson.summary} {text}")))

        for event_id, entries in by_event.items():
            event = events.get(event_id)
            if event is None:
                continue
            topic = words(" ".join(
                [event.name] + concepts.get(event_id, []) + skills.get(event_id, [])))
            for lesson, content in entries:
                fit = _fit(content, topic)
                stats["lessons"] += 1
                if fit < 0:
                    stats["no_topic_vocabulary"] += 1
                elif fit < 0.10:
                    stats["possible_drift"] += 1
                    rows.append({"kind": "drift", "event": event.slug, "title": lesson.title,
                                 "detail": f"uses {fit * 100:.0f}% of the event's vocabulary"})

            # near-duplicate lessons within one event
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    a, b = entries[i][1], entries[j][1]
                    if not a or not b:
                        continue
                    overlap = len(a & b) / min(len(a), len(b))
                    if overlap > 0.72:
                        stats["near_duplicate_pairs"] += 1
                        rows.append({
                            "kind": "duplicate", "event": event.slug,
                            "title": entries[i][0].title,
                            "detail": f"{overlap * 100:.0f}% overlap with "
                                      f"{entries[j][0].title[:38]}"})

        # items: does an exam question use its event's vocabulary at all?
        for question in db.scalars(select(Question)).all():
            provenance = question.generation_provenance or {}
            if not str(provenance.get("generation_run", "")).startswith("launch-"):
                continue
            event = events.get(question.event_id)
            if event is None:
                continue
            topic = words(" ".join(
                [event.name] + concepts.get(event.id, []) + skills.get(event.id, [])))
            body = words(f"{question.stem} {' '.join(str(c) for c in question.choices or [])}")
            stats["items"] += 1
            if topic and not (body & topic):
                stats["items_sharing_no_topic_word"] += 1
                rows.append({"kind": "item", "event": event.slug,
                             "title": f"item {question.id}",
                             "detail": question.stem[:60]})
    return {"rows": rows, "stats": stats}


def main() -> None:
    ap = argparse.ArgumentParser(description="Screen lessons and items for topical drift")
    ap.add_argument("--event", default=None)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    result = run(args.event)
    print("=" * 84)
    print("TOPICAL FIT — a cheap screen, meant to find what deserves a human's attention")
    print("=" * 84)
    for row in result["rows"][:args.top]:
        print(f"  {row['kind']:10} {row['event'][:24]:26} {row['title'][:30]:32} {row['detail'][:40]}")
    if len(result["rows"]) > args.top:
        print(f"  … {len(result['rows']) - args.top} more")
    print("-" * 84)
    for key, value in sorted(result["stats"].items()):
        print(f"  {key:30} {value}")
    print("=" * 84)


if __name__ == "__main__":
    main()
