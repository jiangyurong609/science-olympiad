"""Phase Q — catalog-wide course quality scorecard.

Runs the existing machine-checkable course rubric (`course_quality.audit_course`)
over EVERY course and produces a fleet rollup: how many courses are release-ready,
the blocker histogram across the catalog, and the worst offenders first. This is
the honest catalog baseline the gap-closure plan is judged against
(docs/HONEN_GAP_CLOSURE_PLAN.md, Phase Q).

Read-only. Never mutates content.

Usage:
    PYTHONPATH=. python -m scripts.audit_catalog_quality
    PYTHONPATH=. python -m scripts.audit_catalog_quality --json docs/history/catalog_quality_<date>.json
    PYTHONPATH=. python -m scripts.audit_catalog_quality --status published   # only published courses
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Course, Event
from app.services.course_quality import audit_course


# Courses in these statuses, or attached to an inactive event, are NOT part of the live
# catalog and are excluded from the quality gate by default (R-C8). `--archive` audits them.
NON_LIVE_STATUSES = {"retired_duplicate", "withdrawn", "archived_superseded"}


def _is_live(course: Course, events: dict) -> bool:
    if course.status in NON_LIVE_STATUSES:
        return False
    ev = events.get(course.event_id)
    if ev is not None and not ev.active:
        return False
    return True


def run(status: str | None = None, archive: bool = False) -> dict:
    with SessionLocal() as db:
        events = {e.id: e for e in db.scalars(select(Event)).all()}
        query = select(Course)
        if status:
            query = query.where(Course.status == status)
        all_courses = db.scalars(query.order_by(Course.id)).all()

        # By default audit the LIVE catalog; --archive audits only the non-live remainder.
        if status:
            courses = all_courses
        elif archive:
            courses = [c for c in all_courses if not _is_live(c, events)]
        else:
            courses = [c for c in all_courses if _is_live(c, events)]

        per_course = []
        blocker_histogram: Counter[str] = Counter()
        audited = 0
        errored = 0
        release_ready = 0

        for course in courses:
            event = events.get(course.event_id)
            label = {
                "course_id": course.id,
                "slug": course.slug,
                "title": course.title,
                "status": course.status,
                "event_id": course.event_id,
                "event_slug": getattr(event, "slug", None),
                "season": getattr(event, "season", None),
                "division": getattr(event, "division", None),
            }
            try:
                report = audit_course(db, course.id)
            except Exception as exc:  # a schema/data gap shouldn't sink the whole sweep
                errored += 1
                per_course.append({**label, "audit_error": f"{type(exc).__name__}: {exc}"})
                continue

            audited += 1
            if report["release_ready"]:
                release_ready += 1
            blocker_histogram.update(report["blocker_counts"])
            per_course.append({
                **label,
                "release_ready": report["release_ready"],
                "blocker_total": report["counts"]["blockers"],
                "blocker_counts": report["blocker_counts"],
                "counts": report["counts"],
            })

        # Worst offenders first (most blockers); ready courses and errors sort to the ends.
        def sort_key(row: dict):
            if "audit_error" in row:
                return (-1, 0)  # errors first — they need a look
            return (0, -row.get("blocker_total", 0))

        per_course.sort(key=sort_key)

        # Denominator = every selected course (R-C8): an audit error counts as
        # not-release-ready and stays in the denominator, so a failure can never *raise*
        # the headline pass rate. Population assertion: default runs exclude non-live courses.
        selected = len(courses)
        if not status and not archive:
            leaked = [c.id for c in courses if not _is_live(c, events)]
            assert not leaked, f"live scorecard leaked non-live courses: {leaked}"

        return {
            "generated_at": None,  # stamped by caller/CI; Date.now unavailable here by policy
            "filter_status": status,
            "population": "archive" if archive else ("status:" + status if status else "live"),
            "totals": {
                "courses": selected,
                "audited": audited,
                "errored": errored,
                "release_ready": release_ready,
                # errored courses are NOT release-ready:
                "not_release_ready": selected - release_ready,
                "release_ready_pct": round(100 * release_ready / selected, 1) if selected else 0.0,
            },
            "blocker_histogram": dict(blocker_histogram.most_common()),
            "courses": per_course,
        }


def _print_summary(result: dict) -> None:
    t = result["totals"]
    print("=" * 72)
    print("CATALOG QUALITY SCORECARD (Phase Q baseline)")
    print(f"population: {result['population']}")
    print("=" * 72)
    print(f"courses (selected) : {t['courses']}")
    print(f"audited            : {t['audited']}  (errored: {t['errored']} — counted NOT ready)")
    print(f"release_ready      : {t['release_ready']} / {t['courses']}  ({t['release_ready_pct']}%)")
    print(f"NOT release_ready  : {t['not_release_ready']}")
    print("-" * 72)
    print("Top blocker codes across the catalog:")
    for code, n in list(result["blocker_histogram"].items())[:15]:
        print(f"  {n:>5}  {code}")
    print("-" * 72)
    print("Worst offenders (most blockers first):")
    for row in result["courses"][:12]:
        if "audit_error" in row:
            print(f"  [ERR] {row['slug']}: {row['audit_error']}")
            continue
        ready = "OK " if row["release_ready"] else "    "
        print(f"  [{ready}] {row['blocker_total']:>3} blockers  {row['slug']}  ({row['status']})")
    print("=" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(description="Catalog-wide course quality scorecard")
    parser.add_argument("--status", default=None, help="only audit courses with this status")
    parser.add_argument("--archive", action="store_true",
                        help="audit ONLY non-live (archived/retired/inactive-event) courses")
    parser.add_argument("--json", dest="json_path", default=None, help="write full report to this path")
    args = parser.parse_args()

    result = run(status=args.status, archive=args.archive)
    _print_summary(result)

    if args.json_path:
        with open(args.json_path, "w") as fh:
            json.dump(result, fh, indent=2)
        print(f"\nWrote full report -> {args.json_path}")


if __name__ == "__main__":
    main()
