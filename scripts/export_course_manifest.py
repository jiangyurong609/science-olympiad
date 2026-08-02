"""Export an exact, stable-reference course draft manifest for review/import."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    AssessmentBlueprint, ContentGap, Course, CourseSourceCoverage, CourseUnit,
    CourseVersion, Event, Lesson, LessonSkill, LessonVersion, Question,
    ScientificClaim, Skill, Source, SourcePassage, SourceSnapshot,
)


def _hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def export_manifest(db, event_slug: str) -> dict:
    event = db.scalar(select(Event).where(Event.slug == event_slug))
    if not event:
        raise ValueError("event not found")
    course = db.scalar(select(Course).where(Course.event_id == event.id))
    if not course:
        raise ValueError("course not found")
    version = db.scalar(select(CourseVersion).where(
        CourseVersion.course_id == course.id,
        CourseVersion.version == course.current_version,
    ))
    units = db.scalars(select(CourseUnit).where(
        CourseUnit.course_id == course.id,
        CourseUnit.status != "withdrawn",
    ).order_by(CourseUnit.sequence)).all()
    skills = db.scalars(select(Skill).where(
        Skill.course_id == course.id,
        Skill.status != "withdrawn",
    ).order_by(Skill.sequence)).all()
    skill_by_id = {skill.id: skill for skill in skills}
    links = db.scalars(select(LessonSkill).where(
        LessonSkill.skill_id.in_(skill_by_id)
    )).all()
    # Every lesson a skill teaches, primary first. Keeping only the primary link silently
    # dropped 16 of the pilot's 24 lessons: splitting an over-long lesson gives a skill three
    # parts, and a migration that carries one of them is data loss reported as success.
    primary_link_by_skill = {}
    links_by_skill: dict[int, list] = {}
    for link in sorted(links, key=lambda row: (not row.is_primary, row.id)):
        primary_link_by_skill.setdefault(link.skill_id, link)
        links_by_skill.setdefault(link.skill_id, []).append(link)
    lessons = {}
    lesson_versions = {}
    for link in [row for group in links_by_skill.values() for row in group]:
        lesson = db.get(Lesson, link.lesson_id)
        if not lesson:
            continue
        lessons[lesson.id] = lesson
        lesson_versions[lesson.id] = db.scalar(select(LessonVersion).where(
            LessonVersion.lesson_id == lesson.id,
            LessonVersion.version == lesson.current_version,
        ))
    questions = db.scalars(select(Question).where(
        Question.event_id == event.id,
        Question.concept_id.in_([
            skill.concept_id for skill in skills if skill.concept_id
        ]),
    ).order_by(Question.id)).all()
    claims = {
        row.id: row for row in db.scalars(select(ScientificClaim).where(
            ScientificClaim.skill_id.in_(skill_by_id)
        )).all()
    }
    coverage = db.scalars(select(CourseSourceCoverage).where(
        CourseSourceCoverage.course_id == course.id
    ).order_by(CourseSourceCoverage.id)).all()
    source_ids = {row.source_id for row in coverage}
    sources = {
        row.id: row for row in db.scalars(select(Source).where(
            Source.id.in_(source_ids)
        )).all()
    }
    snapshots = {
        row.id: row for row in db.scalars(select(SourceSnapshot).where(
            SourceSnapshot.source_id.in_(source_ids)
        )).all()
    }

    passage_refs = {}
    passage_payloads = {}
    cited_passage_ids = {
        citation.get("source_passage_id")
        for lesson_version in lesson_versions.values() if lesson_version
        for citation in (lesson_version.citations or [])
        if citation.get("source_passage_id")
    } | {
        claim.source_passage_id for claim in claims.values()
        if claim.source_passage_id
    }
    for passage in db.scalars(select(SourcePassage).where(
        SourcePassage.id.in_(cited_passage_ids)
    )).all() if cited_passage_ids else []:
        source = sources.get(passage.source_id) or db.get(Source, passage.source_id)
        snapshot = snapshots.get(passage.source_snapshot_id) or db.get(
            SourceSnapshot, passage.source_snapshot_id
        )
        stable = hashlib.sha256(
            "|".join([
                source.url, snapshot.content_hash, passage.locator, passage.content_hash,
            ]).encode()
        ).hexdigest()[:20]
        ref = f"passage:{stable}"
        passage_refs[passage.id] = ref
        passage_payloads[ref] = {
            "source_url": source.url,
            "source_title": source.title,
            "snapshot_hash": snapshot.content_hash,
            "locator": passage.locator,
            "content_hash": passage.content_hash,
            "passage_type": passage.passage_type,
            # The evidence has to travel. Carrying only hashes meant the manifest could be
            # imported solely where byte-identical snapshots already existed — never true of
            # a fresh environment, so importing the pilot into production resolved 0 of 239
            # passages and silently did nothing. Grounding that cannot move is not portable.
            "text": passage.text,
            "sequence": passage.sequence,
            "heading": passage.heading,
            "snapshot": {
                "final_url": snapshot.final_url,
                "content_type": snapshot.content_type,
                "extracted_text": snapshot.extracted_text or "",
            },
            "source": {
                "title": source.title,
                "publisher": source.publisher,
                "rights_status": source.rights_status,
                "license_name": source.license_name,
                "approved": bool(source.approved),
            },
        }

    def stable_blocks(blocks):
        result = []
        for block in blocks or []:
            item = dict(block)
            if "passage_ids" in item:
                item["passage_refs"] = [
                    passage_refs[value] for value in item.pop("passage_ids")
                    if value in passage_refs
                ]
            result.append(item)
        return result

    def stable_citations(citations):
        result = []
        for citation in citations or []:
            item = {
                key: value for key, value in citation.items()
                if key not in {
                    "source_id", "source_snapshot_id", "source_passage_id", "claim_id",
                }
            }
            if citation.get("source_passage_id") in passage_refs:
                item["passage_ref"] = passage_refs[citation["source_passage_id"]]
            if citation.get("claim_id") in claims:
                item["claim_ref"] = f"claim:{citation['claim_id']}"
            result.append(item)
        return result

    unit_payloads = []
    for unit in units:
        unit_skills = []
        for skill in [row for row in skills if row.unit_id == unit.id]:
            link = primary_link_by_skill.get(skill.id)
            lesson = lessons.get(link.lesson_id) if link else None
            lesson_version = lesson_versions.get(lesson.id) if lesson else None
            skill_lessons = []
            for row in links_by_skill.get(skill.id, []):
                linked = lessons.get(row.lesson_id)
                linked_version = lesson_versions.get(row.lesson_id) if linked else None
                if linked is None or linked_version is None:
                    continue
                skill_lessons.append({
                    "slug": linked.slug, "title": linked.title, "summary": linked.summary,
                    "status": linked.status, "sequence": linked.sequence,
                    "estimated_minutes": linked.estimated_minutes,
                    "version": linked.current_version,
                    "review_status": linked_version.review_status,
                    "is_primary": bool(row.is_primary),
                    "content": stable_blocks(linked_version.content),
                    "citations": stable_citations(linked_version.citations),
                })
            unit_skills.append({
                "lessons": skill_lessons,
                "slug": skill.slug,
                "name": skill.name,
                "description": skill.description,
                "sequence": skill.sequence,
                "weight": skill.weight,
                "status": skill.status,
                "prerequisites": skill.prerequisites,
                "lesson": {
                    "slug": lesson.slug,
                    "title": lesson.title,
                    "summary": lesson.summary,
                    "status": lesson.status,
                    "sequence": lesson.sequence,
                    "estimated_minutes": lesson.estimated_minutes,
                    "version": lesson.current_version,
                    "review_status": lesson_version.review_status,
                    "content": stable_blocks(lesson_version.content),
                    "citations": stable_citations(lesson_version.citations),
                } if lesson and lesson_version else None,
            })
        unit_payloads.append({
            "slug": unit.slug, "title": unit.title, "summary": unit.summary,
            "sequence": unit.sequence, "status": unit.status,
            "objectives": unit.objectives, "prerequisites": unit.prerequisites,
            "skills": unit_skills,
        })

    skill_slug_by_concept = {
        skill.concept_id: skill.slug for skill in skills if skill.concept_id
    }
    question_payloads = []
    for question in questions:
        if question.concept_id not in skill_slug_by_concept:
            continue
        question_payloads.append({
            "ref": f"question:{question.id}",
            "skill_slug": skill_slug_by_concept[question.concept_id],
            "version": question.version, "status": question.status,
            "question_type": question.question_type, "stem": question.stem,
            "choices": question.choices, "answer_spec": question.answer_spec,
            "explanation": question.explanation,
            "citations": stable_citations(question.citations),
            "difficulty": question.difficulty,
            "cognitive_level": question.cognitive_level,
            "estimated_seconds": question.estimated_seconds,
            "validation_report": question.validation_report,
            "similarity_report": question.similarity_report,
            "generation_provenance": {
                key: value for key, value in (question.generation_provenance or {}).items()
                if key not in {"skill_id", "source_passage_ids"}
            },
        })
    claim_payloads = [{
        "ref": f"claim:{claim.id}",
        "skill_slug": skill_by_id[claim.skill_id].slug,
        "passage_ref": passage_refs.get(claim.source_passage_id),
        "claim_text": claim.claim_text,
        "evidence_excerpt": claim.evidence_excerpt,
        "locator": claim.locator,
        "confidence": claim.confidence,
        "approved": claim.approved,
    } for claim in sorted(claims.values(), key=lambda row: row.id)]
    blueprints = []
    for row in db.scalars(select(AssessmentBlueprint).where(
        AssessmentBlueprint.course_id == course.id
    ).order_by(AssessmentBlueprint.id)):
        specification = dict(row.specification or {})
        if "skill_ids" in specification:
            specification["skill_slugs"] = [
                skill_by_id[value].slug for value in specification.pop("skill_ids")
                if value in skill_by_id
            ]
        blueprints.append({
            "unit_slug": next(
                (unit.slug for unit in units if unit.id == row.unit_id), None
            ),
            "assessment_type": row.assessment_type,
            "version": row.version, "title": row.title,
            "specification": specification, "status": row.status,
        })
    gaps = db.scalars(select(ContentGap).where(
        ContentGap.course_id == course.id
    ).order_by(ContentGap.id)).all()
    payload = {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "student_release": False,
        "event": {
            "slug": event.slug, "season": event.season,
            "name": event.name, "division": event.division,
        },
        "course": {
            "slug": course.slug, "title": course.title, "summary": course.summary,
            "status": course.status, "version": course.current_version,
            "objectives": version.objectives if version else [],
            "review_status": version.review_status if version else "missing",
            "units": unit_payloads,
        },
        "passages": dict(sorted(passage_payloads.items())),
        "claims": claim_payloads,
        "questions": question_payloads,
        "assessment_blueprints": blueprints,
        "content_gaps": [{
            "skill_slug": skill_by_id[row.skill_id].slug,
            "gap_type": row.gap_type, "description": row.description,
            "status": row.status, "owner": row.owner,
            "resolution_notes": row.resolution_notes,
        } for row in gaps if row.skill_id in skill_by_id],
        "source_coverage": [{
            "source_url": sources[row.source_id].url,
            "snapshot_hash": snapshots[row.source_snapshot_id].content_hash
            if row.source_snapshot_id in snapshots else None,
            "instructional_role": row.instructional_role,
            "extraction_status": row.extraction_status,
            "rights_status": row.rights_status,
            "review_status": row.review_status,
            "student_destination": row.student_destination,
            "decision_reason": row.decision_reason,
            "withdrawal_reason": row.withdrawal_reason,
        } for row in coverage if row.source_id in sources],
    }
    payload["manifest_hash"] = _hash(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        manifest = export_manifest(db, args.event)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "manifest_hash": manifest["manifest_hash"],
        "units": len(manifest["course"]["units"]),
        "skills": sum(len(unit["skills"]) for unit in manifest["course"]["units"]),
        # this line used to count skills and label them lessons, so a manifest carrying 8 of
        # 24 lessons reported "lessons: 8" and looked complete
        "lessons": sum(len(skill.get("lessons", []))
                       for unit in manifest["course"]["units"]
                       for skill in unit["skills"]),
        "questions": len(manifest["questions"]),
        "claims": len(manifest["claims"]),
        "passages": len(manifest["passages"]),
    }, indent=2))


if __name__ == "__main__":
    main()
