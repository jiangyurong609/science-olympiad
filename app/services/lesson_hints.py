"""Phase 8 — scaffolding: a hint that helps a student think, without answering for them.

Two rules decide whether a hint may be served, and they are both refusals.

**A hint is capability, and rule 4 forbids new capability on unreviewed content.** So a hint is
served only for a lesson that passed editor *and* SME review — the same evidence
`student_visibility` requires, not a weaker parallel one. Today that is zero lessons, which is
the correct answer while review is outstanding: the feature ships dark and lights up per lesson
as each is approved, consuming no review capacity in the meantime. This is the shape Phase 7
used when it was brought forward.

**A hint that gives away the answer is worse than no hint.** The catalog's other assessment
content is gated by a blind solver — an independent model shown the stem and choices but never
the key. The same instrument works here, inverted: a hint is *too strong* if a solver shown the
hint and choices, but denied the lesson, can pick the key it could not pick without it. That is
a measurable property, so `hint_is_too_revealing` records the finding on the block and
`write_checkpoint_hints` refuses to store one that fails.

Serving is deliberately a separate request rather than a field on the block. A hint the student
asked for is a signal about their confidence; a hint delivered alongside the question is just
part of the question. It is recorded on `LessonProgress` so mastery can account for it later.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Lesson, LessonProgress, LessonVersion, ReviewDecision, User
from app.services import lesson_blocks
from app.services.lesson_blocks import checkpoint_answer_index, checkpoint_stem

HINT_FIELD = "hint"
REQUIRED_STAGES = {"editor", "sme"}


class HintError(ValueError):
    pass


def lesson_is_review_cleared(db: Session, lesson: Lesson, version: LessonVersion) -> bool:
    """The same evidence `lesson_is_student_visible` demands, asked for the same version.

    Deliberately not `LessonVersion.review_status`: that is a different mechanism, and this
    codebase has already shipped three gates that agreed only by coincidence of the data.
    """
    approved = {
        stage for stage, decision in db.execute(select(
            ReviewDecision.stage, ReviewDecision.decision,
        ).where(
            ReviewDecision.entity_type == "lesson",
            ReviewDecision.entity_id == lesson.id,
            ReviewDecision.entity_version == version.version,
        )).all() if decision == "approved"
    }
    return REQUIRED_STAGES.issubset(approved)


def hint_for(
    db: Session,
    user: User,
    lesson: Lesson,
    version: LessonVersion,
    checkpoint_id: str,
) -> dict:
    """The hint for one checkpoint, or a refusal explaining which rule refused it."""
    block = next((b for index, b in enumerate(version.content or [])
                  if b.get("type") == lesson_blocks.CHECKPOINT
                  and lesson_blocks.block_id(b, index) == checkpoint_id), None)
    if block is None:
        raise HintError("Checkpoint not found")

    text = str(block.get(HINT_FIELD) or "").strip()
    if not text:
        return {"available": False, "reason": "no_hint_written"}
    if block.get("hint_too_revealing"):
        # kept on the block rather than deleted, so a reviewer can see what was rejected
        return {"available": False, "reason": "hint_withheld_pending_rewrite"}
    # Absence of the flag is not evidence of safety. A hint written by hand, or one added
    # before the check existed, carries no `hint_check` at all and was served unexamined —
    # the flag only appears when the solver *did* run and *did* object. Require the positive
    # record, and require it to match the hint on the block: `write_checkpoint_hints` edits
    # lesson content in place, so a hint can be replaced after it was cleared.
    if not hint_verified(block):
        return {"available": False, "reason": "hint_not_verified"}

    staff = user.role in {"admin", "editor", "sme", "calibrator"}
    if not staff and not lesson_is_review_cleared(db, lesson, version):
        return {"available": False, "reason": "lesson_not_yet_reviewed"}

    progress = db.scalar(select(LessonProgress).where(
        LessonProgress.user_id == user.id, LessonProgress.lesson_id == lesson.id))
    if progress is not None and not staff:
        used = dict(progress.checkpoint_results or {})
        entry = dict(used.get(checkpoint_id) or {})
        entry["hint_used"] = True
        used[checkpoint_id] = entry
        progress.checkpoint_results = used
        db.flush()
    return {"available": True, "hint": text}


def hint_fingerprint(block: dict) -> str:
    """Ties a verification to the exact hint, stem, choices and key it was run against."""
    import hashlib

    payload = "\u0000".join([
        str(block.get(HINT_FIELD) or ""),
        checkpoint_stem(block),
        "\u0001".join(str(c) for c in (block.get("choices") or [])),
        str(checkpoint_answer_index(block)),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def hint_verified(block: dict) -> bool:
    """A hint is servable only with a passing check recorded against this exact content."""
    check = block.get("hint_check")
    if not isinstance(check, dict):
        return False
    if check.get("too_revealing") is not False:
        return False
    return check.get("fingerprint") == hint_fingerprint(block)


def hint_is_too_revealing(solver_choice: int | None, answer_index: int | None,
                          baseline_choice: int | None) -> bool:
    """Did the hint hand over an answer the solver could not otherwise reach?

    Both halves matter. A solver that already knew the answer without the hint proves nothing
    about the hint — the item was simply easy. The hint is only implicated when it *changes* a
    wrong or absent answer into the key.
    """
    if answer_index is None or solver_choice is None:
        return False
    if baseline_choice == answer_index:
        return False
    return solver_choice == answer_index
