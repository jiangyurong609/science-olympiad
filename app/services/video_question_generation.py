"""Turn test-oriented video transcripts into reviewable assessment candidates.

Candidates are deliberately marked with a private provenance kind so the normal
student exam assembler cannot serve them before editorial approval.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Event, EventSourceMap, Question, QuestionStatus, Source, SourceSnapshot
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider
from app.services.validation import build_similarity_report, validate_candidate

SYSTEM = """You are an expert Science Olympiad assessment writer. The source is a
video transcript describing an example test or test-solving session. Create
original, age-appropriate multiple-choice practice questions only from facts,
definitions, procedures, or worked reasoning explicitly supported by the
transcript. Do not copy question wording. Do not invent values, diagrams, or
rules. Return strict JSON {\"items\":[{\"stem\":str,\"choices\":[str,str,str,str],
\"correct_index\":int,\"explanation\":str,\"estimated_seconds\":int,
\"distractor_error_types\":{}}]}. Prefer questions that test reasoning over
memorizing the speaker's wording."""


def generate_video_question_candidates(db: Session, event: Event, source: Source, *, count: int = 8, commit: bool = True) -> list[Question]:
    snapshot = db.scalar(select(SourceSnapshot).where(SourceSnapshot.source_id == source.id).order_by(SourceSnapshot.id.desc()))
    if not snapshot or snapshot.metadata_json.get("kind") != "youtube_transcript":
        return []
    existing = db.scalars(select(Question).where(Question.event_id == event.id)).all()
    if any((q.generation_provenance or {}).get("video_source_id") == source.id for q in existing):
        return []
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise ModelProviderError("External model provider is not configured")
    payload = provider.generate_json(SYSTEM, json.dumps({
        "event": event.name, "division": event.division, "source_title": source.title,
        "transcript": snapshot.extracted_text[:14000], "count": count,
    })).payload
    items = payload.get("items", []) if isinstance(payload, dict) else []
    results = []
    for raw in items[:count]:
        if not isinstance(raw, dict):
            continue
        choices = [str(c).strip() for c in raw.get("choices", [])]
        stem = str(raw.get("stem", "")).strip()
        answer_spec = {"correct_index": raw.get("correct_index"), "points": 1,
                       "distractor_error_types": raw.get("distractor_error_types", {})}
        structural = validate_candidate(db, stem=stem, choices=choices, answer_spec=answer_spec, claim_ids=[], source_id=None)
        structural["passed"] = bool(structural["passed"])
        structural["rights_check"] = False
        structural["review_required"] = ["source_rights", "editor_accuracy", "sme_accuracy", "calibration"]
        question = Question(
            event_id=event.id, source_id=source.id,
            status=QuestionStatus.MACHINE_VALIDATED.value if structural["passed"] else QuestionStatus.DRAFT.value,
            question_type="single_choice", stem=stem, choices=choices, answer_spec=answer_spec,
            explanation=str(raw.get("explanation", "")), difficulty=0.55,
            cognitive_level="application", estimated_seconds=int(raw.get("estimated_seconds", 90) or 90),
            citations=[{"source_id": source.id, "source_snapshot_id": snapshot.id,
                        "title": source.title, "url": source.url, "locator": "video transcript"}],
            validation_report=structural,
            similarity_report=build_similarity_report(db, stem, choices),
            generation_provenance={"provider": provider.model, "prompt_version": "video-test-v1",
                                   "video_source_id": source.id, "video_snapshot_id": snapshot.id,
                                   "import_kind": "video_transcript_candidate", "review_status": "editor_review"},
        )
        db.add(question); db.flush(); results.append(question)
    if commit:
        db.commit()
    return results
