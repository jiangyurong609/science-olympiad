"""Read-only reconciliation ledger for legacy Fieldstone content.

This script never writes to the database. It inventories content records and
their student dependencies so course-map migration can preserve old exams,
attempts, progress, and source lineage.

Usage:
  DATABASE_URL=... python -m scripts.reconcile_content_inventory \
    --json data/reports/content-reconciliation.json \
    --markdown docs/CONTENT_RECONCILIATION.md
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import (
    Attempt, Concept, Event, EventSourceMap, Exam, ExamItem, Lesson,
    LessonProgress, LessonVersion, MasteryState, PracticeSet, Question,
    QuestionCalibration, QuestionReview, RawArtifact, Response, ScientificClaim,
    Source, SourceSnapshot, SpecimenAsset,
)


def _domain(url: str) -> str:
    try:
        parsed = urlparse(url or "")
        return parsed.netloc or ("local" if url else "missing")
    except ValueError:
        return "invalid_url"


def _event_dict(events):
    return {event.id: event for event in events}


def build_report(db):
    events = db.scalars(select(Event).order_by(Event.season.desc(), Event.slug)).all()
    concepts = db.scalars(select(Concept)).all()
    lessons = db.scalars(select(Lesson)).all()
    lesson_versions = db.scalars(select(LessonVersion)).all()
    practice_sets = db.scalars(select(PracticeSet)).all()
    questions = db.scalars(select(Question)).all()
    exams = db.scalars(select(Exam)).all()
    exam_items = db.scalars(select(ExamItem)).all()
    attempts = db.scalars(select(Attempt)).all()
    responses = db.scalars(select(Response)).all()
    progress = db.scalars(select(LessonProgress)).all()
    mastery = db.scalars(select(MasteryState)).all()
    sources = db.scalars(select(Source)).all()
    snapshots = db.scalars(select(SourceSnapshot)).all()
    artifacts = db.scalars(select(RawArtifact)).all()
    maps = db.scalars(select(EventSourceMap)).all()
    claims = db.scalars(select(ScientificClaim)).all()
    reviews = db.scalars(select(QuestionReview)).all()
    calibrations = db.scalars(select(QuestionCalibration)).all()
    specimen_assets = db.scalars(select(SpecimenAsset)).all()

    events_by_id = _event_dict(events)
    snapshot_by_source = defaultdict(list)
    for row in snapshots:
        snapshot_by_source[row.source_id].append(row)
    artifact_by_snapshot = {row.snapshot_id: row for row in artifacts}
    maps_by_source = defaultdict(list)
    for row in maps:
        maps_by_source[row.source_id].append(row)
    versions_by_lesson = defaultdict(list)
    for row in lesson_versions:
        versions_by_lesson[row.lesson_id].append(row)
    items_by_exam = defaultdict(list)
    for row in exam_items:
        items_by_exam[row.exam_id].append(row)
    exams_by_question = defaultdict(list)
    for row in exam_items:
        exams_by_question[row.question_id].append(row.exam_id)
    attempts_by_exam = Counter(row.exam_id for row in attempts)
    responses_by_question = Counter(row.question_id for row in responses)
    progress_by_lesson = Counter(row.lesson_id for row in progress)
    reviews_by_question = Counter(row.question_id for row in reviews)
    calibrations_by_question = Counter(row.question_id for row in calibrations)
    assets_by_source = Counter(row.source_id for row in specimen_assets)

    source_rows = []
    for source in sources:
        source_snapshots = snapshot_by_source[source.id]
        latest = max(source_snapshots, key=lambda row: (row.created_at, row.id), default=None)
        source_maps = maps_by_source[source.id]
        if not source_snapshots:
            state = "needs_extraction"
        elif not any((row.extracted_text or "").strip() for row in source_snapshots):
            state = "snapshot_without_text"
        elif source.rights_status in {"metadata_only", "link_only", "unknown"} and source.approved is not True:
            state = "rights_review_required"
        else:
            state = "extracted"
        source_rows.append({
            "id": source.id, "title": source.title, "url": source.url,
            "domain": _domain(source.url), "publisher": source.publisher,
            "approved": source.approved, "rights_status": source.rights_status,
            "crawl_status": source.crawl_status, "snapshot_count": len(source_snapshots),
            "latest_snapshot_id": latest.id if latest else None,
            "latest_content_type": latest.content_type if latest else None,
            "latest_text_chars": len(latest.extracted_text or "") if latest else 0,
            "artifact_present": bool(latest and latest.id in artifact_by_snapshot),
            "event_count": len({row.event_id for row in source_maps}),
            "event_ids": sorted({row.event_id for row in source_maps}),
            "specimen_asset_count": assets_by_source[source.id],
            "state": state,
        })

    lesson_rows = []
    for lesson in lessons:
        event = events_by_id.get(lesson.event_id)
        has_video = any(
            any(block.get("type") == "video" for block in (version.content or []))
            for version in versions_by_lesson[lesson.id]
        )
        if lesson.status != "published":
            state = "draft_review"
        elif has_video and event and event.season == 2027:
            state = "published_video_review_required"
        elif not lesson.concept_id:
            state = "published_needs_skill_mapping"
        else:
            state = "published_legacy_preserve"
        lesson_rows.append({
            "id": lesson.id, "event_id": lesson.event_id,
            "event_slug": event.slug if event else None,
            "season": event.season if event else None, "slug": lesson.slug,
            "title": lesson.title, "status": lesson.status,
            "concept_id": lesson.concept_id, "version_count": len(versions_by_lesson[lesson.id]),
            "has_video_block": has_video, "progress_count": progress_by_lesson[lesson.id],
            "state": state,
        })

    question_rows = []
    for question in questions:
        event = events_by_id.get(question.event_id)
        kind = (question.generation_provenance or {}).get("import_kind", "none")
        if kind == "video_transcript_candidate":
            state = "candidate_not_servable"
        elif exams_by_question[question.id]:
            state = "exam_snapshot_preserve_and_audit"
        elif reviews_by_question[question.id] == 0 or calibrations_by_question[question.id] == 0:
            state = "review_and_calibration_required"
        else:
            state = "reviewed"
        question_rows.append({
            "id": question.id, "event_id": question.event_id,
            "event_slug": event.slug if event else None,
            "season": event.season if event else None, "status": question.status,
            "import_kind": kind, "source_id": question.source_id,
            "concept_id": question.concept_id, "exam_count": len(exams_by_question[question.id]),
            "response_count": responses_by_question[question.id],
            "review_count": reviews_by_question[question.id],
            "calibration_count": calibrations_by_question[question.id],
            "state": state,
        })

    exam_rows = []
    for exam in exams:
        event = events_by_id.get(exam.event_id)
        exam_rows.append({
            "id": exam.id, "event_id": exam.event_id,
            "event_slug": event.slug if event else None,
            "season": event.season if event else None, "title": exam.title,
            "published": exam.published, "release_class": exam.release_class,
            "item_count": len(items_by_exam[exam.id]), "attempt_count": attempts_by_exam[exam.id],
            "state": "immutable_snapshot_preserve" if items_by_exam[exam.id] else "needs_item_audit",
        })

    event_rows = []
    for event in events:
        event_lessons = [row for row in lesson_rows if row["event_id"] == event.id]
        event_questions = [row for row in question_rows if row["event_id"] == event.id]
        event_exams = [row for row in exam_rows if row["event_id"] == event.id]
        event_sources = [row for row in source_rows if event.id in row["event_ids"]]
        event_rows.append({
            "id": event.id, "slug": event.slug, "name": event.name,
            "season": event.season, "division": event.division,
            "lesson_count": len(event_lessons), "practice_set_count": sum(1 for row in practice_sets if row.event_id == event.id),
            "question_count": len(event_questions), "published_exam_count": sum(1 for row in event_exams if row["published"]),
            "source_count": len(event_sources),
            "state": "legacy_preserve_and_map" if event.season == 2026 else "new_course_reconciliation_required",
        })

    counts = {
        "events": len(events), "concepts": len(concepts), "lessons": len(lessons),
        "lesson_versions": len(lesson_versions), "practice_sets": len(practice_sets),
        "questions": len(questions), "exams": len(exams), "exam_items": len(exam_items),
        "attempts": len(attempts), "responses": len(responses), "lesson_progress": len(progress),
        "mastery_states": len(mastery), "sources": len(sources), "source_snapshots": len(snapshots),
        "raw_artifacts": len(artifacts), "event_source_maps": len(maps),
        "scientific_claims": len(claims), "question_reviews": len(reviews),
        "question_calibrations": len(calibrations), "specimen_assets": len(specimen_assets),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "counts": counts,
        "source_state_counts": dict(Counter(row["state"] for row in source_rows)),
        "lesson_state_counts": dict(Counter(row["state"] for row in lesson_rows)),
        "question_state_counts": dict(Counter(row["state"] for row in question_rows)),
        "exam_state_counts": dict(Counter(row["state"] for row in exam_rows)),
        "events": event_rows, "sources": source_rows,
        "lessons": lesson_rows, "questions": question_rows, "exams": exam_rows,
    }


def markdown(report: dict) -> str:
    lines = ["# Content Reconciliation Ledger", "", f"Generated: {report['generated_at']}", "", "Read-only production inventory; no database writes were performed.", "", "## Counts", ""]
    lines += [f"- {key}: {value}" for key, value in report["counts"].items()]
    lines += ["", "## Migration state counts", ""]
    for label in ("source", "lesson", "question", "exam"):
        lines.append(f"### {label.title()}")
        lines.extend(f"- {key}: {value}" for key, value in report[f"{label}_state_counts"].items())
        lines.append("")
    lines += ["## Events requiring reconciliation", "", "| Season | Division | Event | Lessons | Questions | Exams | Sources | State |", "|---:|:---:|---|---:|---:|---:|---:|---|"]
    for row in report["events"]:
        lines.append(f"| {row['season']} | {row['division']} | {row['slug']} | {row['lesson_count']} | {row['question_count']} | {row['published_exam_count']} | {row['source_count']} | {row['state']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    with SessionLocal() as db:
        report = build_report(db)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, default=str) + "\n")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown(report))
    print(json.dumps({"read_only": True, "counts": report["counts"], "json": str(args.json), "markdown": str(args.markdown) if args.markdown else None}, indent=2))


if __name__ == "__main__":
    main()
