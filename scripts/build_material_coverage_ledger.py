"""Create auditable course-source disposition rows from the retained corpus.

Dry-run by default. This does not approve rights, claims, lessons, or questions;
it records what exists and makes every missing decision visible.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import (
    Course, CourseSourceCoverage, EventSourceMap, ScientificClaim, Source,
    SourcePassage, SourceSnapshot,
)


ROLE_BY_PURPOSE = {
    "official_video": "teaching_video",
    "training_handout": "lesson_evidence",
    "reference_material": "reference_only",
    "official_event_page": "competition_scope",
    "rules_control": "competition_scope",
    "season_control": "competition_scope",
    "science_grounding": "lesson_evidence",
    "sample_test": "assessment_blueprint_evidence",
    "test": "historical_assessment",
    "answer_key": "assessment_validation",
    "answer_key_and_rubric": "assessment_validation",
    "answer_sheet": "assessment_validation",
}
STAFF_ONLY_ROLES = {"assessment_validation"}


def _extraction_status(snapshot: SourceSnapshot | None, passage_count: int) -> str:
    if snapshot is None or not (snapshot.extracted_text or "").strip():
        return "needs_extraction"
    if passage_count == 0:
        return "needs_passages"
    return "extracted"


def build(db, *, apply: bool, course_id: int | None = None) -> dict:
    courses_query = select(Course).order_by(Course.id)
    if course_id:
        courses_query = courses_query.where(Course.id == course_id)
    courses = db.scalars(courses_query).all()
    report = {
        "mode": "apply" if apply else "dry_run",
        "courses": len(courses),
        "sources_seen": 0,
        "rows_created": 0,
        "rows_updated": 0,
        "extraction_states": Counter(),
        "review_states": Counter(),
    }
    for course in courses:
        mappings = db.scalars(select(EventSourceMap).where(
            EventSourceMap.event_id == course.event_id,
        ).order_by(EventSourceMap.id)).all()
        grouped: dict[int, list[EventSourceMap]] = defaultdict(list)
        for mapping in mappings:
            grouped[mapping.source_id].append(mapping)
        for source_id, source_mappings in grouped.items():
            source = db.get(Source, source_id)
            if source is None:
                continue
            report["sources_seen"] += 1
            snapshot = db.scalar(select(SourceSnapshot).where(
                SourceSnapshot.source_id == source.id,
            ).order_by(SourceSnapshot.created_at.desc(), SourceSnapshot.id.desc()))
            passage_count = db.scalar(select(func.count(SourcePassage.id)).where(
                SourcePassage.source_snapshot_id == snapshot.id,
            )) if snapshot else 0
            claim_count = db.scalar(select(func.count(ScientificClaim.id)).where(
                ScientificClaim.source_snapshot_id == snapshot.id,
            )) if snapshot else 0
            purposes = [mapping.purpose for mapping in source_mappings]
            roles = [ROLE_BY_PURPOSE.get(purpose, "unmapped") for purpose in purposes]
            role = next((item for item in roles if item != "unmapped"), "unmapped")
            extraction_status = _extraction_status(snapshot, passage_count or 0)
            review_status = (
                "needs_rights_review"
                if not source.approved else "needs_instructional_mapping"
            )
            report["extraction_states"][extraction_status] += 1
            report["review_states"][review_status] += 1
            existing = db.scalar(select(CourseSourceCoverage).where(
                CourseSourceCoverage.course_id == course.id,
                CourseSourceCoverage.source_id == source.id,
            ))
            if existing is None:
                report["rows_created"] += 1
                if not apply:
                    continue
                existing = CourseSourceCoverage(
                    course_id=course.id,
                    source_id=source.id,
                    instructional_role=role,
                    extraction_status=extraction_status,
                    rights_status=source.rights_status,
                )
                db.add(existing)
            else:
                report["rows_updated"] += 1
                if not apply:
                    continue
            metadata = source.metadata_json or {}
            existing.source_snapshot_id = snapshot.id if snapshot else None
            existing.sheet_row = str(metadata.get("sheet_row") or "")
            existing.source_type = str(
                metadata.get("material_type") or (snapshot.content_type if snapshot else "")
            )
            existing.authority_tier = min(
                (mapping.source_tier for mapping in source_mappings),
                default=None,
            )
            if not existing.instructional_role or existing.instructional_role == "unmapped":
                existing.instructional_role = role
            existing.extraction_status = extraction_status
            existing.rights_status = source.rights_status
            existing.passage_count = passage_count or 0
            existing.claim_count = claim_count or 0
            if not existing.review_status or existing.review_status == "unreviewed":
                existing.review_status = review_status
            if existing.instructional_role in STAFF_ONLY_ROLES:
                existing.student_destination = "staff_only"
                existing.decision_reason = (
                    "Answer keys and rubrics support scoring validation and are not exposed "
                    "as student reading."
                )
            elif existing.instructional_role == "reference_only" and not existing.decision_reason:
                existing.decision_reason = (
                    "Reference-only until an editor maps specific passages to course skills."
                )
    if apply:
        db.commit()
    else:
        db.rollback()
    report["extraction_states"] = dict(report["extraction_states"])
    report["review_states"] = dict(report["review_states"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--course-id", type=int)
    args = parser.parse_args()
    with SessionLocal() as db:
        report = build(db, apply=args.apply, course_id=args.course_id)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
