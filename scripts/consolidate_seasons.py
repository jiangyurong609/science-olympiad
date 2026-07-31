"""Phase C — consolidate the 2026 + 2027 catalogs into one season-agnostic catalog.

Decided model (see docs/HONEN_GAP_CLOSURE_PLAN.md, Phase C):
  * ONE canonical, ACTIVE event per (normalized name, division).
  * Recurring (both seasons): canonical = the 2026 event (it holds the real course +
    content). Carry current-season metadata from the 2027 twin, merge the twin's
    EventSourceMap rows (dedup), then ARCHIVE the 2027 twin + its subordinate content.
  * only-2027: keep as current.
  * only-2026: mark season_status="prior_season_practice" (kept as practice).

Honest scope: this does NOT claim "zero content loss." It preserves all *live/published*
content on canonical events, and it ARCHIVES the redundant 2027 import stubs — they stay in
the DB, queryable via season_status, and recoverable, but are removed from the live catalog.
The apply path REFUSES to retire a twin that carries any published content, and BLOCKS on any
event-dependent table it has not explicitly classified (so schema growth can't silently drop
rows). A post-apply invariant asserts exactly one active event per (name, division).

Hard constraint: uq_course_event => at most ONE course per event.

DRY-RUN BY DEFAULT. `--apply` runs in one transaction; requires --i-took-a-backup and a clean
conflict report. `--resolve-intra-season` archives same-season duplicates (smaller by question
count) into the richer sibling instead of blocking on them.

Usage:
    PYTHONPATH=. python -m scripts.consolidate_seasons --json docs/history/consolidation_plan.json
    PYTHONPATH=. python -m scripts.consolidate_seasons --resolve-intra-season --apply --i-took-a-backup
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Course, Event, EventSourceMap, EventTaxonScope, Exam, Lesson, PracticeSet,
    Question,
)

CURRENT_SEASON = 2027
PRIOR_SEASON = 2026
PRIOR_STATUS = "prior_season_practice"
ARCHIVED_STATUS = "archived_superseded"

# Every model that carries a hard event_id FK to a *content* surface. If a twin has rows in
# a table NOT listed here, apply BLOCKS (unclassified) so schema growth cannot silently drop.
# disposition: "merge" = re-point to canonical; "archive" = retire with the twin (queryable).
EVENT_DEPENDENT = {
    "EventSourceMap": (EventSourceMap, "merge"),
    "Concept": (Concept, "archive"),
    "Course": (Course, "archive"),
    "Lesson": (Lesson, "archive"),
    "Question": (Question, "archive"),
    "PracticeSet": (PracticeSet, "archive"),
    "EventTaxonScope": (EventTaxonScope, "archive"),
    "Exam": (Exam, "archive"),
}


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _q(db: Session, model, event_id: int) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.event_id == event_id)) or 0


def _live_content(db: Session, event_id: int) -> dict:
    """Every kind of student-visible row on an event (R-C5) — not just lessons/questions.
    Archival is refused if ANY of these is > 0."""
    return {
        "published_lessons": db.scalar(
            select(func.count(Lesson.id)).where(Lesson.event_id == event_id, Lesson.status == "published")
        ) or 0,
        "published_questions": db.scalar(
            select(func.count(Question.id)).where(Question.event_id == event_id, Question.status == "published")
        ) or 0,
        "published_courses": db.scalar(
            select(func.count(Course.id)).where(Course.event_id == event_id, Course.status == "published")
        ) or 0,
        "published_exams": db.scalar(
            select(func.count(Exam.id)).where(Exam.event_id == event_id, Exam.published.is_(True))
        ) or 0,
        "published_practice_sets": db.scalar(
            select(func.count(PracticeSet.id)).where(PracticeSet.event_id == event_id, PracticeSet.status == "published")
        ) or 0,
    }


def _has_live_content(inv: dict) -> bool:
    return any(v > 0 for v in inv.values())


def _dependent_inventory(db: Session, event_id: int) -> dict:
    return {name: _q(db, model, event_id) for name, (model, _) in EVENT_DEPENDENT.items()}


def _richest(db: Session, events: list[Event]) -> tuple[Event, list[Event]]:
    """Return (canonical, [others]) picking the event with the most questions."""
    ranked = sorted(events, key=lambda e: _q(db, Question, e.id), reverse=True)
    return ranked[0], ranked[1:]


def build_plan(db: Session, resolve_intra: bool) -> dict:
    events = db.scalars(select(Event)).all()
    # (name, division) -> season -> [events]. Already-archived events are excluded from
    # planning (they've been resolved, e.g. via merge_events) so they don't re-trigger conflicts.
    groups: dict[tuple, dict[int, list[Event]]] = defaultdict(lambda: defaultdict(list))
    for e in events:
        if e.season_status == ARCHIVED_STATUS:
            continue
        groups[(norm(e.name), e.division)][e.season].append(e)

    recurring, only_prior, only_current = [], [], []
    conflicts: list[dict] = []
    intra_archived: list[dict] = []  # same-season dups archived into their richer sibling

    for (name, division), by_season in groups.items():
        # 1) intra-season duplicate handling (Codex #1)
        collapsed: dict[int, Event] = {}
        for season, evs in by_season.items():
            if len(evs) == 1:
                collapsed[season] = evs[0]
            elif resolve_intra:
                canon, extras = _richest(db, evs)
                collapsed[season] = canon
                for x in extras:
                    pub = _live_content(db, x.id)
                    if _has_live_content(pub):
                        conflicts.append({
                            "key": [name, division],
                            "issue": "intra-season duplicate has live/published content; refusing to archive",
                            "event_id": x.id, "slug": x.slug, "live_content": pub,
                        })
                    intra_archived.append({
                        "key": [name, division], "season": season,
                        "archive_event_id": x.id, "archive_slug": x.slug,
                        "into_event_id": canon.id, "into_slug": canon.slug,
                        "inventory": _dependent_inventory(db, x.id),
                    })
            else:
                conflicts.append({
                    "key": [name, division],
                    "issue": f"{len(evs)} events share (name,division,season={season}) — "
                             f"pass --resolve-intra-season or clean up the data",
                    "event_ids": [e.id for e in evs],
                    "slugs": [e.slug for e in evs],
                })
                collapsed[season] = _richest(db, evs)[0]  # best-effort for the report only

        prior = collapsed.get(PRIOR_SEASON)
        current = collapsed.get(CURRENT_SEASON)

        if prior and current:
            # R-C7: the canonical must itself be active, else archiving the twin empties the key.
            if not prior.active:
                conflicts.append({
                    "key": [name, division],
                    "issue": "canonical (2026) event is inactive; archiving the twin would leave "
                             "zero active events for this key",
                    "canonical_event_id": prior.id, "canonical_slug": prior.slug,
                })
            twin_inv = _dependent_inventory(db, current.id)
            twin_pub = _live_content(db, current.id)
            if _has_live_content(twin_pub):
                conflicts.append({
                    "key": [name, division],
                    "issue": "2027 twin carries live/published content; refusing to archive it",
                    "twin_event_id": current.id, "twin_slug": current.slug, "live_content": twin_pub,
                })
            unclassified = _unclassified_event_tables(db, current.id)
            if unclassified:
                conflicts.append({
                    "key": [name, division],
                    "issue": "twin has rows in unclassified event-dependent table(s)",
                    "twin_event_id": current.id, "tables": unclassified,
                })
            canon_keys = {
                (m.source_id, m.purpose, m.source_universe_version)
                for m in db.scalars(select(EventSourceMap).where(EventSourceMap.event_id == prior.id))
            }
            twin_maps = db.scalars(select(EventSourceMap).where(EventSourceMap.event_id == current.id)).all()
            to_move = [m for m in twin_maps if (m.source_id, m.purpose, m.source_universe_version) not in canon_keys]
            recurring.append({
                "key": [name, division],
                "canonical_event_id": prior.id, "canonical_slug": prior.slug,
                "archive_event_id": current.id, "archive_slug": current.slug,
                "carry_metadata": {
                    "official_url": current.official_url or prior.official_url,
                    "category": current.category or prior.category,
                    "season_status": "current",
                },
                "source_maps_move": len(to_move), "source_maps_dup_skip": len(twin_maps) - len(to_move),
                "twin_inventory_archived": twin_inv,   # explicit: what gets archived (Codex #2)
                "canonical_questions": _q(db, Question, prior.id),
            })
        elif prior:
            only_prior.append({
                "key": [name, division], "event_id": prior.id, "slug": prior.slug,
                "action": f"season_status -> {PRIOR_STATUS}",
            })
        elif current:
            only_current.append({
                "key": [name, division], "event_id": current.id, "slug": current.slug,
                "action": "keep current (needs content)",
            })

    return {
        "summary": {
            "events_before": len(events),
            "canonical_active_after": len(recurring) + len(only_prior) + len(only_current),
            "recurring_merged": len(recurring),
            "only_2026_prior_practice": len(only_prior),
            "only_2027_current": len(only_current),
            "twins_archived": len(recurring),
            "intra_season_dups_archived": len(intra_archived),
            "source_maps_to_move": sum(r["source_maps_move"] for r in recurring),
            "conflicts": len(conflicts),
            "content_archived_totals": _sum_inventories(
                [r["twin_inventory_archived"] for r in recurring]
                + [a["inventory"] for a in intra_archived]
            ),
            "total_questions": db.scalar(select(func.count(Question.id))) or 0,
            "total_lessons": db.scalar(select(func.count(Lesson.id))) or 0,
            "total_exams": db.scalar(select(func.count(Exam.id))) or 0,
        },
        "conflicts": conflicts,
        "recurring": recurring,
        "intra_season_archived": intra_archived,
        "only_2026_prior_practice": only_prior,
        "only_2027_current": only_current,
    }


def _sum_inventories(invs: list[dict]) -> dict:
    total: dict[str, int] = defaultdict(int)
    for inv in invs:
        for k, v in inv.items():
            total[k] += v
    return dict(total)


# Tables (by __tablename__) we have NOT classified but that carry a non-null event_id.
# If a twin has rows in one, apply blocks. Kept minimal + data-driven against the mapper.
_CLASSIFIED_TABLES = {m.__tablename__ for m, _ in EVENT_DEPENDENT.values()}


def _unclassified_event_tables(db: Session, event_id: int) -> list[str]:
    """Any mapped table with a NOT-NULL event_id column carrying rows for this event that we
    have not classified. Guards against silently dropping rows when the schema grows."""
    from app.models.entities import Base
    found = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table = cls.__tablename__
        if table in _CLASSIFIED_TABLES:
            continue
        col = cls.__table__.columns.get("event_id")
        if col is None or col.nullable:
            continue  # nullable event refs (uploads/feedback/assignments) handled separately
        if (db.scalar(select(func.count()).select_from(cls).where(cls.event_id == event_id)) or 0) > 0:
            found.append(table)
    return found


def _archive_event(db: Session, event_id: int, reason: str) -> None:
    ev = db.get(Event, event_id)
    ev.active = False
    ev.season_status = ARCHIVED_STATUS
    for c in db.scalars(select(Course).where(Course.event_id == event_id)).all():
        c.status = ARCHIVED_STATUS
    # subordinate content stays attached to the archived event (queryable + recoverable);
    # it is removed from the live catalog because the event is inactive + archived-status.


def merge_events(db: Session, keep_id: int, drop_id: int) -> dict:
    """Merge a same-key duplicate event: re-point `drop`'s content onto `keep` (nothing hidden),
    then archive the now-empty `drop`. Slug-unique tables (Lesson/PracticeSet/EventTaxonScope)
    get a `-merged-<drop_id>` suffix on collision. `keep`'s single course is preserved
    (uq_course_event); `drop`'s course is archived. Returns a conservation report."""
    keep = db.get(Event, keep_id)
    drop = db.get(Event, drop_id)
    if not keep or not drop:
        raise SystemExit(f"merge_events: unknown event id(s) keep={keep_id} drop={drop_id}")

    before = {
        "questions": _q(db, Question, keep_id) + _q(db, Question, drop_id),
        "lessons": _q(db, Lesson, keep_id) + _q(db, Lesson, drop_id),
        "exams": _q(db, Exam, keep_id) + _q(db, Exam, drop_id),
    }

    # direct re-point (no per-event uniqueness)
    for model in (Concept, Question, Exam):
        for row in db.scalars(select(model).where(model.event_id == drop_id)).all():
            row.event_id = keep_id

    # slug-unique re-point (suffix on collision)
    for model in (Lesson, PracticeSet):
        keep_slugs = {r.slug for r in db.scalars(select(model).where(model.event_id == keep_id)).all()}
        for row in db.scalars(select(model).where(model.event_id == drop_id)).all():
            if row.slug in keep_slugs:
                row.slug = f"{row.slug}-merged-{drop_id}"
            keep_slugs.add(row.slug)
            row.event_id = keep_id

    # taxon scopes (uq event_id,taxon_id,list_version) — re-point unless it would collide
    keep_scope_keys = {
        (s.taxon_id, s.list_version)
        for s in db.scalars(select(EventTaxonScope).where(EventTaxonScope.event_id == keep_id)).all()
    }
    for s in db.scalars(select(EventTaxonScope).where(EventTaxonScope.event_id == drop_id)).all():
        if (s.taxon_id, s.list_version) not in keep_scope_keys:
            s.event_id = keep_id  # else leave on drop (archived) to avoid a uq violation

    # source maps (dedup on the uq tuple)
    keep_src = {
        (m.source_id, m.purpose, m.source_universe_version)
        for m in db.scalars(select(EventSourceMap).where(EventSourceMap.event_id == keep_id)).all()
    }
    for m in db.scalars(select(EventSourceMap).where(EventSourceMap.event_id == drop_id)).all():
        if (m.source_id, m.purpose, m.source_universe_version) not in keep_src:
            m.event_id = keep_id

    _archive_event(db, drop_id, f"merged into {keep_id}")
    db.flush()

    after = {
        "questions": _q(db, Question, keep_id),
        "lessons": _q(db, Lesson, keep_id),
        "exams": _q(db, Exam, keep_id),
    }
    # nothing lost: every live row now lives on `keep`
    for k in before:
        if after[k] != before[k]:
            raise SystemExit(f"merge_events conservation failed for {k}: {before[k]} -> {after[k]}")
    # targeted invariant: this key now has exactly one active event (the rest of the catalog
    # may still be unconsolidated, so we do NOT assert the global invariant here).
    key = (norm(keep.name), keep.division)
    active_here = sum(
        1 for e in db.scalars(select(Event)).all()
        if (norm(e.name), e.division) == key and e.active and e.season_status != ARCHIVED_STATUS
    )
    if active_here != 1:
        raise SystemExit(f"merge_events: key {key} has {active_here} active events after merge (want 1)")
    db.commit()
    return {"keep_id": keep_id, "drop_id": drop_id, "before": before, "after": after}


def apply_plan(db: Session, plan: dict) -> None:
    for r in plan["recurring"]:
        canon = db.get(Event, r["canonical_event_id"])
        twin = db.get(Event, r["archive_event_id"])
        canon.official_url = r["carry_metadata"]["official_url"]
        canon.category = r["carry_metadata"]["category"]
        canon.season_status = "current"
        canon_keys = {
            (m.source_id, m.purpose, m.source_universe_version)
            for m in db.scalars(select(EventSourceMap).where(EventSourceMap.event_id == canon.id))
        }
        for m in db.scalars(select(EventSourceMap).where(EventSourceMap.event_id == twin.id)).all():
            if (m.source_id, m.purpose, m.source_universe_version) not in canon_keys:
                m.event_id = canon.id
        _archive_event(db, twin.id, "superseded 2027 import stub")
    for a in plan["intra_season_archived"]:
        _archive_event(db, a["archive_event_id"], "intra-season duplicate")
    for p in plan["only_2026_prior_practice"]:
        db.get(Event, p["event_id"]).season_status = PRIOR_STATUS
    db.flush()
    _assert_invariant(db)
    db.commit()


def _assert_invariant(db: Session) -> None:
    """EXACTLY ONE active, non-archived event per (name,division) that exists in the catalog
    (R-C7). Rejects both duplicates (>1) AND emptied keys (0) — the latter catches archiving a
    twin whose canonical was already inactive."""
    all_events = db.scalars(select(Event)).all()
    expected_keys = {(norm(e.name), e.division) for e in all_events}
    active_counts: dict[tuple, int] = defaultdict(int)
    for e in all_events:
        if e.active and e.season_status != ARCHIVED_STATUS:
            active_counts[(norm(e.name), e.division)] += 1
    bad = {k: active_counts.get(k, 0) for k in expected_keys if active_counts.get(k, 0) != 1}
    if bad:
        raise SystemExit(
            f"INVARIANT FAILED: {len(bad)} (name,division) key(s) do not have exactly one active "
            f"event (0=emptied, >1=duplicate): {bad}"
        )


def _print(plan: dict) -> None:
    s = plan["summary"]
    print("=" * 74)
    print("SEASON CONSOLIDATION PLAN (Phase C)  —  DRY-RUN unless --apply")
    print("=" * 74)
    for k in ("events_before", "canonical_active_after", "recurring_merged",
              "only_2026_prior_practice", "only_2027_current", "twins_archived",
              "intra_season_dups_archived", "source_maps_to_move", "conflicts",
              "total_questions", "total_lessons", "total_exams"):
        print(f"  {k:30}: {s[k]}")
    print(f"  content_archived_totals       : {s['content_archived_totals']}")
    if plan["conflicts"]:
        print("-" * 74)
        print(f"CONFLICTS ({len(plan['conflicts'])}) — apply is BLOCKED until resolved:")
        for c in plan["conflicts"][:20]:
            print(f"  ! {c['key']}: {c['issue']}  {c.get('slugs') or c.get('slug') or ''}")
    print("=" * 74)


def main() -> None:
    ap = argparse.ArgumentParser(description="Consolidate 2026+2027 into one catalog")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--i-took-a-backup", action="store_true", help="required with --apply")
    ap.add_argument("--resolve-intra-season", action="store_true",
                    help="archive same-season duplicates into their richer sibling instead of blocking")
    ap.add_argument("--archive-surface-ready", action="store_true",
                    help="assert the R-C6 archive listing/detail surface + canonical redirects are "
                         "deployed and tested; required to actually --apply")
    ap.add_argument("--merge", nargs=2, type=int, metavar=("KEEP", "DROP"),
                    help="merge duplicate event DROP into KEEP (re-point content, archive DROP), "
                         "then exit; requires --i-took-a-backup")
    ap.add_argument("--json", dest="json_path", default=None)
    args = ap.parse_args()

    if args.merge:
        if not args.i_took_a_backup:
            raise SystemExit("Refusing --merge without --i-took-a-backup.")
        keep_id, drop_id = args.merge
        with SessionLocal() as db:
            report = merge_events(db, keep_id, drop_id)
        print(f"MERGED {drop_id} -> {keep_id}: {report['before']} conserved. "
              f"{drop_id} archived. Re-run the dry-run to confirm the duplicate is gone.")
        return

    with SessionLocal() as db:
        plan = build_plan(db, resolve_intra=args.resolve_intra_season)
        _print(plan)
        if args.json_path:
            with open(args.json_path, "w") as fh:
                json.dump(plan, fh, indent=2)
            print(f"\nWrote full plan -> {args.json_path}")
        if args.apply:
            if not args.i_took_a_backup:
                raise SystemExit("Refusing --apply without --i-took-a-backup.")
            if not args.archive_surface_ready:
                raise SystemExit(
                    "Refusing --apply: archiving removes courses from live discovery, so the "
                    "R-C6 archive listing/detail surface + canonical redirects must exist and be "
                    "tested first. Re-run with --archive-surface-ready once they do."
                )
            if plan["conflicts"]:
                raise SystemExit(f"Refusing --apply: {len(plan['conflicts'])} conflict(s) — resolve first.")
            apply_plan(db, plan)
            print("\nAPPLIED + invariant passed. Re-run the Phase Q scorecard on the consolidated catalog.")


if __name__ == "__main__":
    main()
