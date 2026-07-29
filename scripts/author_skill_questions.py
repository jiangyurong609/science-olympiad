"""Draft original, passage-grounded formative questions for a course.

Generated rows remain ``draft`` and cannot enter student practice until rights,
editor, SME, and calibration gates are independently recorded.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    ContentGap, Course, CourseSourceCoverage, Event, Question, ScientificClaim,
    Skill, Source, SourcePassage,
)
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider
from app.services.validation import build_similarity_report
from scripts.author_rocks_vertical_slice import _select_passages


PROMPT_VERSION = "passage-grounded-skill-items-v1"
ALLOWED_SOURCE_ROLES = {
    "teaching_video", "lesson_evidence", "reference_only", "competition_scope",
}
SYSTEM = """You are an expert Science Olympiad assessment author. Draft original
formative questions for ONE skill using only the supplied source passages. Never copy
an existing test question and never invent a specimen property, rule, or measurement.
Return strict JSON {items:[...]}. Each item must have:
stem, exactly four choices, correct_index, explanation, rationale_by_choice for all
four choices, misconception_by_choice for each incorrect choice, cognitive_level
(recall, application, or transfer), difficulty from 0 to 1, estimated_seconds,
passage_id, claim_text, and evidence_excerpt.
The evidence_excerpt must be a short EXACT quote from the cited passage (40 words max).
Create a balanced set with recall, application, and at least one transfer item. The
explanation must teach the reasoning, not merely repeat the key. Output JSON only."""


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _choice_feedback(value) -> dict[str, str]:
    if isinstance(value, list) and len(value) == 4:
        return {str(index): str(item).strip() for index, item in enumerate(value)}
    if isinstance(value, dict):
        return {str(key): str(item).strip() for key, item in value.items()}
    return {}


def _validate_item(raw: dict, passages: dict[int, SourcePassage]) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("question item is not an object")
    choices = [str(value).strip() for value in raw.get("choices", [])]
    correct = raw.get("correct_index")
    if len(choices) != 4 or len(set(value.casefold() for value in choices)) != 4:
        raise ValueError("question needs four distinct choices")
    if not isinstance(correct, int) or not 0 <= correct < 4:
        raise ValueError("question has an invalid correct answer")
    passage_id = raw.get("passage_id")
    if not isinstance(passage_id, int) or passage_id not in passages:
        raise ValueError("question cites an unavailable passage")
    excerpt = str(raw.get("evidence_excerpt") or "").strip()
    if not excerpt or len(excerpt.split()) > 40:
        raise ValueError("evidence excerpt is missing or too long")
    if _normalize(excerpt) not in _normalize(passages[passage_id].text):
        raise ValueError("evidence excerpt is not present in the cited passage")
    rationales = _choice_feedback(raw.get("rationale_by_choice"))
    misconceptions = _choice_feedback(raw.get("misconception_by_choice"))
    if any(str(index) not in rationales for index in range(4)):
        raise ValueError("question is missing a choice rationale")
    if any(str(index) not in misconceptions for index in range(4) if index != correct):
        raise ValueError("question is missing a distractor misconception")
    stem = str(raw.get("stem") or "").strip()
    claim = str(raw.get("claim_text") or "").strip()
    if len(stem) < 12 or len(claim) < 20:
        raise ValueError("question stem or grounding claim is too short")
    cognitive = str(raw.get("cognitive_level") or "application").lower()
    if cognitive not in {"recall", "application", "transfer"}:
        raise ValueError("question has an invalid cognitive level")
    try:
        difficulty = max(0.0, min(1.0, float(raw.get("difficulty", 0.5))))
        seconds = max(30, min(240, int(raw.get("estimated_seconds", 90))))
    except (TypeError, ValueError) as exc:
        raise ValueError("question timing or difficulty is invalid") from exc
    return {
        "stem": stem, "choices": choices, "correct_index": correct,
        "explanation": str(raw.get("explanation") or "").strip(),
        "rationale_by_choice": rationales,
        "misconception_by_choice": misconceptions,
        "cognitive_level": cognitive, "difficulty": difficulty,
        "estimated_seconds": seconds, "passage_id": passage_id,
        "claim_text": claim, "evidence_excerpt": excerpt,
    }


def _generate_one(provider, course: Course, skill: Skill, passages: list[SourcePassage],
                  sources: dict[int, Source], count: int, avoid_stems: list[str]):
    payload = provider.generate_json(SYSTEM, json.dumps({
        "course": course.title,
        "skill": skill.name,
        "skill_description": skill.description,
        "count": count,
        "avoid_stems": avoid_stems,
        "passages": [{
            "passage_id": passage.id,
            "source_title": sources[passage.source_id].title,
            "locator": passage.locator,
            "text": passage.text,
        } for passage in passages],
    })).payload
    passage_map = {passage.id: passage for passage in passages}
    items = []
    failures = []
    for raw in payload.get("items", []) if isinstance(payload, dict) else []:
        try:
            items.append(_validate_item(raw, passage_map))
        except ValueError as exc:
            failures.append(str(exc))
    return items[:count], failures


def author(event_slug: str, *, apply: bool, regenerate: bool = False) -> dict:
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == event_slug))
        if not event:
            raise ValueError("event not found")
        course = db.scalar(select(Course).where(Course.event_id == event.id))
        if not course:
            raise ValueError("course scaffold not found")
        skills = db.scalars(select(Skill).where(
            Skill.course_id == course.id,
            Skill.status != "withdrawn",
        ).order_by(Skill.sequence)).all()
        coverage = db.scalars(select(CourseSourceCoverage).where(
            CourseSourceCoverage.course_id == course.id,
            CourseSourceCoverage.instructional_role.in_(ALLOWED_SOURCE_ROLES),
        )).all()
        allowed_source_ids = [row.source_id for row in coverage]
        sources = {
            row.id: row for row in db.scalars(select(Source).where(
                Source.id.in_(allowed_source_ids)
            )).all()
        }
        passages = db.scalars(select(SourcePassage).where(
            SourcePassage.source_id.in_(allowed_source_ids)
        )).all()
        planned = []
        report = {
            "mode": "apply" if apply else "dry_run",
            "skills": len(skills), "questions_created": 0,
            "questions_rejected": 0, "failed": [],
        }
        for skill in skills:
            existing = db.scalars(select(Question).where(
                Question.event_id == event.id,
                Question.concept_id == skill.concept_id,
                Question.generation_provenance["prompt_version"].as_string() == PROMPT_VERSION,
            )).all()
            target_count = 8 if skill.weight > 1 else 6
            if len(existing) >= target_count and not regenerate:
                continue
            selected = _select_passages(
                passages, sources, [skill.name, skill.description],
                require_video=False,
            )
            if not selected:
                report["failed"].append({"skill": skill.slug, "reason": "no_passages"})
                continue
            requested_count = target_count if regenerate else target_count - len(existing)
            planned.append((
                skill, selected, requested_count,
                [question.stem for question in existing],
                len(existing), target_count,
            ))
        if not apply:
            report["planned_skills"] = len(planned)
            return report
        provider = OpenAICompatibleProvider()
        if not provider.configured:
            raise ModelProviderError("External model provider is not configured")
        results = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(
                    _generate_one, provider, course, skill, selected, sources,
                    count, avoid_stems,
                ):
                    skill.slug
                for skill, selected, count, avoid_stems, _, _ in planned
            }
            for future in as_completed(futures):
                slug = futures[future]
                try:
                    results[slug] = future.result()
                except Exception as exc:  # noqa: BLE001 - retain per-skill failure
                    report["failed"].append({"skill": slug, "reason": str(exc)[:500]})
        for skill, selected, _, _, existing_count, target_count in planned:
            items, rejected = results.get(skill.slug, ([], []))
            report["questions_rejected"] += len(rejected)
            passage_map = {passage.id: passage for passage in selected}
            created_for_skill = []
            for item in items:
                passage = passage_map[item["passage_id"]]
                source = sources[passage.source_id]
                claim = ScientificClaim(
                    source_id=source.id,
                    source_snapshot_id=passage.source_snapshot_id,
                    source_passage_id=passage.id,
                    skill_id=skill.id,
                    concept_id=skill.concept_id,
                    claim_text=item["claim_text"],
                    evidence_excerpt=item["evidence_excerpt"],
                    locator=passage.locator,
                    confidence=0.7,
                    approved=False,
                )
                db.add(claim)
                db.flush()
                answer_spec = {
                    "correct_index": item["correct_index"],
                    "points": 1,
                    "rationale_by_choice": item["rationale_by_choice"],
                    "misconception_by_choice": item["misconception_by_choice"],
                }
                question = Question(
                    event_id=event.id, concept_id=skill.concept_id,
                    source_id=source.id, status="draft",
                    question_type="single_choice", stem=item["stem"],
                    choices=item["choices"], answer_spec=answer_spec,
                    explanation=item["explanation"],
                    citations=[{
                        "claim_id": claim.id,
                        "source_id": source.id,
                        "source_snapshot_id": passage.source_snapshot_id,
                        "source_passage_id": passage.id,
                        "title": source.title, "url": source.url,
                        "locator": passage.locator,
                    }],
                    difficulty=item["difficulty"],
                    cognitive_level=item["cognitive_level"],
                    estimated_seconds=item["estimated_seconds"],
                    validation_report={
                        "passed": False,
                        "structural_checks": "passed",
                        "errors": ["source_rights_review", "unapproved_claim"],
                        "review_required": ["rights", "editor", "sme", "calibration"],
                        "validator_version": "passage-candidate-1.0",
                    },
                    similarity_report=build_similarity_report(
                        db, item["stem"], item["choices"]
                    ),
                    generation_provenance={
                        "import_kind": "passage_grounded_candidate",
                        "prompt_version": PROMPT_VERSION,
                        "skill_id": skill.id,
                        "source_passage_ids": [passage.id],
                        "review_status": "editor_review",
                    },
                )
                db.add(question)
                db.flush()
                created_for_skill.append(question)
                coverage_row = next(
                    (row for row in coverage if row.source_id == source.id), None
                )
                if coverage_row:
                    coverage_row.question_ids = sorted(
                        set(coverage_row.question_ids + [question.id])
                    )
            final_count = existing_count + len(created_for_skill)
            levels = set(db.scalars(select(Question.cognitive_level).where(
                Question.event_id == event.id,
                Question.concept_id == skill.concept_id,
                Question.generation_provenance["prompt_version"].as_string()
                == PROMPT_VERSION,
            )).all())
            for gap_type in ("formative_check", "transfer_item"):
                gap = db.scalar(select(ContentGap).where(
                    ContentGap.skill_id == skill.id,
                    ContentGap.gap_type == gap_type,
                ))
                if not gap:
                    continue
                complete = (
                    final_count >= target_count
                    and (gap_type == "formative_check" or "transfer" in levels)
                )
                gap.status = "in_review" if complete else "open"
                gap.resolution_notes = (
                    f"{final_count}/{target_count} draft candidates with levels "
                    f"{sorted(levels)}; approvals and calibration remain required."
                )
            report["questions_created"] += len(created_for_skill)
        db.commit()
        return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default="rocks-and-minerals-b-2027")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--regenerate", action="store_true")
    args = parser.parse_args()
    print(json.dumps(author(
        args.event, apply=args.apply, regenerate=args.regenerate,
    ), indent=2))


if __name__ == "__main__":
    main()
