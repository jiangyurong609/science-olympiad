"""What to review next, ordered by where a mistake would cost the most.

The queue is now large — 244 items, 11 exams, 24 lessons, 25 video chapters, 403 concept
mappings — and reviewing it in database order wastes the only resource that cannot be
automated. Everything here is already machine-gated; what a human adds is judgement where the
machines disagreed, where the evidence is thinnest, or where the blast radius is widest.

So this orders the queue by risk rather than by id:

  1. **items an independent judge disputed** — the solver picked a different key, or the
     verifier objected. These are the ones most likely to be wrong, and each is quick to settle.
  2. **items whose event has the thinnest grounding** — the same gates pass more easily when
     there is less evidence to contradict them, so a thin event's items deserve more attention
     per item, not less.
  3. **exams**, which are cheap: an exam is sound if its items are, so reviewing items first
     makes exam review nearly free.
  4. **lessons and video**, which a student meets before any exam.
  5. **concept mappings**, which affect where a student is sent next but cannot serve a wrong
     fact.

Nothing here approves anything. It decides order.

    PYTHONPATH=. python -m scripts.review_worklist
    DATABASE_URL=<prod> PYTHONPATH=. python -m scripts.review_worklist --top 25
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, Exam, Lesson, LessonVersion, Question, VideoRender,
)
from app.services import lesson_blocks


def _disputed(question: Question) -> str:
    """Why an independent judge disagreed, if one did."""
    report = question.validation_report or {}
    solver = report.get("independent_solver") or {}
    key = (question.answer_spec or {}).get("correct_index")
    chosen = solver.get("chosen_index")
    if chosen is not None and key is not None and chosen != key:
        return f"solver chose {chosen}, key is {key}"
    if solver.get("ambiguous"):
        return "solver called it ambiguous"
    if solver.get("insufficient"):
        return "solver said the stem is insufficient"
    verifier = report.get("independent_verifier") or {}
    errors = verifier.get("errors") or []
    if errors:
        return f"verifier: {str(errors[0])[:60]}"
    return ""


def build() -> dict:
    with SessionLocal() as db:
        events = {e.id: e for e in db.scalars(select(Event)).all()}
        concepts = {c.id: c for c in db.scalars(select(Concept)).all()}

        # grounding depth per event — thin evidence means the gates had less to disagree with
        claims_per_event: Counter[int] = Counter()
        from app.models.entities import ScientificClaim
        for claim in db.scalars(select(ScientificClaim)).all():
            concept = concepts.get(claim.concept_id)
            if concept:
                claims_per_event[concept.event_id] += 1

        launch_items = [
            q for q in db.scalars(select(Question)).all()
            if str((q.generation_provenance or {}).get("generation_run", "")).startswith("launch-")
            or (q.generation_provenance or {}).get("generation_run") == "regen-pilot-002"
        ]
        rows = []
        for question in launch_items:
            dispute = _disputed(question)
            slug = events[question.event_id].slug if question.event_id in events else "?"
            rows.append({
                "kind": "item", "id": question.id, "event": slug,
                "why": dispute or "routine",
                # disputed first, then thinnest grounding, then by id for stability
                "rank": (0 if dispute else 1, claims_per_event.get(question.event_id, 0),
                         question.id),
            })

        exams = [e for e in db.scalars(select(Exam)).all()
                 if (e.title or "").startswith("Practice Test")]
        lessons = [l for l in db.scalars(select(Lesson).where(
            Lesson.status == "published")).all()]
        unmapped = [l for l in lessons if not l.concept_id]
        pending_video = db.scalars(select(VideoRender).where(
            VideoRender.status == "succeeded", VideoRender.qa_status == "pending")).all()

        rows.sort(key=lambda r: r["rank"])
        return {
            "rows": rows,
            "disputed": sum(1 for r in rows if r["why"] != "routine"),
            "items": len(rows),
            "exams": len(exams),
            "lessons": len(lessons),
            "video": len(pending_video),
            "unmapped_lessons": len(unmapped),
            "claims_per_event": {events[e].slug: n for e, n in claims_per_event.most_common()
                                 if e in events},
        }


def main() -> None:
    ap = argparse.ArgumentParser(description="Order the review queue by risk")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    result = build()
    print("=" * 84)
    print("REVIEW WORKLIST — highest risk first")
    print("=" * 84)
    print(f"  {result['disputed']} item(s) an independent judge disputed — start here\n")
    for row in result["rows"][:args.top]:
        flag = "DISPUTED" if row["why"] != "routine" else "        "
        print(f"  {flag}  item {row['id']:<6} {row['event'][:26]:28} {row['why'][:44]}")
    remaining = len(result["rows"]) - args.top
    if remaining > 0:
        print(f"  … {remaining} more item(s), least risky last")
    print("-" * 84)
    print("  queue")
    print(f"    items                {result['items']:>5}   ({result['disputed']} disputed)")
    print(f"    practice exams       {result['exams']:>5}   (free once their items are settled)")
    print(f"    published lessons    {result['lessons']:>5}")
    print(f"    video chapters       {result['video']:>5}")
    print(f"    lessons unmapped     {result['unmapped_lessons']:>5}   (a pedagogical call)")
    print("-" * 84)
    print("  grounding depth per event — thinner means judge its items harder")
    for slug, n in list(result["claims_per_event"].items())[:8]:
        print(f"    {slug:32} {n:>5} claims")
    print("=" * 84)


if __name__ == "__main__":
    main()
