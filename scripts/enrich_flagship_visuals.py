"""Add specimen images to the flagship (seed) courses and exams.

The seed events (rocks-and-minerals, entomology) power the prominent "Explore
Your Subjects" cards and have hand-authored courses that never received images.
This adds a visual field-guide gallery block to each seed course and appends
image identification questions (interleaved) to each seed exam, using the real
openly-licensed images in app/static/media.

Idempotent: clears any prior visual questions for these events, then rebuilds.

Usage: python -m scripts.enrich_flagship_visuals
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, delete

from app.core.database import SessionLocal
from app.models.entities import (
    Event, Exam, ExamItem, Lesson, LessonVersion, Question, QuestionStatus, Source,
)

MEDIA_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "media"
VISUAL_MARKER = "flagship-visual"

# seed event slug -> manifest key(s)
TARGETS = {
    "rocks-and-minerals": ["rocks-and-minerals"],
    "entomology": ["entomology"],
}


def _snapshot(q: Question) -> dict:
    return {
        "question_id": q.id, "question_version": q.version, "concept_id": q.concept_id,
        "question_type": q.question_type, "stem": q.stem, "choices": q.choices,
        "assets": q.assets or [], "answer_spec": q.answer_spec, "explanation": q.explanation,
        "citations": q.citations, "difficulty": q.difficulty,
        "cognitive_level": q.cognitive_level, "estimated_seconds": q.estimated_seconds,
    }


def _reposition_two_phase(db, exam_id, ordered_items):
    for offset, item in enumerate(ordered_items):
        item.position = 100_000 + offset
    db.flush()
    for position, item in enumerate(ordered_items):
        item.position = position
    db.flush()


def run(db) -> None:
    manifest = json.loads((MEDIA_DIR / "manifest.json").read_text())
    source = db.scalar(select(Source).where(Source.url == "https://commons.wikimedia.org"))
    if source is None:
        source = Source(url="https://commons.wikimedia.org",
                        title="Wikimedia Commons specimen imagery", publisher="Wikimedia Commons",
                        rights_status="approved_with_attribution",
                        license_name="CC/Public Domain (per-image)", approved=True, crawl_status="ok",
                        metadata_json={"generation_domain": "specimen_images"})
        db.add(source); db.flush()

    for slug, keys in TARGETS.items():
        event = db.scalar(select(Event).where(Event.slug == slug))
        if not event:
            print(f"  [{slug}] event not found; skip"); continue
        images, seen = [], set()
        for key in keys:
            for item in manifest.get(key, []):
                if item["label"] not in seen:
                    images.append(item); seen.add(item["label"])
        if len(images) < 4:
            print(f"  [{slug}] not enough images; skip"); continue

        # 1. Clear prior visual questions for this event and detach their exam items
        old_q = [q for q in db.scalars(select(Question).where(Question.event_id == event.id)).all()
                 if (q.generation_provenance or {}).get("marker") == VISUAL_MARKER]
        if old_q:
            old_ids = [q.id for q in old_q]
            db.execute(delete(ExamItem).where(ExamItem.question_id.in_(old_ids)))
            db.execute(delete(Question).where(Question.id.in_(old_ids)))
            db.flush()

        # 2. Gallery block into the event's first published lesson (after opening)
        lesson = db.scalar(select(Lesson).where(
            Lesson.event_id == event.id, Lesson.status == "published"
        ).order_by(Lesson.sequence, Lesson.id))
        if lesson:
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version))
            if version:
                content = [b for b in version.content if b.get("type") != "image_gallery"]
                gallery = {
                    "id": "image-gallery-visual", "type": "image_gallery",
                    "kicker": "Visual field guide",
                    "heading": "Learn the Specimens by Sight",
                    "body": "Study each specimen's distinctive look. Fast, accurate recognition is exactly what identification stations reward.",
                    "images": [{"url": i["url"], "label": i["label"], "note": "", "alt": i["alt"],
                                "attribution": i["attribution"], "license": i["license"]} for i in images],
                }
                insert_at = 1 if content and content[0].get("type") == "opening" else 0
                content.insert(insert_at, gallery)
                version.content = content

        # 3. Image ID questions
        labels = [i["label"] for i in images]
        rng = random.Random(slug)
        exam_images = images[:10]  # cap exam ID questions; full set stays in the gallery
        new_qs = []
        for img in exam_images:
            options = rng.sample([l for l in labels if l != img["label"]], 3) + [img["label"]]
            rng.shuffle(options)
            ci = options.index(img["label"])
            q = Question(
                event_id=event.id, concept_id=None, source_id=source.id, version=1,
                status=QuestionStatus.MACHINE_VALIDATED.value, question_type="single_choice",
                stem="Identify the specimen shown in the image.", choices=options,
                assets=[{"url": img["url"], "alt": img["alt"], "attribution": img["attribution"], "license": img["license"]}],
                answer_spec={"correct_index": ci, "points": 1, "distractor_error_types": {}},
                explanation=f"The specimen shown is {img['label']}.",
                citations=[{"source_id": source.id, "claim_id": None, "locator": "Wikimedia Commons",
                            "evidence_excerpt": img["attribution"]}],
                difficulty=0.5, cognitive_level="recall", estimated_seconds=45,
                generation_provenance={"marker": VISUAL_MARKER, "image": img["url"]},
            )
            db.add(q); new_qs.append(q)
        db.flush()

        # 4. Append to the event's exam, then interleave image/text
        exam = db.scalar(select(Exam).where(Exam.event_id == event.id, Exam.published.is_(True))
                         .order_by(Exam.id))
        if exam:
            items = list(db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id)
                                    .order_by(ExamItem.position)).all())
            base_pos = max((i.position for i in items), default=-1) + 1
            new_items = []
            for k, q in enumerate(new_qs):
                it = ExamItem(exam_id=exam.id, question_id=q.id, question_version=q.version,
                              position=base_pos + k, snapshot=_snapshot(q))
                db.add(it); new_items.append(it)
            db.flush()
            all_items = items + new_items
            img_items = [i for i in all_items if (i.snapshot or {}).get("assets")]
            txt_items = [i for i in all_items if not (i.snapshot or {}).get("assets")]
            # Alternating merge: IMG, txt, IMG, txt, ... leading with an image and
            # spreading whichever list is longer across the exam.
            ordered = []
            i = j = 0
            while i < len(img_items) or j < len(txt_items):
                if i < len(img_items):
                    ordered.append(img_items[i]); i += 1
                if j < len(txt_items):
                    ordered.append(txt_items[j]); j += 1
            _reposition_two_phase(db, exam.id, ordered)
            exam.question_ids = [it.question_id for it in ordered]
            exam.duration_minutes = max(exam.duration_minutes, len(all_items) * 2)
        db.commit()
        print(f"  [{slug}] gallery + {len(new_qs)} image questions (exam {'updated' if exam else 'none'})")
    print("Flagship visual enrichment complete.")


if __name__ == "__main__":
    with SessionLocal() as db:
        run(db)
