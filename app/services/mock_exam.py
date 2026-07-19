"""On-demand shuffled mock exams.

Assemble a fresh Exam by sampling from an event's question pool (its imported
past-test questions), shuffling the item order — and optionally the answer-choice
order for multiple-choice items. Each call mints a new Exam so different students
(or repeat attempts) get a different draw; the existing take/score/feedback flow
handles it unchanged.
"""
from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Event, Exam, ExamItem, Question, QuestionStatus
from app.services.blueprint import blueprint_for, select_for_blueprint
from app.services.scoring import is_servable


POOL_IMPORT_KINDS = {"past_test", "generated_from_material"}


def event_question_pool(db: Session, event: Event) -> list[Question]:
    questions = db.scalars(select(Question).where(
        Question.event_id == event.id,
        Question.status == QuestionStatus.DRAFT.value,
    )).all()
    # Only questions that (a) come from an accepted import kind and (b) are
    # servable — auto-scorable and not missing a figure they depend on. Never
    # assemble an exam around an item with no reference answer or no figure.
    return [q for q in questions
            if (q.generation_provenance or {}).get("import_kind") in POOL_IMPORT_KINDS
            and is_servable(q.question_type, q.answer_spec or {}, q.stem, q.assets)]


def _snapshot(question: Question, shuffle_choices: bool) -> dict:
    snapshot = {
        "stem": question.stem,
        "choices": list(question.choices or []),
        "assets": question.assets,
        "question_type": question.question_type,
        "answer_spec": dict(question.answer_spec or {}),
        "explanation": question.explanation,
        "citations": question.citations,
        "concept_id": question.concept_id,
        "estimated_seconds": question.estimated_seconds,
    }
    spec = snapshot["answer_spec"]
    correct = spec.get("correct_index")
    if (shuffle_choices and question.question_type == "single_choice"
            and snapshot["choices"] and isinstance(correct, int)
            and 0 <= correct < len(snapshot["choices"])):
        order = list(range(len(snapshot["choices"])))
        random.shuffle(order)
        snapshot["choices"] = [snapshot["choices"][i] for i in order]
        spec["correct_index"] = order.index(correct)
        # Every choice-index-keyed map must move with the shuffle, or the
        # per-choice diagnostic/misconception ends up pointing at a different
        # option than the student picked.
        for field in ("distractor_error_types", "misconception_by_choice"):
            mapping = spec.get(field) or {}
            if mapping:
                spec[field] = {
                    str(order.index(int(k))): v for k, v in mapping.items()
                    if str(k).lstrip("-").isdigit() and int(k) in order
                }
        snapshot["answer_spec"] = spec
    return snapshot


def assemble_mock_exam(
    db: Session, event: Event, size: int = 20, feedback_mode: str = "after_submit",
    shuffle_choices: bool = True, title: str | None = None, use_blueprint: bool = True,
) -> Exam:
    pool = event_question_pool(db, event)
    if not pool:
        raise ValueError("No past-test questions are available for this event yet")
    size = min(size, len(pool))
    blueprint = blueprint_for(db, event, pool) if use_blueprint else None
    if blueprint:
        selected = select_for_blueprint(pool, size, blueprint)
    else:
        selected = random.sample(pool, size)
        random.shuffle(selected)
    duration = max(10, round(sum(q.estimated_seconds for q in selected) / 60))
    exam = Exam(
        event_id=event.id,
        title=title or f"{event.name} — Mock Exam ({size} questions)",
        duration_minutes=duration,
        question_ids=[q.id for q in selected],
        published=True,
        release_class="mock_shuffled",
        blueprint={
            "import_kind": "mock_shuffled",
            "feedback_mode": feedback_mode,
            "question_count": size,
            "pool_size": len(pool),
            "shuffle_choices": shuffle_choices,
            "blueprint_source": (blueprint or {}).get("source", "random"),
            "cognitive_mix": (blueprint or {}).get("cognitive_mix", {}),
            "snapshot_schema": 1,
        },
    )
    db.add(exam)
    db.flush()
    for position, question in enumerate(selected):
        db.add(ExamItem(
            exam_id=exam.id, question_id=question.id, question_version=question.version,
            position=position, snapshot=_snapshot(question, shuffle_choices),
        ))
    db.commit()
    db.refresh(exam)
    return exam
