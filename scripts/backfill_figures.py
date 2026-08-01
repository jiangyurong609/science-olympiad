"""Phase 7a — attach recovered figures to items that were imported before recovery existed.

`is_figure_missing` excludes an item from scoring when it names a figure it does not have.
43 imported items are in that state: the question parsed fine, the diagram it refers to was
discarded because import read only extracted text. The PDF bytes were retained, so the figure
can be put back without re-importing — which matters, because re-importing would re-parse the
items and produce duplicates alongside the originals.

The same anchoring rules apply as at import time, and for the same reason: an item is only
given a figure when the document ties them together (`label_matched`) or when the item
references a figure and is alone on its page with exactly one (`sole_on_page`). Everything
else is recorded as a candidate for review and nothing is attached. A wrong figure is worse
than a missing one — the student answers confidently about the wrong picture.

Nothing here publishes, approves, or changes any review state. It supplies missing media to
items that already exist at their current status.

**Measured result on this catalog: 0 of 43 recovered, and that is the correct answer.**
The run is kept because the breakdown is the finding:

  * 17 items — their source predates byte retention, so there is nothing to extract from;
  * 14 — located on a page that holds no extractable figure;
  * 11 — stem not locatable in the source text, because import rewrites stems to read
    standalone while the printed labels do not survive extraction at line starts;
  *  1 — ambiguous.

Inspecting the documents explains it. Science Olympiad tests reference images that are largely
**vector drawings**, which `page.images` cannot see — one exam references 21 images and yields
2 rasters — and they place them on a **separate image sheet**, so a question on page 2 refers
to a figure on page 5. Neither page adjacency nor an ordinal "Image N is the Nth figure"
mapping is supported: across three documents the label counts (21, 18, 3) and extracted figure
counts (2, 25, 13) do not correspond at all.

Recovering these needs vector-region rendering and caption OCR, not a better heuristic over
the rasters. Forcing an ordinal pairing would produce exactly the confident-but-unverified
attachment this pipeline is built to refuse.

    PYTHONPATH=. python -m scripts.backfill_figures            # dry run
    PYTHONPATH=. python -m scripts.backfill_figures --apply
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.entities import Question, Source, SourceSnapshot
from app.services.past_test_import import _retained_bytes, _store_figure
from app.services.pdf_figures import (
    RESOLVING_MATCHES, attach_figures_to_items, extract_figures,
)
from app.services.scoring import is_figure_missing


def backfill(apply: bool) -> dict:
    outcomes: Counter[str] = Counter()
    recovered: list[dict] = []

    with SessionLocal() as db:
        questions = db.scalars(select(Question).where(
            Question.generation_provenance["import_kind"].as_string() == "past_test"
        )).all()
        blocked = [q for q in questions if is_figure_missing(q.stem, q.assets)]
        outcomes["blocked_at_start"] = len(blocked)
        if not blocked:
            raise SystemExit(
                "FAIL: no imported item is blocked by a missing figure. An empty population "
                "is a signal that the query is wrong, not that the work is done."
            )

        by_source: dict[int, list[Question]] = {}
        for question in blocked:
            source_id = (question.generation_provenance or {}).get("exam_source_id")
            if source_id:
                by_source.setdefault(source_id, []).append(question)
            else:
                outcomes["no_source_recorded"] += 1

        for source_id, group in sorted(by_source.items()):
            source = db.get(Source, source_id)
            snapshot = db.scalar(select(SourceSnapshot).where(
                SourceSnapshot.source_id == source_id
            ).order_by(SourceSnapshot.id.desc()))
            if source is None or snapshot is None:
                outcomes["source_or_snapshot_missing"] += len(group)
                continue
            raw = _retained_bytes(db, source, snapshot)
            if not raw:
                outcomes["no_retained_bytes"] += len(group)
                continue
            try:
                report = extract_figures(raw)
            except Exception as exc:
                outcomes[f"extraction_failed:{type(exc).__name__}"] += len(group)
                continue
            if not report.figures:
                outcomes["pdf_had_no_usable_figure"] += len(group)
                continue

            # rebuild the item shape the attacher expects, from the stored question
            items = [{
                "stem": question.stem,
                "label": (question.generation_provenance or {}).get("label", ""),
                "image_dependent": True,
            } for question in group]
            attach_figures_to_items(snapshot.extracted_text or "", items, report.figures)

            stored: dict[str, str] = {}
            for question, item in zip(group, items):
                match = item.get("figure_match")
                outcomes[f"match:{match}"] += 1
                if match not in RESOLVING_MATCHES or not item.get("figures"):
                    continue
                if apply:
                    for figure in report.figures:
                        if figure.sha256 not in stored:
                            stored[figure.sha256] = _store_figure(source, snapshot, figure)
                        figure.storage_key = stored[figure.sha256]
                    question.assets = [
                        dict(descriptor,
                             storage_key=stored.get(descriptor["sha256"], ""))
                        for descriptor in item["figures"]
                    ]
                    flag_modified(question, "assets")
                    provenance = dict(question.generation_provenance or {})
                    provenance.update({
                        "figure_backfilled": True,
                        "figure_match": match,
                        "source_page": item.get("page"),
                    })
                    question.generation_provenance = provenance
                    flag_modified(question, "generation_provenance")
                outcomes["recovered"] += 1
                recovered.append({"question_id": question.id, "match": match,
                                  "source": source.title[:40], "page": item.get("page")})

        if apply:
            db.commit()
        else:
            db.rollback()

        # measure the real effect rather than trusting the counter
        if apply:
            still = [q for q in db.scalars(select(Question).where(
                Question.generation_provenance["import_kind"].as_string() == "past_test"
            )).all() if is_figure_missing(q.stem, q.assets)]
            outcomes["blocked_after"] = len(still)
    return {"outcomes": outcomes, "recovered": recovered}


def main() -> None:
    ap = argparse.ArgumentParser(description="Attach recovered figures to blocked items")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    result = backfill(args.apply)
    outcomes = result["outcomes"]
    print("=" * 72)
    print(f"FIGURE BACKFILL [{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 72)
    for key, count in sorted(outcomes.items()):
        print(f"  {key:34} {count}")
    if result["recovered"]:
        print("-" * 72)
        for row in result["recovered"][:15]:
            print(f"  q{row['question_id']:<6} {row['match']:<14} p{row['page']}  "
                  f"{row['source']}")
        if len(result["recovered"]) > 15:
            print(f"  ... and {len(result['recovered']) - 15} more")
    if not args.apply:
        print("-" * 72)
        print("dry run — nothing written. re-run with --apply")
    print("=" * 72)


if __name__ == "__main__":
    main()
