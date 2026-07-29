"""Author the Rocks & Minerals Division B course from locator-bearing passages.

The script is safe by default: it prints the scaffold plan without writing.
``--apply`` creates the review-only course graph. ``--generate`` additionally
uses the configured model to draft lessons, but never records editor/SME
approval and never makes the course student-visible.
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    AssessmentBlueprint, Concept, ContentGap, Course, CourseSourceCoverage,
    CourseUnit, CourseVersion, Event, EventSourceMap, Lesson, LessonSkill,
    LessonVersion, Skill, Source, SourcePassage,
)
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider


BLUEPRINT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "courses" / "rocks-and-minerals-b-2027.json"
)
PROMPT_VERSION = "passage-grounded-five-part-lesson-v1"
TEACHING_TYPES = {"property_cards", "steps", "worked_example"}

SYSTEM = """You are an expert middle-school Science Olympiad teacher drafting one lesson.
Use ONLY the supplied source passages. Do not invent a fact, rule, specimen property,
or test result. Return strict JSON with title, summary, estimated_minutes, misconceptions,
and blocks. The blocks must form this learning rhythm:
1. one opening block first, with the measurable goal;
2. at least three teaching blocks using property_cards, steps, or worked_example;
3. at least three checkpoint blocks spread through the lesson;
4. one summary block last with key points and next_step.

Every teaching block and checkpoint MUST contain passage_ids using only IDs supplied in
the prompt. A checkpoint must contain id, heading, question, exactly four choices,
correct_index, explanation, misconception_by_choice for every incorrect choice,
cognitive_level (recall, application, or transfer), and passage_ids. Include at least
one application or transfer checkpoint. The explanation must teach why the answer fits
the evidence. Avoid long quotations and avoid referring to 'the passage'. Output JSON only.

Allowed shapes:
opening: {type,kicker,heading,body}
property_cards: {type,heading,body,cards:[{name,cue,detail}],passage_ids}
steps: {type,heading,steps:[{label,detail}],passage_ids}
worked_example: {type,heading,prompt,steps:[string],passage_ids}
checkpoint: {type,id,heading,question,choices,correct_index,explanation,
  misconception_by_choice,cognitive_level,passage_ids}
summary: {type,heading,points:[string],next_step}
"""


def _terms(values: list[str]) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9]+", " ".join(values).lower())
        if len(token) > 2
    ]


def _passage_score(passage: SourcePassage, source: Source, keywords: list[str]) -> int:
    haystack = f"{source.title} {passage.heading} {passage.text}".lower()
    return sum(
        (6 if term in source.title.lower() else 0) + min(haystack.count(term), 4)
        for term in _terms(keywords)
    )


def _select_passages(
    passages: list[SourcePassage],
    sources: dict[int, Source],
    keywords: list[str],
    *,
    require_video: bool,
    limit: int = 10,
) -> list[SourcePassage]:
    scored = sorted(
        (
            (_passage_score(passage, sources[passage.source_id], keywords), passage)
            for passage in passages
        ),
        key=lambda pair: (pair[0], -pair[1].sequence, -pair[1].id),
        reverse=True,
    )
    selected: list[SourcePassage] = []
    used_sources: set[int] = set()
    if require_video:
        video = next(
            (passage for score, passage in scored
             if score > 0 and passage.passage_type == "video_transcript"),
            None,
        )
        if video:
            selected.append(video)
            used_sources.add(video.source_id)
    for score, passage in scored:
        if score <= 0 or passage.id in {row.id for row in selected}:
            continue
        if len(selected) >= limit:
            break
        # Start with source diversity, then fill remaining slots by relevance.
        if passage.source_id in used_sources and len(used_sources) < 4:
            continue
        selected.append(passage)
        used_sources.add(passage.source_id)
    if len(selected) < limit:
        for score, passage in scored:
            if score <= 0 or passage.id in {row.id for row in selected}:
                continue
            selected.append(passage)
            if len(selected) >= limit:
                break
    return selected


def _prompt(blueprint: dict, unit: dict, lesson: dict, passages: list[SourcePassage],
            sources: dict[int, Source]) -> str:
    return json.dumps({
        "course": blueprint["title"],
        "division": "B",
        "unit": unit["title"],
        "lesson_title": lesson["title"],
        "objective": lesson["objective"],
        "passages": [{
            "passage_id": passage.id,
            "source_title": sources[passage.source_id].title,
            "locator": passage.locator,
            "text": passage.text,
        } for passage in passages],
    })


def _normalize_blocks(raw: dict, allowed_passage_ids: set[int], lesson_slug: str) -> list[dict]:
    blocks = raw.get("blocks") if isinstance(raw, dict) else None
    if not isinstance(blocks, list):
        raise ValueError("model returned no lesson blocks")
    normalized = []
    checkpoint_index = 0
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") not in {
            "opening", "property_cards", "steps", "worked_example", "checkpoint", "summary",
        }:
            continue
        item = dict(block)
        if item["type"] in TEACHING_TYPES | {"checkpoint"}:
            passage_ids = [
                int(value) for value in item.get("passage_ids", [])
                if str(value).isdigit() and int(value) in allowed_passage_ids
            ]
            if not passage_ids:
                raise ValueError(f"{item['type']} block has no valid passage citation")
            item["passage_ids"] = list(dict.fromkeys(passage_ids))
        if item["type"] == "checkpoint":
            choices = [str(value).strip() for value in item.get("choices", [])]
            correct = item.get("correct_index")
            if len(choices) != 4 or not isinstance(correct, int) or not 0 <= correct < 4:
                raise ValueError("checkpoint must have four choices and one valid answer")
            misconceptions = {
                str(key): str(value).strip()
                for key, value in (item.get("misconception_by_choice") or {}).items()
            }
            if any(str(index) not in misconceptions for index in range(4) if index != correct):
                raise ValueError("checkpoint is missing a distractor misconception")
            checkpoint_index += 1
            item["id"] = f"{lesson_slug}-check-{checkpoint_index}"
            item["choices"] = choices
            item["correct_index"] = correct
            item["misconception_by_choice"] = misconceptions
        normalized.append(item)
    if not normalized or normalized[0].get("type") != "opening":
        raise ValueError("lesson must begin with an opening")
    if normalized[-1].get("type") != "summary":
        raise ValueError("lesson must end with a summary")
    if sum(block["type"] in TEACHING_TYPES for block in normalized) < 3:
        raise ValueError("lesson needs at least three teaching interactions")
    checkpoints = [block for block in normalized if block["type"] == "checkpoint"]
    if len(checkpoints) < 3:
        raise ValueError("lesson needs at least three checkpoints")
    if not any(
        block.get("cognitive_level") in {"application", "transfer"}
        for block in checkpoints
    ):
        raise ValueError("lesson needs an application or transfer checkpoint")
    return normalized


def _course_sources(db, event: Event):
    source_ids = db.scalars(select(EventSourceMap.source_id).where(
        EventSourceMap.event_id == event.id
    )).all()
    sources = {
        source.id: source for source in db.scalars(select(Source).where(
            Source.id.in_(source_ids)
        )).all()
    }
    passages = db.scalars(select(SourcePassage).where(
        SourcePassage.source_id.in_(source_ids)
    ).order_by(SourcePassage.source_id, SourcePassage.sequence)).all()
    return sources, passages


def _ensure_scaffold(db, blueprint: dict):
    event = db.scalar(select(Event).where(
        Event.slug == blueprint["event_slug"],
        Event.season == blueprint["season"],
    ))
    if not event:
        raise ValueError("Rocks & Minerals Division B 2027 event is not registered")
    course = db.scalar(select(Course).where(Course.event_id == event.id))
    if course is None:
        course = Course(
            event_id=event.id, slug=event.slug, title=blueprint["title"],
            summary=blueprint["summary"], status="review_required", current_version=1,
        )
        db.add(course)
        db.flush()
        db.add(CourseVersion(
            course_id=course.id, version=1, objectives=blueprint["objectives"],
            review_status="authoring",
            release_notes="Passage-grounded vertical slice in editorial review.",
        ))
    else:
        course.title = blueprint["title"]
        course.summary = blueprint["summary"]
        course.status = "review_required"
        version = db.scalar(select(CourseVersion).where(
            CourseVersion.course_id == course.id,
            CourseVersion.version == course.current_version,
        ))
        if version:
            version.objectives = blueprint["objectives"]
            version.review_status = "authoring"
    legacy = db.scalar(select(CourseUnit).where(
        CourseUnit.course_id == course.id,
        CourseUnit.slug == "legacy-learning-path",
    ))
    if legacy:
        legacy.status = "withdrawn"
        legacy.sequence = 10_000

    rows = []
    sequence = 0
    for unit_index, unit_data in enumerate(blueprint["units"], start=1):
        unit = db.scalar(select(CourseUnit).where(
            CourseUnit.course_id == course.id,
            CourseUnit.slug == unit_data["slug"],
        ))
        if unit is None:
            unit = CourseUnit(
                course_id=course.id, slug=unit_data["slug"],
                title=unit_data["title"], summary=unit_data["summary"],
            )
            db.add(unit)
            db.flush()
        unit.title = unit_data["title"]
        unit.summary = unit_data["summary"]
        unit.objectives = unit_data["objectives"]
        unit.sequence = unit_index * 10
        unit.status = "review_required"
        skill_ids = []
        for lesson_data in unit_data["lessons"]:
            sequence += 1
            concept = db.scalar(select(Concept).where(
                Concept.event_id == event.id,
                Concept.name == lesson_data["title"],
            ))
            if concept is None:
                concept = Concept(
                    event_id=event.id, name=lesson_data["title"],
                    description=lesson_data["objective"], prerequisites=[],
                )
                db.add(concept)
                db.flush()
            skill = db.scalar(select(Skill).where(
                Skill.course_id == course.id,
                Skill.slug == lesson_data["slug"],
            ))
            if skill is None:
                skill = Skill(
                    course_id=course.id, unit_id=unit.id,
                    slug=lesson_data["slug"], name=lesson_data["title"],
                )
                db.add(skill)
                db.flush()
            skill.unit_id = unit.id
            skill.concept_id = concept.id
            skill.description = lesson_data["objective"]
            skill.sequence = sequence * 10
            skill.weight = 1.5 if lesson_data.get("high_weight") else 1.0
            skill.status = "review_required"
            skill_ids.append(skill.id)
            rows.append((unit_data, unit, lesson_data, skill, concept, sequence))
            for gap_type, description in (
                ("lesson", "Needs a passage-grounded teach lesson."),
                ("formative_check", "Needs approved formative practice."),
                ("transfer_item", "Needs an unseen transfer item."),
            ):
                gap = db.scalar(select(ContentGap).where(
                    ContentGap.skill_id == skill.id,
                    ContentGap.gap_type == gap_type,
                ))
                if gap is None:
                    db.add(ContentGap(
                        course_id=course.id, unit_id=unit.id, skill_id=skill.id,
                        gap_type=gap_type, description=description,
                    ))
        blueprint_row = db.scalar(select(AssessmentBlueprint).where(
            AssessmentBlueprint.course_id == course.id,
            AssessmentBlueprint.unit_id == unit.id,
            AssessmentBlueprint.assessment_type == "unit_quiz",
            AssessmentBlueprint.version == 1,
        ))
        if blueprint_row is None:
            db.add(AssessmentBlueprint(
                course_id=course.id, unit_id=unit.id, assessment_type="unit_quiz",
                version=1, title=f"{unit.title} Quiz", status="draft",
                specification={
                    "skill_ids": skill_ids, "question_count": 6,
                    "cognitive_mix": {"recall": 0.25, "application": 0.5, "transfer": 0.25},
                    "retryable": True,
                },
            ))
    for assessment_type, title in (
        ("course_diagnostic", "Check What I Know"),
        ("course_challenge", "Rocks and Minerals Course Challenge"),
        ("timed_simulation", "Competition Station Simulation"),
    ):
        existing = db.scalar(select(AssessmentBlueprint).where(
            AssessmentBlueprint.course_id == course.id,
            AssessmentBlueprint.unit_id.is_(None),
            AssessmentBlueprint.assessment_type == assessment_type,
            AssessmentBlueprint.version == 1,
        ))
        if existing is None:
            db.add(AssessmentBlueprint(
                course_id=course.id, unit_id=None, assessment_type=assessment_type,
                version=1, title=title, status="draft",
                specification={"coverage": "all_skills", "review_required": True},
            ))
    db.flush()
    return event, course, rows


def _video_block(passages: list[SourcePassage], sources: dict[int, Source]) -> dict | None:
    video_passage = next(
        (passage for passage in passages if passage.passage_type == "video_transcript"),
        None,
    )
    if not video_passage:
        return None
    # Snapshot metadata is loaded by the caller into the Source's metadata after
    # transcript ingestion; avoid another model call or external lookup.
    source = sources[video_passage.source_id]
    video = (source.metadata_json or {}).get("video") or {}
    if not video.get("video_id"):
        return None
    return {
        "type": "video",
        "video_id": video["video_id"],
        "title": video.get("title") or source.title,
        "channel": video.get("channel") or "",
        "duration": video.get("duration"),
        "transcript_source": source.id,
        "transcript_excerpt": (
            f"Focus on {video_passage.locator}; the notes and checks that follow "
            "use the retained transcript."
        ),
        "passage_ids": [video_passage.id],
    }


def _generate_one(provider, blueprint, unit_data, lesson_data, passages, sources):
    result = provider.generate_json(
        SYSTEM, _prompt(blueprint, unit_data, lesson_data, passages, sources)
    )
    blocks = _normalize_blocks(
        result.payload, {passage.id for passage in passages}, lesson_data["slug"]
    )
    if lesson_data.get("video"):
        block = _video_block(passages, sources)
        if block:
            blocks.insert(1, block)
    return {
        "payload": result.payload,
        "blocks": blocks,
        "provider": result.provider,
        "model": result.model,
    }


def author(*, apply: bool, generate: bool, regenerate: bool = False) -> dict:
    blueprint = json.loads(BLUEPRINT_PATH.read_text())
    report = {
        "mode": "apply" if apply else "dry_run",
        "generate": generate,
        "units": len(blueprint["units"]),
        "planned_lessons": sum(len(unit["lessons"]) for unit in blueprint["units"]),
        "generated_lessons": 0,
        "failed": [],
    }
    if not apply:
        return report
    with SessionLocal() as db:
        event, course, scaffold = _ensure_scaffold(db, blueprint)
        sources, all_passages = _course_sources(db, event)
        generation_rows = []
        for unit_data, unit, lesson_data, skill, concept, sequence in scaffold:
            passages = _select_passages(
                all_passages, sources, lesson_data["keywords"],
                require_video=bool(lesson_data.get("video")),
            )
            if not passages:
                gap = ContentGap(
                    course_id=course.id, unit_id=unit.id, skill_id=skill.id,
                    gap_type="source_support",
                    description="No retained source passage matched this skill.",
                )
                if not db.scalar(select(ContentGap).where(
                    ContentGap.skill_id == skill.id,
                    ContentGap.gap_type == "source_support",
                )):
                    db.add(gap)
                report["failed"].append({
                    "lesson": lesson_data["slug"], "reason": "no_matching_passages",
                })
                continue
            generation_rows.append(
                (unit_data, unit, lesson_data, skill, concept, sequence, passages)
            )
        if generate:
            provider = OpenAICompatibleProvider()
            if not provider.configured:
                raise ModelProviderError("External model provider is not configured")
            results = {}
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {
                    pool.submit(
                        _generate_one, provider, blueprint, unit_data, lesson_data,
                        passages, sources,
                    ): lesson_data["slug"]
                    for unit_data, _, lesson_data, _, _, _, passages in generation_rows
                }
                for future in as_completed(futures):
                    slug = futures[future]
                    try:
                        results[slug] = future.result()
                    except Exception as exc:  # noqa: BLE001 - retain per-lesson failure
                        report["failed"].append({"lesson": slug, "reason": str(exc)[:500]})

            for unit_data, unit, lesson_data, skill, concept, sequence, passages in generation_rows:
                generated = results.get(lesson_data["slug"])
                if not generated:
                    continue
                lesson = db.scalar(select(Lesson).where(
                    Lesson.event_id == event.id,
                    Lesson.slug == lesson_data["slug"],
                ))
                if lesson and not regenerate:
                    continue
                if lesson is None:
                    lesson = Lesson(
                        event_id=event.id, slug=lesson_data["slug"],
                        title=lesson_data["title"], status="draft",
                    )
                    db.add(lesson)
                    db.flush()
                    version_number = 1
                else:
                    version_number = lesson.current_version + 1
                lesson.concept_id = concept.id
                lesson.title = lesson_data["title"]
                lesson.summary = str(
                    generated["payload"].get("summary") or lesson_data["objective"]
                )
                lesson.status = "draft"
                lesson.current_version = version_number
                lesson.sequence = sequence * 10
                lesson.estimated_minutes = max(
                    5, min(12, int(generated["payload"].get("estimated_minutes") or 8))
                )
                citations = [{
                    "source_id": passage.source_id,
                    "source_snapshot_id": passage.source_snapshot_id,
                    "source_passage_id": passage.id,
                    "title": sources[passage.source_id].title,
                    "publisher": sources[passage.source_id].publisher,
                    "url": sources[passage.source_id].url,
                    "locator": passage.locator,
                } for passage in passages]
                db.add(LessonVersion(
                    lesson_id=lesson.id, version=version_number,
                    content=generated["blocks"], claim_ids=[], citations=citations,
                    review_status="ai_draft",
                ))
                link = db.scalar(select(LessonSkill).where(
                    LessonSkill.lesson_id == lesson.id,
                    LessonSkill.skill_id == skill.id,
                ))
                if link is None:
                    db.add(LessonSkill(
                        lesson_id=lesson.id, skill_id=skill.id,
                        is_primary=True, weight=1.0,
                    ))
                lesson_gap = db.scalar(select(ContentGap).where(
                    ContentGap.skill_id == skill.id,
                    ContentGap.gap_type == "lesson",
                ))
                if lesson_gap:
                    lesson_gap.status = "in_review"
                    lesson_gap.resolution_notes = (
                        f"AI draft lesson {lesson.id} version {version_number}; "
                        "editor and SME approval still required."
                    )
                for passage in passages:
                    coverage = db.scalar(select(CourseSourceCoverage).where(
                        CourseSourceCoverage.course_id == course.id,
                        CourseSourceCoverage.source_id == passage.source_id,
                    ))
                    if not coverage:
                        continue
                    coverage.mapped_unit_ids = sorted(set(coverage.mapped_unit_ids + [unit.id]))
                    coverage.mapped_skill_ids = sorted(set(coverage.mapped_skill_ids + [skill.id]))
                    coverage.lesson_ids = sorted(set(coverage.lesson_ids + [lesson.id]))
                    if coverage.student_destination != "staff_only":
                        coverage.student_destination = (
                            f"/courses/{event.season}/{event.slug}/lesson/{lesson.slug}"
                        )
                    if coverage.review_status == "needs_instructional_mapping":
                        coverage.review_status = "lesson_draft_review"
                report["generated_lessons"] += 1
        db.commit()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--regenerate", action="store_true")
    args = parser.parse_args()
    if args.generate and not args.apply:
        raise SystemExit("--generate requires --apply")
    print(json.dumps(author(
        apply=args.apply, generate=args.generate, regenerate=args.regenerate,
    ), indent=2))


if __name__ == "__main__":
    main()
