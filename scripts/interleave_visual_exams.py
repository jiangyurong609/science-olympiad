"""Interleave image-identification questions through each visual event's exam.

Image ID questions were appended after the text questions (positions 10+), so a
student sees only text at the start. This reorders each generated exam's
ExamItems so image and text questions alternate, keeping images visible early
and throughout. Idempotent (ordering is deterministic).

Usage: python -m scripts.interleave_visual_exams
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Exam, ExamItem, Question


def interleave(db) -> None:
    exams = [e for e in db.scalars(select(Exam)).all()
             if (e.blueprint or {}).get("marker") == "catalog-2026-generated"]
    changed = 0
    for exam in exams:
        items = db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id)
                           .order_by(ExamItem.position)).all()
        if not items:
            continue
        q_by_id = {q.id: q for q in db.scalars(select(Question).where(
            Question.id.in_([i.question_id for i in items]))).all()}

        def has_image(item):
            snap = item.snapshot or {}
            if snap.get("assets"):
                return True
            q = q_by_id.get(item.question_id)
            return bool(q and (q.assets or []))

        image_items = [i for i in items if has_image(i)]
        text_items = [i for i in items if not has_image(i)]
        if not image_items:
            continue

        # Weave: spread image questions evenly across the text questions,
        # leading with one image so specimens appear immediately.
        ordered = []
        ti = iter(text_items)
        text_remaining = list(text_items)
        n_img = len(image_items)
        n_text = len(text_remaining)
        # place an image roughly every (total/n_img) slots, starting at 0
        total = n_img + n_text
        gap = max(1, total // n_img)
        img_idx = 0
        text_idx = 0
        for pos in range(total):
            if img_idx < n_img and pos % gap == 0:
                ordered.append(image_items[img_idx]); img_idx += 1
            elif text_idx < n_text:
                ordered.append(text_remaining[text_idx]); text_idx += 1
            elif img_idx < n_img:
                ordered.append(image_items[img_idx]); img_idx += 1
        # append any leftovers (safety)
        placed = {id(x) for x in ordered}
        for item in items:
            if id(item) not in placed:
                ordered.append(item)

        # Two-phase to avoid the (exam_id, position) unique constraint colliding
        # while positions are being swapped.
        for offset, item in enumerate(ordered):
            item.position = 100_000 + offset
        db.flush()
        for position, item in enumerate(ordered):
            item.position = position
        exam.question_ids = [item.question_id for item in ordered]
        db.flush()
        changed += 1
    db.commit()
    print(f"Interleaved {changed} exams.")


if __name__ == "__main__":
    with SessionLocal() as db:
        interleave(db)
