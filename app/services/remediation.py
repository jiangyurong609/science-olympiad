from __future__ import annotations
from datetime import datetime, timedelta, timezone
import random
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import MasteryState, Question, RemediationCase, TransferAttempt
from app.services.scoring import score_response


def build_transfer_question(db: Session, case: RemediationCase) -> TransferAttempt:
    existing = db.scalar(
        select(TransferAttempt).where(
            TransferAttempt.remediation_case_id == case.id,
            TransferAttempt.completed_at.is_(None),
        ).order_by(TransferAttempt.id.desc())
    )
    if existing:
        return existing
    source = _case_source(db, case)
    payload = _variant(source, case.id)
    transfer = TransferAttempt(
        remediation_case_id=case.id,
        user_id=case.user_id,
        question_payload=payload,
    )
    db.add(transfer)
    case.status = "near_transfer"
    db.commit()
    db.refresh(transfer)
    return transfer


def _case_source(db: Session, case: RemediationCase) -> dict:
    source = db.get(Question, case.question_id) if case.question_id else None
    if source:
        return {
            "id": source.id,
            "question_type": source.question_type,
            "stem": source.stem,
            "choices": source.choices,
            "answer_spec": source.answer_spec,
            "explanation": source.explanation,
            "concept_id": source.concept_id,
        }
    snapshot = (case.diagnosis or {}).get("transfer_source")
    if not snapshot:
        raise ValueError("Original question snapshot is unavailable")
    return snapshot


def _variant(source: dict, seed: int) -> dict:
    if source["question_type"] == "single_choice":
        choices = list(source["choices"])
        correct = int(source["answer_spec"].get("correct_index", 0))
        tagged = list(enumerate(choices))
        random.Random(f"transfer:{source.get('id', 'snapshot')}:{seed}").shuffle(tagged)
        new_choices = [value for _, value in tagged]
        new_correct = next(i for i, (old, _) in enumerate(tagged) if old == correct)
        return {
            "question_type": "single_choice",
            "stem": f"Transfer check: {source['stem']}",
            "choices": new_choices,
            "answer_spec": {**source["answer_spec"], "correct_index": new_correct},
            "explanation": source.get("explanation", ""),
            "concept_id": source.get("concept_id"),
            "source_question_id": source.get("id"),
        }
    return {
        "question_type": source["question_type"],
        "stem": f"Transfer check: {source['stem']}",
        "choices": source.get("choices", []),
        "answer_spec": source["answer_spec"],
        "explanation": source.get("explanation", ""),
        "concept_id": source.get("concept_id"),
        "source_question_id": source.get("id"),
    }


def grade_transfer(db: Session, transfer: TransferAttempt, answer: dict) -> TransferAttempt:
    class SnapshotQuestion:
        question_type = transfer.question_payload["question_type"]
        answer_spec = transfer.question_payload["answer_spec"]

    correct, _, diagnostic = score_response(SnapshotQuestion(), answer)
    now = datetime.now(timezone.utc)
    transfer.answer = answer
    transfer.is_correct = correct
    transfer.diagnostic = diagnostic
    transfer.completed_at = now
    case = db.get(RemediationCase, transfer.remediation_case_id)
    if not case:
        raise ValueError("Remediation case missing")
    if correct:
        case.status = "delayed_review"
        case.plan = {
            **case.plan,
            "transfer_passed_at": now.isoformat(),
            "next_review_at": (now + timedelta(days=3)).isoformat(),
        }
        if case.concept_id:
            mastery = db.scalar(select(MasteryState).where(
                MasteryState.user_id == case.user_id,
                MasteryState.concept_id == case.concept_id,
            ))
            if not mastery:
                mastery = MasteryState(
                    user_id=case.user_id, concept_id=case.concept_id,
                    mastery_probability=0.25, evidence_count=0, misconception_risk=0.5,
                )
            mastery.evidence_count = (mastery.evidence_count or 0) + 1
            mastery.mastery_probability = min(0.95, (mastery.mastery_probability or 0.25) + 0.2)
            mastery.misconception_risk = max(0.05, (mastery.misconception_risk or 0.5) - 0.2)
            mastery.last_practiced_at = now
            mastery.next_review_at = now + timedelta(days=3)
            db.add(mastery)
    else:
        case.status = "guided_practice"
        case.plan = {**case.plan, "transfer_failed_at": now.isoformat(), "retry_required": True}
    db.add(case)
    db.add(transfer)
    db.commit()
    db.refresh(transfer)
    return transfer


def build_delayed_review(db: Session, case: RemediationCase) -> TransferAttempt:
    existing = db.scalar(select(TransferAttempt).where(
        TransferAttempt.remediation_case_id == case.id,
        TransferAttempt.completed_at.is_(None),
    ).order_by(TransferAttempt.id.desc()))
    if existing and existing.question_payload.get("review_phase") == "delayed":
        return existing
    if case.status != "delayed_review":
        raise ValueError("Case is not ready for delayed review")
    due_text = (case.plan or {}).get("next_review_at")
    if not due_text:
        raise ValueError("Delayed review has no due date")
    due = datetime.fromisoformat(due_text)
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) < due:
        raise ValueError("Delayed review is not due yet")
    source = _case_source(db, case)
    payload = _variant(source, case.id + 1_000_000)
    payload["stem"] = f"Delayed retention check: {source['stem']}"
    payload["review_phase"] = "delayed"
    transfer = TransferAttempt(remediation_case_id=case.id, user_id=case.user_id, question_payload=payload)
    db.add(transfer)
    case.status = "delayed_check_in_progress"
    db.commit()
    db.refresh(transfer)
    return transfer


def grade_delayed_review(db: Session, transfer: TransferAttempt, answer: dict) -> TransferAttempt:
    if transfer.question_payload.get("review_phase") != "delayed":
        raise ValueError("Transfer attempt is not a delayed review")

    class SnapshotQuestion:
        question_type = transfer.question_payload["question_type"]
        answer_spec = transfer.question_payload["answer_spec"]

    correct, _, diagnostic = score_response(SnapshotQuestion(), answer)
    now = datetime.now(timezone.utc)
    transfer.answer = answer
    transfer.is_correct = correct
    transfer.diagnostic = diagnostic
    transfer.completed_at = now
    case = db.get(RemediationCase, transfer.remediation_case_id)
    if not case:
        raise ValueError("Remediation case missing")
    mastery = None
    if case.concept_id:
        mastery = db.scalar(select(MasteryState).where(MasteryState.user_id == case.user_id, MasteryState.concept_id == case.concept_id))
    if correct:
        case.status = "resolved"
        case.resolved_at = now
        case.plan = {**case.plan, "delayed_review_passed_at": now.isoformat()}
        if mastery:
            mastery.evidence_count += 1
            mastery.mastery_probability = min(0.99, mastery.mastery_probability + 0.1)
            mastery.misconception_risk = max(0.01, mastery.misconception_risk - 0.1)
            mastery.last_practiced_at = now
            mastery.next_review_at = now + timedelta(days=14)
    else:
        case.status = "reopened"
        case.plan = {**case.plan, "delayed_review_failed_at": now.isoformat(), "retry_required": True}
        if mastery:
            mastery.mastery_probability = max(0.05, mastery.mastery_probability - 0.15)
            mastery.misconception_risk = min(0.99, mastery.misconception_risk + 0.2)
            mastery.last_practiced_at = now
            mastery.next_review_at = now + timedelta(days=1)
    db.add(case)
    if mastery:
        db.add(mastery)
    db.add(transfer)
    db.commit()
    db.refresh(transfer)
    return transfer
