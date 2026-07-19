from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Attempt, ExamItem, Question, RemediationCase, Response, ScoreCorrection,
)
from app.services.scoring import score_response


def apply_score_correction(
    db: Session,
    *,
    challenge_id: int,
    question: Question,
    question_version: int,
    correction_type: str,
    corrected_answer_spec: dict | None,
    reason: str,
    actor_user_id: int,
) -> dict:
    items = db.scalars(select(ExamItem).where(
        ExamItem.question_id == question.id,
        ExamItem.question_version == question_version,
    )).all()
    items_by_exam = {item.exam_id: item for item in items}
    attempts = db.scalars(select(Attempt).where(
        Attempt.exam_id.in_(items_by_exam), Attempt.submitted_at.is_not(None),
    )).all() if items_by_exam else []
    changed_scores = 0
    voided_cases = 0
    opened_cases = 0
    affected_user_ids = []
    now = datetime.now(timezone.utc)
    for attempt in attempts:
        if db.scalar(select(ScoreCorrection).where(
            ScoreCorrection.challenge_id == challenge_id,
            ScoreCorrection.attempt_id == attempt.id,
        )):
            continue
        affected_user_ids.append(attempt.user_id)
        item = items_by_exam[attempt.exam_id]
        response = db.scalar(select(Response).where(
            Response.attempt_id == attempt.id, Response.question_id == question.id,
        ))
        old_points = float(response.points_awarded or 0.0) if response else 0.0
        old_score = float(attempt.score or 0.0)
        old_max = float(attempt.max_score or 0.0)
        old_state = {
            "is_correct": response.is_correct if response else None,
            "points_awarded": response.points_awarded if response else None,
            "diagnostic": response.diagnostic if response else {},
        }
        item_points = float(item.snapshot.get("answer_spec", {}).get("points", 1))
        if correction_type == "exclude_item":
            new_points = 0.0
            new_score = max(0.0, old_score - old_points)
            new_max = max(0.0, old_max - item_points)
            new_correct = None
            diagnostic = {"content_correction": "item_excluded", "challenge_id": challenge_id}
        else:
            corrected = SimpleNamespace(
                question_type=item.snapshot["question_type"],
                answer_spec=corrected_answer_spec,
            )
            new_correct, new_points, diagnostic = score_response(
                corrected, response.answer if response else {}
            )
            diagnostic = {**diagnostic, "content_correction": "key_corrected", "challenge_id": challenge_id}
            new_score = max(0.0, old_score - old_points + new_points)
            new_max = old_max
        attempt.score = new_score
        attempt.max_score = new_max
        if response:
            response.is_correct = new_correct
            response.points_awarded = new_points
            response.diagnostic = diagnostic
        case = db.scalar(select(RemediationCase).where(
            RemediationCase.attempt_id == attempt.id,
            RemediationCase.question_id == question.id,
        ))
        if correction_type == "exclude_item" or new_correct:
            if case and case.status not in {"resolved", "void_content_correction"}:
                case.status = "void_content_correction"
                case.resolved_at = now
                case.plan = {**(case.plan or {}), "void_reason": reason, "challenge_id": challenge_id}
                voided_cases += 1
        elif not case:
            db.add(RemediationCase(
                attempt_id=attempt.id, user_id=attempt.user_id, question_id=question.id,
                concept_id=question.concept_id, source_type="exam",
                source_ref=f"correction:{challenge_id}:{attempt.id}:{question.id}",
                error_type="answer_key_correction", status="open",
                diagnosis={
                    "question_stem": item.snapshot["stem"], "student_answer": response.answer if response else {},
                    "correct_answer": corrected_answer_spec, "evidence": diagnostic,
                },
                plan={
                    "steps": ["Read the correction note", "Explain the corrected reasoning", "Complete an unseen transfer item"],
                    "explanation": reason, "resolution_requires": "unseen_transfer_item",
                },
            ))
            opened_cases += 1
        active_case = db.scalar(select(RemediationCase.id).where(
            RemediationCase.attempt_id == attempt.id,
            RemediationCase.status.not_in(["resolved", "void_content_correction"]),
        ))
        attempt.status = "remediation_open" if active_case or (not new_correct and correction_type != "exclude_item") else "remediation_complete"
        db.add(ScoreCorrection(
            challenge_id=challenge_id, attempt_id=attempt.id,
            response_id=response.id if response else None,
            old_score=old_score, old_max_score=old_max,
            new_score=new_score, new_max_score=new_max,
            old_response_state=old_state,
            new_response_state={
                "is_correct": new_correct, "points_awarded": new_points, "diagnostic": diagnostic,
            },
            reason=reason, created_by_user_id=actor_user_id,
        ))
        if new_score != old_score or new_max != old_max:
            changed_scores += 1
    db.flush()
    return {
        "affected_attempts": len(attempts),
        "changed_scores": changed_scores,
        "voided_remediation_cases": voided_cases,
        "opened_remediation_cases": opened_cases,
        "affected_user_ids": sorted(set(affected_user_ids)),
    }
