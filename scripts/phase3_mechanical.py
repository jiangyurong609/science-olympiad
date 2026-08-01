"""Phase 3 (mechanical half) — clear the `audit_course` blockers that are data plumbing.

Phase 3's gate is "zero blockers except `release_missing`". Its blockers split cleanly:

  * **mechanical** — records the pipeline should have written and didn't (retained passages,
    course/source dispositions, citation wiring, lesson duration). Fixed here, from real data.
  * **human** — editor/SME approval, calibration, source review. NOT touched. Auto-approving
    them is precisely the relabelling MASTER_PLAN operating rule 3 forbids.

Every fix here is falsifiable: a passage is only written when its text is actually present in
the retained snapshot, durations come from the lesson's own content, and citations are only
wired to passages that exist. Nothing is invented to satisfy a counter.

    PYTHONPATH=. python -m scripts.phase3_mechanical --event rocks-and-minerals-b [--apply]
"""
from __future__ import annotations

import argparse
import hashlib
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.entities import (
    Course, CourseSourceCoverage, Event, EventSourceMap, Lesson, LessonVersion,
    ScientificClaim, Skill, Source, SourcePassage, SourceSnapshot,
)

# a passage is the retained, citable neighbourhood around the evidence, not the bare sentence
PASSAGE_PAD = 400
WORDS_PER_MINUTE = 130          # silent reading of expository science prose
MIN_MINUTES, MAX_MINUTES = 5, 12


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _locate(haystack: str, needle: str) -> int:
    """Offset of `needle` in `haystack`, tolerant of whitespace differences."""
    lowered_h, lowered_n = haystack.lower(), needle.lower()
    idx = lowered_h.find(lowered_n)
    if idx >= 0:
        return idx
    collapsed = re.sub(r"\s+", " ", lowered_h)
    idx = collapsed.find(re.sub(r"\s+", " ", lowered_n))
    return idx


def materialize_passages(db: Session, claims: list[ScientificClaim], apply: bool) -> Counter:
    """Write the retained SourcePassage each claim's evidence actually came from.

    `ground_event` stored the excerpt and the snapshot but never materialized the passage, so
    every claim tripped `claim_passage_missing`. The passage is reconstructed by locating the
    excerpt in the retained snapshot text — if it is not there, the claim is not evidence and
    the blocker correctly stays.
    """
    out: Counter[str] = Counter()
    snapshots: dict[int, SourceSnapshot] = {}
    for claim in claims:
        if claim.source_passage_id:
            existing = db.get(SourcePassage, claim.source_passage_id)
            if existing is not None:
                out["already_linked"] += 1
                continue
        if not claim.source_snapshot_id:
            out["no_snapshot"] += 1
            continue
        snapshot = snapshots.get(claim.source_snapshot_id) or db.get(
            SourceSnapshot, claim.source_snapshot_id)
        if snapshot is None:
            out["no_snapshot"] += 1
            continue
        snapshots[claim.source_snapshot_id] = snapshot
        if snapshot.source_id != claim.source_id:
            out["snapshot_belongs_to_another_source"] += 1
            continue
        text = snapshot.extracted_text or ""
        excerpt = _norm(claim.evidence_excerpt)
        if not excerpt:
            out["no_excerpt"] += 1
            continue
        idx = _locate(text, excerpt)
        if idx < 0:
            out["excerpt_not_in_snapshot"] += 1
            continue

        start = max(0, idx - PASSAGE_PAD)
        end = min(len(text), idx + len(excerpt) + PASSAGE_PAD)
        passage_text = text[start:end].strip()
        locator = f"char:{start}-{end}"
        content_hash = hashlib.sha256(passage_text.encode("utf-8")).hexdigest()
        if not apply:
            out["would_create"] += 1
            continue
        # the unique key is (snapshot, locator, hash): overlapping claims reuse one passage
        passage = db.scalar(select(SourcePassage).where(
            SourcePassage.source_snapshot_id == snapshot.id,
            SourcePassage.locator == locator,
            SourcePassage.content_hash == content_hash,
        ))
        if passage is None:
            passage = SourcePassage(
                source_id=claim.source_id, source_snapshot_id=snapshot.id,
                sequence=start, locator=locator, passage_type="text",
                text=passage_text, content_hash=content_hash,
                metadata_json={"derived_from": "evidence_excerpt", "excerpt_offset": idx},
            )
            db.add(passage)
            db.flush()
        claim.source_passage_id = passage.id
        out["linked"] += 1
    return out


def reconcile_sources(db: Session, course: Course, apply: bool) -> Counter:
    """Give every mapped source an explicit course disposition.

    `source_unreconciled` means the source was mapped to the event but the course never said
    what it does with it. The disposition recorded here is factual — role and extraction
    status come from what the source actually produced — and `review_status` stays
    `unreviewed`, because that is an editor's call, not this script's.
    """
    out: Counter[str] = Counter()
    mapped = db.scalars(select(EventSourceMap).where(
        EventSourceMap.event_id == course.event_id)).all()
    have = {row.source_id for row in db.scalars(select(CourseSourceCoverage).where(
        CourseSourceCoverage.course_id == course.id)).all()}
    for row in mapped:
        if row.source_id in have:
            out["already_reconciled"] += 1
            continue
        source = db.get(Source, row.source_id)
        if source is None:
            out["missing_source"] += 1
            continue
        snapshot = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_id == source.id).order_by(SourceSnapshot.id.desc()))
        claim_rows = db.scalars(select(ScientificClaim).where(
            ScientificClaim.source_id == source.id)).all()
        passage_count = len(db.scalars(select(SourcePassage).where(
            SourcePassage.source_id == source.id)).all())
        # role follows what the source actually contributed, so the audit's
        # `source_destination` rule resolves on fact rather than on a default
        role = "reference_only" if not claim_rows else "instructional"
        if not apply:
            out["would_reconcile"] += 1
            continue
        db.add(CourseSourceCoverage(
            course_id=course.id, source_id=source.id,
            source_snapshot_id=snapshot.id if snapshot else None,
            source_type=(source.metadata_json or {}).get("source_type", ""),
            instructional_role=role,
            extraction_status="extracted" if snapshot else "not_extracted",
            rights_status=source.rights_status, passage_count=passage_count,
            claim_count=len(claim_rows), review_status="unreviewed",
            decision_reason="Auto-reconciled from extraction results; awaiting editor review.",
        ))
        out["reconciled"] += 1
    return out


def estimate_minutes(version: LessonVersion) -> int:
    words = len(re.findall(r"\w+", _flatten_text(version.content or [])))
    checks = sum(1 for b in (version.content or []) if b.get("type") == "checkpoint")
    return round(words / WORDS_PER_MINUTE + checks * 0.5)


def record_student_destinations(db: Session, course: Course, versions: dict,
                                lessons: list[Lesson], apply: bool) -> Counter:
    """Say where a student actually meets each instructional source.

    `source_destination` asks a real question — an instructional source no student ever
    reaches is a source the course only claims to use. The answer is derived, not asserted:
    a source's destination is the set of lessons whose current version cites a claim drawn
    from it. A source that reaches no lesson is demoted to `reference_only`, which is the
    truth about it rather than a way past the check.
    """
    out: Counter[str] = Counter()
    lesson_by_id = {lesson.id: lesson for lesson in lessons}
    source_to_lessons: dict[int, set[int]] = {}
    for lesson_id, version in versions.items():
        if version is None:
            continue
        for claim_id in (version.claim_ids or []):
            claim = db.get(ScientificClaim, claim_id)
            if claim is not None:
                source_to_lessons.setdefault(claim.source_id, set()).add(lesson_id)

    for row in db.scalars(select(CourseSourceCoverage).where(
        CourseSourceCoverage.course_id == course.id)).all():
        if row.student_destination or row.withdrawal_reason:
            out["already_recorded"] += 1
            continue
        if row.instructional_role in {"reference_only", "assessment_validation"}:
            out["exempt_role"] += 1
            continue
        reached = sorted(source_to_lessons.get(row.source_id, set()))
        if not reached:
            # This used to set `instructional_role = "reference_only"`, which `course_quality`
            # exempts from the `source_destination` check — so the blocker vanished without
            # anything being fixed. Adversarial review flagged it as relabelling, correctly:
            # "no lesson cites it" is evidence that the source is *unused*, not evidence about
            # what it was for. It may be an instructional source whose content was lost in a
            # regeneration, which is exactly the case worth surfacing.
            #
            # The finding is now recorded and the blocker deliberately left standing. Only a
            # reviewer can say whether this source should be connected to a lesson or withdrawn.
            out["unused_left_blocking_for_review"] += 1
            if apply:
                row.decision_reason = (
                    "No lesson in the current course version cites a claim from this source. "
                    "Its intended role is preserved; a reviewer must either connect it to "
                    "student content or withdraw it with a reason."
                )
            continue
        titles = [lesson_by_id[lid].title for lid in reached if lid in lesson_by_id]
        if apply:
            row.student_destination = "; ".join(titles)[:1024]
            row.lesson_ids = reached
        out["destination_recorded"] += 1
    return out


def fix_lesson_durations(db: Session, lessons: list[Lesson], versions: dict, apply: bool) -> Counter:
    """Set `estimated_minutes` to the lesson's real reading time — never to a passing one.

    The first version of this clamped the estimate into the rubric's 5–12 minute window, which
    would have turned a measured 23-minute lesson into a compliant-looking 12. That is the
    relabelling the plan forbids: the rubric wants lessons a student can finish, and a lesson
    that is too long has to be *split* (`scripts.split_lessons`), not re-labelled. So this
    writes the honest number and leaves `lesson_duration` blocking until the content changes.
    """
    out: Counter[str] = Counter()
    for lesson in lessons:
        version = versions.get(lesson.id)
        if version is None:
            out["no_version"] += 1
            continue
        minutes = estimate_minutes(version)
        if lesson.estimated_minutes != minutes and apply:
            lesson.estimated_minutes = minutes
        if minutes > MAX_MINUTES:
            out["too_long_needs_split"] += 1
        elif minutes < MIN_MINUTES:
            out["too_short_needs_merge"] += 1
        else:
            out["in_range"] += 1
    return out


def _flatten_text(blocks: list) -> str:
    parts: list[str] = []
    def walk(node) -> None:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key in {"type", "claim_ids", "passage_ids", "id"}:
                    continue
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(blocks)
    return " ".join(parts)


def wire_citations(db: Session, lessons: list[Lesson], versions: dict, apply: bool) -> Counter:
    """Every passage a block cites must appear in the version's citation list.

    The audit requires block `passage_ids` to be a subset of the version's `citations`. Blocks
    carry claim ids from grounding; now that those claims have passages, the block's passage
    ids and the version's citation list are both derived from the claims — one fact, recorded
    in the two places the reader and the auditor look.
    """
    from sqlalchemy.orm.attributes import flag_modified

    out: Counter[str] = Counter()
    for lesson in lessons:
        version = versions.get(lesson.id)
        if version is None:
            out["no_version"] += 1
            continue
        content = [dict(b) for b in (version.content or [])]
        citations = {row.get("source_passage_id"): dict(row)
                     for row in (version.citations or []) if isinstance(row, dict)}
        changed = False
        for block in content:
            claim_ids = block.get("claim_ids") or []
            if not claim_ids:
                continue
            passage_ids = []
            for claim_id in claim_ids:
                claim = db.get(ScientificClaim, claim_id)
                if claim is None or not claim.source_passage_id:
                    continue
                passage_ids.append(claim.source_passage_id)
                citations.setdefault(claim.source_passage_id, {
                    "source_passage_id": claim.source_passage_id,
                    "claim_id": claim.id, "source_id": claim.source_id,
                })
            passage_ids = sorted(set(passage_ids))
            if passage_ids and block.get("passage_ids") != passage_ids:
                block["passage_ids"] = passage_ids
                changed = True
        # a block may cite a passage the version has not listed; that is the audit's failure
        # mode, so rebuild the list from what the blocks actually reference
        cited = {p for b in content for p in (b.get("passage_ids") or [])}
        rebuilt = [citations[p] for p in sorted(cited) if p in citations]
        if changed or [r.get("source_passage_id") for r in (version.citations or [])] != \
                [r.get("source_passage_id") for r in rebuilt]:
            if apply:
                version.content = content
                version.citations = rebuilt
                flag_modified(version, "content")
                flag_modified(version, "citations")
            out["rewired"] += 1
        else:
            out["already_consistent"] += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Clear mechanical Phase 3 blockers")
    ap.add_argument("--event", required=True)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    from app.services.course_quality import audit_course

    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == args.event))
        if not event:
            raise SystemExit(f"unknown event {args.event!r}")
        course = db.scalar(select(Course).where(Course.event_id == event.id))
        if not course:
            raise SystemExit(f"{args.event} has no course")

        before = audit_course(db, course.id)
        skills = db.scalars(select(Skill).where(
            Skill.course_id == course.id, Skill.status != "withdrawn")).all()
        claims = db.scalars(select(ScientificClaim).where(
            ScientificClaim.skill_id.in_([s.id for s in skills]))).all() if skills else []
        lessons = db.scalars(select(Lesson).where(
            Lesson.event_id == event.id, Lesson.status != "withdrawn")).all()
        versions = {}
        for lesson in lessons:
            versions[lesson.id] = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version))

        mode = "APPLY" if args.apply else "DRY RUN"
        print("=" * 72)
        print(f"PHASE 3 MECHANICAL — {course.slug} [{mode}]")
        print("=" * 72)
        print(f"blockers before: {before['counts']['blockers']}")

        print("\n1. retained passages for claims")
        for key, count in materialize_passages(db, claims, args.apply).most_common():
            print(f"   {key:34} {count}")
        db.flush()

        print("\n2. course/source dispositions")
        for key, count in reconcile_sources(db, course, args.apply).most_common():
            print(f"   {key:34} {count}")

        print("\n2b. student destinations for instructional sources")
        for key, count in record_student_destinations(
                db, course, versions, lessons, args.apply).most_common():
            print(f"   {key:34} {count}")

        print("\n3. lesson durations")
        for key, count in fix_lesson_durations(db, lessons, versions, args.apply).most_common():
            print(f"   {key:34} {count}")

        print("\n4. citation wiring")
        for key, count in wire_citations(db, lessons, versions, args.apply).most_common():
            print(f"   {key:34} {count}")

        if args.apply:
            db.commit()
            after = audit_course(db, course.id)
            print(f"\nblockers after: {after['counts']['blockers']} "
                  f"(was {before['counts']['blockers']})")
            print("remaining by code:")
            for code, count in sorted(after["blocker_counts"].items(),
                                      key=lambda kv: -kv[1]):
                human = code in {"lesson_review", "question_review", "question_calibration",
                                 "source_review", "content_gap", "release_missing"}
                print(f"   {code:28} {count:5}  {'← human decision' if human else ''}")
        else:
            db.rollback()
            print("\ndry run — nothing written. re-run with --apply")


if __name__ == "__main__":
    main()
