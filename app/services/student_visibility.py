"""Phase 0 — the single rule deciding what a student may be served and scored on.

Four independent paths used to publish or serve unreviewed content: the catalog builder,
the mock-exam sampler (which deliberately drew `draft` items), the past-test importer, and
lesson generation's publish flag. Fixing any one of them closed nothing, so the rule lives
here and every path calls it.

The rule is deliberately narrow: an item is student-scoreable only once a human has taken
responsibility for it. Everything else may still be *shown* — labelled as unreviewed
practice — but it may not be presented as verified, and new exposure to it is refused.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Exam, ExamItem, Question, QuestionStatus

# Statuses that mean a human accepted the item. Anything below this is machine output.
STUDENT_READY_ITEM_STATUSES = {
    QuestionStatus.PUBLISHED.value,
    QuestionStatus.CALIBRATED.value,
}

# How an exam's exposure has been decided. No exam may sit in an implicit state.
DISPOSITION_REVIEWED = "reviewed"            # every item human-reviewed; fully serveable
DISPOSITION_UNREVIEWED_PRACTICE = "unreviewed_practice"  # historical; labelled, no new starts
DISPOSITION_WITHDRAWN = "withdrawn"          # not serveable at all
DISPOSITION_PENDING = "pending_disposition"  # default; treated as unsafe until decided
DISPOSITIONS = {
    DISPOSITION_REVIEWED, DISPOSITION_UNREVIEWED_PRACTICE,
    DISPOSITION_WITHDRAWN, DISPOSITION_PENDING,
}


class StudentVisibilityError(ValueError):
    """Raised when a path tries to make unreviewed content student-scoreable."""


def item_is_student_ready(question: Question) -> bool:
    return question.status in STUDENT_READY_ITEM_STATUSES


def unreviewed_item_ids(db: Session, question_ids: list[int]) -> list[int]:
    """Which of these items no human has accepted."""
    if not question_ids:
        return []
    rows = db.scalars(select(Question).where(Question.id.in_(question_ids))).all()
    found = {q.id for q in rows}
    missing = [qid for qid in question_ids if qid not in found]
    return sorted([q.id for q in rows if not item_is_student_ready(q)] + missing)


def assert_publishable(db: Session, question_ids: list[int], *, what: str = "exam") -> None:
    """Gate for every path that creates student-scoreable content."""
    unreviewed = unreviewed_item_ids(db, question_ids)
    if unreviewed:
        raise StudentVisibilityError(
            f"cannot publish {what}: {len(unreviewed)} item(s) have not been reviewed "
            f"(first: {unreviewed[:5]}). Publish it as unreviewed practice, or send the "
            f"items through review first."
        )


def exam_disposition(exam: Exam) -> str:
    value = getattr(exam, "disposition", None) or DISPOSITION_PENDING
    return value if value in DISPOSITIONS else DISPOSITION_PENDING


def can_start_new_attempt(db: Session, exam: Exam) -> tuple[bool, str]:
    """New exposure is stricter than resumption.

    A student part-way through an attempt keeps working from immutable ExamItem snapshots —
    withdrawing content must never strand saved work. But nobody new is sent into an exam
    whose items no human has accepted.
    """
    if not exam.published:
        return False, "This exam is not published."
    disposition = exam_disposition(exam)
    if disposition == DISPOSITION_WITHDRAWN:
        return False, "This exam has been withdrawn while its content is corrected."
    if disposition == DISPOSITION_PENDING:
        # Undecided is not a licence: classify from actual contents. An exam of reviewed
        # items is allowed; anything containing unreviewed items falls through to the
        # unreviewed-practice branch below and is refused.
        disposition = classify_exam(db, exam)
    if disposition == DISPOSITION_UNREVIEWED_PRACTICE:
        return False, (
            "This exam is historical practice whose items have not been reviewed, so it is "
            "no longer offered for new attempts."
        )
    return True, ""


def is_unreviewed_practice(exam: Exam) -> bool:
    """True when the UI must label the exam rather than present it as verified."""
    return exam_disposition(exam) != DISPOSITION_REVIEWED


def classify_exam(db: Session, exam: Exam) -> str:
    """The disposition an exam earns from what it will actually serve.

    `start_exam` serves ExamItem snapshots, not `exam.question_ids`, so the classifier judges
    the ExamItem rows — including the exact `question_version` recorded — and fails closed on
    any divergence between the two. Judging the id list alone would let reviewed current
    questions authorise older or extra unreviewed snapshots.
    """
    declared = list(exam.question_ids or [])
    items = db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id)
                       .order_by(ExamItem.position)).all()
    if not declared and not items:
        return DISPOSITION_WITHDRAWN
    if not items:
        # nothing snapshotted to serve yet: judge the declared list, fail closed if unreviewed
        return (DISPOSITION_REVIEWED if not unreviewed_item_ids(db, declared)
                else DISPOSITION_UNREVIEWED_PRACTICE)

    served_ids = [i.question_id for i in items]
    if declared and sorted(served_ids) != sorted(declared):
        return DISPOSITION_UNREVIEWED_PRACTICE      # drift: fail closed
    if len(set(served_ids)) != len(served_ids):
        return DISPOSITION_UNREVIEWED_PRACTICE      # duplicates: fail closed

    questions = {q.id: q for q in db.scalars(
        select(Question).where(Question.id.in_(served_ids))
    ).all()} if served_ids else {}
    for item in items:
        question = questions.get(item.question_id)
        if question is None or not item_is_student_ready(question):
            return DISPOSITION_UNREVIEWED_PRACTICE
        # human acceptance applies to a specific version; a newer draft edit must not ride
        # in on an older approval, nor an old snapshot on a newer approval
        recorded = getattr(item, "question_version", None)
        if recorded is not None and recorded != question.version:
            return DISPOSITION_UNREVIEWED_PRACTICE
    return DISPOSITION_REVIEWED
