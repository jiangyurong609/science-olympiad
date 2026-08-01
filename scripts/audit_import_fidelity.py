"""Phase 7c — report how faithfully each past-test import reproduced its source.

Import success has been measured by "it ran". That hides the two things that decide whether
an imported test is usable: how many printed items actually became answerable questions, and
how many of those carry a key anyone can trust. Both are now recorded per item at import
time, so this reads them back rather than re-deriving them.

Fidelity is deliberately reported as several numbers, not one score. An import that produced
40 items with withheld keys and one that produced 40 clean items are not the same event, and
a single percentage would let the first hide behind the second.

    PYTHONPATH=. python -m scripts.audit_import_fidelity
    PYTHONPATH=. python -m scripts.audit_import_fidelity --event rocks-and-minerals-b
    PYTHONPATH=. python -m scripts.audit_import_fidelity --json docs/history/import_fidelity.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Question, Source
from app.services.scoring import is_figure_missing, is_gradeable


def collect(event_slug: str | None = None) -> dict:
    with SessionLocal() as db:
        query = select(Question).where(
            Question.generation_provenance["import_kind"].as_string() == "past_test")
        if event_slug:
            event = db.scalar(select(Event).where(Event.slug == event_slug))
            if not event:
                raise SystemExit(f"unknown event {event_slug!r}")
            query = query.where(Question.event_id == event.id)
        questions = db.scalars(query).all()
        if not questions:
            raise SystemExit(
                "FAIL: no imported past-test questions matched. An empty population is a "
                "failure, not perfect fidelity."
            )

        events = dict(db.execute(select(Event.id, Event.slug)).all())
        sources = dict(db.execute(select(Source.id, Source.title)).all())

        by_source: dict[int, list[Question]] = defaultdict(list)
        for question in questions:
            by_source[(question.generation_provenance or {}).get("exam_source_id")].append(
                question)

    rows = []
    for source_id, group in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
        provenances = [q.generation_provenance or {} for q in group]
        # older imports predate these fields; absent is reported as unknown, never as good
        confidences = [p["parse_confidence"] for p in provenances
                       if isinstance(p.get("parse_confidence"), (int, float))]
        gradeable = sum(1 for q in group if is_gradeable(q.question_type, q.answer_spec or {}))
        figure_ok = sum(1 for q in group
                        if not is_figure_missing(q.stem, q.assets))
        rows.append({
            "source_id": source_id,
            "source": sources.get(source_id, "(unknown source)"),
            "event": events.get(group[0].event_id, ""),
            "items": len(group),
            "gradeable": gradeable,
            "gradeable_pct": round(100 * gradeable / len(group), 1),
            "answer_withheld": sum(1 for p in provenances if p.get("answer_withheld")),
            "figure_ready": figure_ok,
            "figure_ready_pct": round(100 * figure_ok / len(group), 1),
            "figures_attached": sum(1 for q in group if q.assets),
            "figure_resolved": sum(1 for p in provenances if p.get("figure_resolved")),
            "confidence_measured": len(confidences),
            "confidence_unknown": len(group) - len(confidences),
            "mean_confidence": round(sum(confidences) / len(confidences), 3)
            if confidences else None,
            "top_reasons": dict(Counter(
                reason for p in provenances
                for reason in (p.get("parse_confidence_reasons") or [])
            ).most_common(4)),
        })

    totals = {
        "imports": len(rows),
        "items": sum(r["items"] for r in rows),
        "gradeable": sum(r["gradeable"] for r in rows),
        "figure_ready": sum(r["figure_ready"] for r in rows),
        "answer_withheld": sum(r["answer_withheld"] for r in rows),
        "figures_attached": sum(r["figures_attached"] for r in rows),
        "confidence_unknown": sum(r["confidence_unknown"] for r in rows),
    }
    totals["gradeable_pct"] = round(100 * totals["gradeable"] / totals["items"], 1)
    totals["figure_ready_pct"] = round(100 * totals["figure_ready"] / totals["items"], 1)
    return {"totals": totals, "by_import": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Per-import past-test fidelity")
    ap.add_argument("--event", default=None)
    ap.add_argument("--json", dest="json_path", default=None)
    ap.add_argument("--limit", type=int, default=12)
    args = ap.parse_args()

    result = collect(args.event)
    t = result["totals"]
    print("=" * 78)
    print("PAST-TEST IMPORT FIDELITY (Phase 7c)")
    print("=" * 78)
    print(f"imports              : {t['imports']}")
    print(f"imported items       : {t['items']}")
    print(f"gradeable            : {t['gradeable']} ({t['gradeable_pct']}%)")
    print(f"not blocked by a missing figure: {t['figure_ready']} ({t['figure_ready_pct']}%)")
    print(f"answers withheld for review    : {t['answer_withheld']}")
    print(f"items carrying a figure        : {t['figures_attached']}")
    if t["confidence_unknown"]:
        print(f"items imported before confidence was recorded: {t['confidence_unknown']} "
              f"(counted as unknown, not as passing)")
    print("-" * 78)
    print(f"{'source':<38}{'items':>6}{'grade%':>8}{'fig%':>7}{'withheld':>10}{'conf':>7}")
    for row in result["by_import"][:args.limit]:
        conf = f"{row['mean_confidence']:.2f}" if row["mean_confidence"] is not None else "  — "
        print(f"{row['source'][:37]:<38}{row['items']:>6}{row['gradeable_pct']:>8}"
              f"{row['figure_ready_pct']:>7}{row['answer_withheld']:>10}{conf:>7}")
    if len(result["by_import"]) > args.limit:
        print(f"... and {len(result['by_import']) - args.limit} more imports not shown")
    worst = [r for r in result["by_import"] if r["gradeable_pct"] < 60]
    if worst:
        print("-" * 78)
        print(f"{len(worst)} import(s) below 60% gradeable:")
        for row in worst[:5]:
            print(f"  {row['source'][:44]:<45} {row['gradeable_pct']:>5}%  {row['top_reasons']}")
    print("=" * 78)

    if args.json_path:
        with open(args.json_path, "w") as fh:
            json.dump(result, fh, indent=2)
        print(f"wrote {args.json_path}")


if __name__ == "__main__":
    main()
