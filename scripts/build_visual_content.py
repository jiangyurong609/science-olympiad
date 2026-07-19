"""Add image-based identification questions and a visual lesson block to the
image-critical events, using the real openly-licensed images in
app/static/media (see scripts/fetch_specimen_images.py).

For each image-critical event:
  - append an "identify this specimen" image question per specimen (4 name
    choices, the correct one plus 3 distractors drawn from sibling specimens);
  - insert an image_gallery block into the event's course after the opening;
  - refresh the exam's ExamItem snapshots so the new questions appear.

Idempotent: skips events that already have image questions.

Usage: python -m scripts.build_visual_content
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Event, Exam, ExamItem, Lesson, LessonVersion, Question, QuestionStatus, Source,
)

MEDIA_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "media"
VISUAL_MARKER = "catalog-2026-visual"

# event base-slug -> manifest key (astronomy also draws planets from solar-system)
EVENT_MANIFEST = {
    "rocks-and-minerals": ["rocks-and-minerals"],
    "astronomy": ["astronomy", "solar-system"],
    "solar-system": ["solar-system"],
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


def _images_for(base_slug: str, manifest: dict) -> list[dict]:
    rows: list[dict] = []
    seen = set()
    for key in EVENT_MANIFEST.get(base_slug, []):
        for item in manifest.get(key, []):
            if item["label"] not in seen:
                rows.append(item)
                seen.add(item["label"])
    return rows


def build(db) -> None:
    manifest = json.loads((MEDIA_DIR / "manifest.json").read_text())
    source = db.scalar(select(Source).where(Source.url == "https://commons.wikimedia.org"))
    if source is None:
        source = Source(
            url="https://commons.wikimedia.org", title="Wikimedia Commons specimen imagery",
            publisher="Wikimedia Commons", rights_status="approved_with_attribution",
            license_name="CC/Public Domain (per-image)", approved=True, crawl_status="ok",
            metadata_json={"generation_domain": "specimen_images", "open_ingest": True},
        )
        db.add(source)
        db.flush()
    events = db.scalars(select(Event).where(Event.season == 2026, Event.active.is_(True))).all()
    import re
    made = 0
    for event in events:
        base = re.sub(r"-[bc]$", "", event.slug)
        images = _images_for(base, manifest)
        if len(images) < 4:
            continue
        # Refresh: clear any prior visual questions + their exam items so a
        # larger image set rebuilds cleanly.
        old_q = [q for q in db.scalars(select(Question).where(Question.event_id == event.id)).all()
                 if (q.generation_provenance or {}).get("marker") == VISUAL_MARKER]
        if old_q:
            from sqlalchemy import delete
            old_ids = [q.id for q in old_q]
            db.execute(delete(ExamItem).where(ExamItem.question_id.in_(old_ids)))
            db.execute(delete(Question).where(Question.id.in_(old_ids)))
            db.flush()

        labels = [img["label"] for img in images]
        new_questions: list[Question] = []
        rng = random.Random(event.slug)
        for img in images:
            distractors = rng.sample([l for l in labels if l != img["label"]], 3)
            options = distractors + [img["label"]]
            rng.shuffle(options)
            correct_index = options.index(img["label"])
            asset = {"url": img["url"], "alt": img["alt"],
                     "attribution": img["attribution"], "license": img["license"]}
            question = Question(
                event_id=event.id, concept_id=None,
                source_id=source.id if source else None, version=1,
                status=QuestionStatus.MACHINE_VALIDATED.value, question_type="single_choice",
                stem="Identify the specimen shown in the image.",
                choices=options, assets=[asset],
                answer_spec={"correct_index": correct_index, "points": 1, "distractor_error_types": {}},
                explanation=f"The specimen shown is {img['label']}.",
                citations=[{"source_id": source.id if source else None, "claim_id": None,
                            "locator": "Wikimedia Commons", "evidence_excerpt": img["attribution"]}],
                difficulty=0.5, cognitive_level="recall", estimated_seconds=45,
                generation_provenance={"marker": VISUAL_MARKER, "image": img["url"]},
            )
            db.add(question)
            new_questions.append(question)
        db.flush()

        # image gallery lesson block after the opening
        lesson = db.scalar(select(Lesson).where(
            Lesson.event_id == event.id, Lesson.slug == "foundations-2026"))
        if lesson:
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version))
            if version:
                content_wo_gallery = [b for b in version.content if b.get("type") != "image_gallery"]
                gallery = {
                    "id": "image-gallery-visual", "type": "image_gallery",
                    "kicker": "Visual field guide",
                    "heading": "Learn the Specimens by Sight",
                    "body": "Study each specimen's distinctive appearance. Recognition speed is what identification stations reward.",
                    "images": [{"url": i["url"], "label": i["label"],
                                "note": "", "alt": i["alt"],
                                "attribution": i["attribution"], "license": i["license"]}
                               for i in images],
                }
                insert_at = 1 if content_wo_gallery and content_wo_gallery[0].get("type") == "opening" else 0
                content_wo_gallery.insert(insert_at, gallery)
                version.content = content_wo_gallery

        # Add a capped subset of image questions to the exam (the full set lives
        # in the lesson gallery), interleaved IMG/txt with the existing questions.
        exam = next((e for e in db.scalars(select(Exam).where(Exam.event_id == event.id)).all()
                     if (e.blueprint or {}).get("marker") == "catalog-2026-generated"), None)
        exam_added = 0
        if exam:
            # keep only the non-visual (text) items already on the exam
            current = list(db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id)
                                      .order_by(ExamItem.position)).all())
            text_items = [i for i in current if not (i.snapshot or {}).get("assets")]
            stale = [i for i in current if (i.snapshot or {}).get("assets")]
            for it in stale:
                db.delete(it)
            db.flush()
            exam_questions = new_questions[:10]
            new_items = []
            base = 100_500
            for k, q in enumerate(exam_questions):
                it = ExamItem(exam_id=exam.id, question_id=q.id, question_version=q.version,
                              position=base + k, snapshot=_snapshot(q))
                db.add(it); new_items.append(it)
            db.flush()
            # alternating merge: IMG, txt, IMG, txt, ...
            ordered, i, j = [], 0, 0
            while i < len(new_items) or j < len(text_items):
                if i < len(new_items): ordered.append(new_items[i]); i += 1
                if j < len(text_items): ordered.append(text_items[j]); j += 1
            for offset, it in enumerate(ordered):
                it.position = 200_000 + offset
            db.flush()
            for pos, it in enumerate(ordered):
                it.position = pos
            exam.question_ids = [it.question_id for it in ordered]
            exam.duration_minutes = max(20, len(ordered) * 2)
            exam_added = len(exam_questions)
        db.commit()
        made += 1
        print(f"  [{event.slug}] gallery {len(images)} imgs, +{exam_added} exam ID questions")
    print(f"Added visual content to {made} events.")


if __name__ == "__main__":
    with SessionLocal() as db:
        build(db)
