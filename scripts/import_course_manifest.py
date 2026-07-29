"""Import a reviewed course draft manifest using stable source/passage identities.

Dry-run by default. The importer never creates approvals or a student release,
and refuses to overwrite published lessons.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import (
    AssessmentBlueprint, Concept, ContentGap, Course, CourseSourceCoverage,
    CourseUnit, CourseVersion, Event, Lesson, LessonSkill, LessonVersion,
    Question, ScientificClaim, Skill, Source, SourcePassage, SourceSnapshot,
)
from app.services.validation import build_similarity_report


def _hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _verify_manifest(payload: dict) -> str:
    expected = payload.get("manifest_hash")
    if not expected:
        raise ValueError("manifest_hash is missing")
    check = dict(payload)
    check.pop("manifest_hash")
    actual = _hash(check)
    if actual != expected:
        raise ValueError("manifest hash does not match the file content")
    if payload.get("student_release") is not False:
        raise ValueError("only review-only draft manifests are accepted")
    return expected


def _resolve_passages(db, payload: dict):
    resolved = {}
    missing = []
    for ref, descriptor in payload.get("passages", {}).items():
        source = db.scalar(select(Source).where(
            Source.url == descriptor["source_url"]
        ))
        snapshot = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_id == source.id,
            SourceSnapshot.content_hash == descriptor["snapshot_hash"],
        )) if source else None
        passage = db.scalar(select(SourcePassage).where(
            SourcePassage.source_snapshot_id == snapshot.id,
            SourcePassage.locator == descriptor["locator"],
            SourcePassage.content_hash == descriptor["content_hash"],
        )) if snapshot else None
        if not source or not snapshot or not passage:
            missing.append({
                "ref": ref, "source_url": descriptor["source_url"],
                "snapshot_hash": descriptor["snapshot_hash"],
                "locator": descriptor["locator"],
            })
            continue
        resolved[ref] = (source, snapshot, passage)
    return resolved, missing


def _blocks(blocks: list, passages: dict) -> list:
    result = []
    for block in blocks:
        item = dict(block)
        if "passage_refs" in item:
            refs = item.pop("passage_refs")
            item["passage_ids"] = [passages[ref][2].id for ref in refs]
        result.append(item)
    return result


def _citations(citations: list, passages: dict, claim_ids: dict | None = None) -> list:
    result = []
    for citation in citations:
        item = {
            key: value for key, value in citation.items()
            if key not in {"passage_ref", "claim_ref"}
        }
        passage_ref = citation.get("passage_ref")
        if passage_ref:
            source, snapshot, passage = passages[passage_ref]
            item.update({
                "source_id": source.id,
                "source_snapshot_id": snapshot.id,
                "source_passage_id": passage.id,
            })
        claim_ref = citation.get("claim_ref")
        if claim_ref and claim_ids and claim_ref in claim_ids:
            item["claim_id"] = claim_ids[claim_ref]
        result.append(item)
    return result


def import_manifest(db, payload: dict, *, apply: bool) -> dict:
    manifest_hash = _verify_manifest(payload)
    passages, missing = _resolve_passages(db, payload)
    event_payload = payload["event"]
    event = db.scalar(select(Event).where(
        Event.slug == event_payload["slug"],
        Event.season == event_payload["season"],
    ))
    report = {
        "mode": "apply" if apply else "dry_run",
        "manifest_hash": manifest_hash,
        "event_found": bool(event),
        "passages_required": len(payload.get("passages", {})),
        "passages_resolved": len(passages),
        "missing_passages": missing,
        "units": len(payload["course"]["units"]),
        "lessons": sum(
            len(unit["skills"]) for unit in payload["course"]["units"]
        ),
        "claims": len(payload.get("claims", [])),
        "questions": len(payload.get("questions", [])),
    }
    if not event or missing or not apply:
        db.rollback()
        return report
    course_payload = payload["course"]
    course = db.scalar(select(Course).where(Course.event_id == event.id))
    if course is None:
        course = Course(
            event_id=event.id, slug=course_payload["slug"],
            title=course_payload["title"], summary=course_payload["summary"],
            status="review_required", current_version=course_payload["version"],
        )
        db.add(course)
        db.flush()
    course.title = course_payload["title"]
    course.summary = course_payload["summary"]
    course.status = "review_required"
    course.current_version = course_payload["version"]
    course_version = db.scalar(select(CourseVersion).where(
        CourseVersion.course_id == course.id,
        CourseVersion.version == course.current_version,
    ))
    if course_version is None:
        course_version = CourseVersion(
            course_id=course.id, version=course.current_version,
        )
        db.add(course_version)
    course_version.objectives = course_payload["objectives"]
    course_version.review_status = "authoring"
    course_version.release_notes = f"Imported draft manifest {manifest_hash}."

    units_by_slug = {}
    skills_by_slug = {}
    lessons_by_slug = {}
    for unit_payload in course_payload["units"]:
        unit = db.scalar(select(CourseUnit).where(
            CourseUnit.course_id == course.id,
            CourseUnit.slug == unit_payload["slug"],
        ))
        if unit is None:
            unit = CourseUnit(
                course_id=course.id, slug=unit_payload["slug"],
                title=unit_payload["title"],
            )
            db.add(unit)
            db.flush()
        unit.title = unit_payload["title"]
        unit.summary = unit_payload["summary"]
        unit.sequence = unit_payload["sequence"]
        unit.status = "review_required"
        unit.objectives = unit_payload["objectives"]
        unit.prerequisites = unit_payload["prerequisites"]
        units_by_slug[unit.slug] = unit
        for skill_payload in unit_payload["skills"]:
            concept = db.scalar(select(Concept).where(
                Concept.event_id == event.id,
                Concept.name == skill_payload["name"],
            ))
            if concept is None:
                concept = Concept(
                    event_id=event.id, name=skill_payload["name"],
                    description=skill_payload["description"], prerequisites=[],
                )
                db.add(concept)
                db.flush()
            skill = db.scalar(select(Skill).where(
                Skill.course_id == course.id,
                Skill.slug == skill_payload["slug"],
            ))
            if skill is None:
                skill = Skill(
                    course_id=course.id, unit_id=unit.id,
                    slug=skill_payload["slug"], name=skill_payload["name"],
                )
                db.add(skill)
                db.flush()
            skill.unit_id = unit.id
            skill.concept_id = concept.id
            skill.name = skill_payload["name"]
            skill.description = skill_payload["description"]
            skill.sequence = skill_payload["sequence"]
            skill.weight = skill_payload["weight"]
            skill.status = "review_required"
            skill.prerequisites = skill_payload["prerequisites"]
            skills_by_slug[skill.slug] = skill
            lesson_payload = skill_payload.get("lesson")
            if not lesson_payload:
                continue
            lesson = db.scalar(select(Lesson).where(
                Lesson.event_id == event.id,
                Lesson.slug == lesson_payload["slug"],
            ))
            if lesson and lesson.status == "published":
                raise ValueError(
                    f"refusing to overwrite published lesson {lesson.slug}"
                )
            if lesson is None:
                lesson = Lesson(
                    event_id=event.id, slug=lesson_payload["slug"],
                    title=lesson_payload["title"], status="draft",
                )
                db.add(lesson)
                db.flush()
            lesson.concept_id = concept.id
            lesson.title = lesson_payload["title"]
            lesson.summary = lesson_payload["summary"]
            lesson.status = "draft"
            lesson.current_version = lesson_payload["version"]
            lesson.sequence = lesson_payload["sequence"]
            lesson.estimated_minutes = lesson_payload["estimated_minutes"]
            stable_content = _blocks(lesson_payload["content"], passages)
            stable_citations = _citations(lesson_payload["citations"], passages)
            lesson_version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version,
            ))
            if lesson_version is None:
                lesson_version = LessonVersion(
                    lesson_id=lesson.id, version=lesson.current_version,
                )
                db.add(lesson_version)
            elif (
                lesson_version.content != stable_content
                or lesson_version.citations != stable_citations
            ):
                raise ValueError(
                    f"existing draft version differs for lesson {lesson.slug}"
                )
            lesson_version.content = stable_content
            lesson_version.citations = stable_citations
            lesson_version.claim_ids = []
            lesson_version.review_status = "ai_draft"
            link = db.scalar(select(LessonSkill).where(
                LessonSkill.lesson_id == lesson.id,
                LessonSkill.skill_id == skill.id,
            ))
            if link is None:
                db.add(LessonSkill(
                    lesson_id=lesson.id, skill_id=skill.id,
                    is_primary=True, weight=1.0,
                ))
            lessons_by_slug[lesson.slug] = lesson

    claim_ids = {}
    for claim_payload in payload.get("claims", []):
        skill = skills_by_slug[claim_payload["skill_slug"]]
        source, snapshot, passage = passages[claim_payload["passage_ref"]]
        claim = db.scalar(select(ScientificClaim).where(
            ScientificClaim.skill_id == skill.id,
            ScientificClaim.source_passage_id == passage.id,
            ScientificClaim.claim_text == claim_payload["claim_text"],
        ))
        if claim is None:
            claim = ScientificClaim(
                source_id=source.id, source_snapshot_id=snapshot.id,
                source_passage_id=passage.id, skill_id=skill.id,
                concept_id=skill.concept_id,
                claim_text=claim_payload["claim_text"],
                evidence_excerpt=claim_payload["evidence_excerpt"],
                locator=claim_payload["locator"],
                confidence=claim_payload["confidence"], approved=False,
            )
            db.add(claim)
            db.flush()
        claim_ids[claim_payload["ref"]] = claim.id

    question_ids_by_ref = {}
    for question_payload in payload.get("questions", []):
        skill = skills_by_slug[question_payload["skill_slug"]]
        provenance = {
            **question_payload["generation_provenance"],
            "manifest_hash": manifest_hash,
            "manifest_ref": question_payload["ref"],
            "skill_id": skill.id,
        }
        question = db.scalar(select(Question).where(
            Question.event_id == event.id,
            Question.generation_provenance["manifest_hash"].as_string() == manifest_hash,
            Question.generation_provenance["manifest_ref"].as_string()
            == question_payload["ref"],
        ))
        if question is None:
            citations = _citations(
                question_payload["citations"], passages, claim_ids
            )
            question = Question(
                event_id=event.id, concept_id=skill.concept_id,
                source_id=citations[0].get("source_id") if citations else None,
                version=question_payload["version"], status="draft",
                question_type=question_payload["question_type"],
                stem=question_payload["stem"], choices=question_payload["choices"],
                answer_spec=question_payload["answer_spec"],
                explanation=question_payload["explanation"],
                citations=citations,
                difficulty=question_payload["difficulty"],
                cognitive_level=question_payload["cognitive_level"],
                estimated_seconds=question_payload["estimated_seconds"],
                validation_report=question_payload["validation_report"],
                generation_provenance=provenance,
            )
            db.add(question)
            db.flush()
            question.similarity_report = build_similarity_report(
                db, question.stem, question.choices,
                exclude_question_id=question.id,
            )
        question_ids_by_ref[question_payload["ref"]] = question.id

    for row in payload.get("assessment_blueprints", []):
        unit = units_by_slug.get(row["unit_slug"])
        blueprint = db.scalar(select(AssessmentBlueprint).where(
            AssessmentBlueprint.course_id == course.id,
            AssessmentBlueprint.unit_id == (unit.id if unit else None),
            AssessmentBlueprint.assessment_type == row["assessment_type"],
            AssessmentBlueprint.version == row["version"],
        ))
        if blueprint is None:
            blueprint = AssessmentBlueprint(
                course_id=course.id, unit_id=unit.id if unit else None,
                assessment_type=row["assessment_type"], version=row["version"],
                title=row["title"],
            )
            db.add(blueprint)
        specification = dict(row["specification"])
        if "skill_slugs" in specification:
            specification["skill_ids"] = [
                skills_by_slug[slug].id for slug in specification.pop("skill_slugs")
            ]
        blueprint.specification = specification
        blueprint.status = "draft"
    for row in payload.get("content_gaps", []):
        skill = skills_by_slug[row["skill_slug"]]
        gap = db.scalar(select(ContentGap).where(
            ContentGap.skill_id == skill.id,
            ContentGap.gap_type == row["gap_type"],
        ))
        if gap is None:
            gap = ContentGap(
                course_id=course.id, unit_id=skill.unit_id, skill_id=skill.id,
                gap_type=row["gap_type"], description=row["description"],
            )
            db.add(gap)
        gap.status = row["status"]
        gap.owner = row["owner"]
        gap.resolution_notes = row["resolution_notes"]

    coverage_by_url = {
        row["source_url"]: row for row in payload.get("source_coverage", [])
    }
    uses_by_source = defaultdict(lambda: {
        "units": set(), "skills": set(), "lessons": set(), "questions": set(),
    })
    for unit_payload in course_payload["units"]:
        unit = units_by_slug[unit_payload["slug"]]
        for skill_payload in unit_payload["skills"]:
            skill = skills_by_slug[skill_payload["slug"]]
            lesson = skill_payload.get("lesson")
            if not lesson:
                continue
            lesson_row = lessons_by_slug[lesson["slug"]]
            for citation in lesson["citations"]:
                passage_ref = citation.get("passage_ref")
                if not passage_ref:
                    continue
                source = passages[passage_ref][0]
                uses_by_source[source.id]["units"].add(unit.id)
                uses_by_source[source.id]["skills"].add(skill.id)
                uses_by_source[source.id]["lessons"].add(lesson_row.id)
    for question_payload in payload.get("questions", []):
        skill = skills_by_slug[question_payload["skill_slug"]]
        for citation in question_payload["citations"]:
            passage_ref = citation.get("passage_ref")
            if passage_ref:
                source = passages[passage_ref][0]
                uses_by_source[source.id]["questions"].add(
                    question_ids_by_ref[question_payload["ref"]]
                )
    for source_url, row in coverage_by_url.items():
        source = db.scalar(select(Source).where(Source.url == source_url))
        if not source:
            continue
        snapshot = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_id == source.id,
            SourceSnapshot.content_hash == row["snapshot_hash"],
        )) if row.get("snapshot_hash") else None
        coverage_row = db.scalar(select(CourseSourceCoverage).where(
            CourseSourceCoverage.course_id == course.id,
            CourseSourceCoverage.source_id == source.id,
        ))
        if coverage_row is None:
            coverage_row = CourseSourceCoverage(
                course_id=course.id, source_id=source.id,
                instructional_role=row["instructional_role"],
                extraction_status=row["extraction_status"],
                rights_status=row["rights_status"],
            )
            db.add(coverage_row)
        usage = uses_by_source[source.id]
        coverage_row.source_snapshot_id = snapshot.id if snapshot else None
        coverage_row.instructional_role = row["instructional_role"]
        coverage_row.extraction_status = row["extraction_status"]
        coverage_row.rights_status = row["rights_status"]
        coverage_row.review_status = row["review_status"]
        coverage_row.student_destination = row["student_destination"]
        coverage_row.decision_reason = row["decision_reason"]
        coverage_row.withdrawal_reason = row["withdrawal_reason"]
        coverage_row.mapped_unit_ids = sorted(usage["units"])
        coverage_row.mapped_skill_ids = sorted(usage["skills"])
        coverage_row.lesson_ids = sorted(usage["lessons"])
        coverage_row.question_ids = sorted(usage["questions"])
        coverage_row.passage_count = db.scalar(select(func.count()).select_from(
            SourcePassage
        ).where(SourcePassage.source_snapshot_id == snapshot.id)) if snapshot else 0
        coverage_row.claim_count = db.scalar(select(func.count()).select_from(
            ScientificClaim
        ).where(ScientificClaim.source_snapshot_id == snapshot.id)) if snapshot else 0
    db.commit()
    report["imported"] = True
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    payload = json.loads(args.manifest.read_text())
    with SessionLocal() as db:
        report = import_manifest(db, payload, apply=args.apply)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
