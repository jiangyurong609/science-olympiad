"""Phase 1a — the grounding audit must be honest before its percentage becomes a gate."""
from __future__ import annotations

import itertools

import pytest

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Course, Event, Lesson, LessonVersion, ScientificClaim, Skill, Source,
    SourceSnapshot,
)
from scripts.audit_grounding import audit_event, claim_is_valid, run

EXCERPT = "Minerals are identified by hardness, streak, and luster."
SNAPSHOT_TEXT = f"Some preamble. {EXCERPT} Some trailing text."
_UNIQUE = itertools.count(1)   # id() collides: identical default strings are interned


def _event(db, slug="rocks-and-minerals-b"):
    e = Event(slug=slug, name="Rocks and Minerals", division="B", season=2026)
    db.add(e); db.flush()
    return e


def _claim(db, event, *, rights="public_domain", approved_source=True, approved=True,
           excerpt=EXCERPT, snapshot_text=SNAPSHOT_TEXT, with_snapshot=True):
    src = Source(url=f"https://sci.gov/ref-{next(_UNIQUE)}", title="Ref",
                 rights_status=rights, approved=approved_source)
    db.add(src); db.flush()
    snap_id = None
    if with_snapshot:
        snap = SourceSnapshot(source_id=src.id, final_url=src.url, content_hash="h",
                              extracted_text=snapshot_text)
        db.add(snap); db.flush()
        snap_id = snap.id
    concept = Concept(event_id=event.id, name="Identification")
    db.add(concept); db.flush()
    claim = ScientificClaim(source_id=src.id, source_snapshot_id=snap_id,
                            concept_id=concept.id, claim_text="Minerals are identified by properties.",
                            evidence_excerpt=excerpt, approved=approved)
    db.add(claim); db.flush()
    return claim


def _lesson(db, event, blocks, claim_ids=()):
    lesson = Lesson(event_id=event.id, slug=f"lesson-{next(_UNIQUE)}", title="Lesson",
                    status="published", current_version=1)
    db.add(lesson); db.flush()
    db.add(LessonVersion(lesson_id=lesson.id, version=1, content=blocks,
                         claim_ids=list(claim_ids)))
    db.flush()
    return lesson


# ---------------------------------------------------------------- claim validity

def test_a_claim_is_evidence_only_when_its_excerpt_is_really_in_the_snapshot():
    with SessionLocal() as db:
        e = _event(db)
        good = _claim(db, e)
        fabricated = _claim(db, e, excerpt="A sentence that never appears in the source.")
        db.commit()
        assert claim_is_valid(db, good, {})[0] is True
        ok, reason = claim_is_valid(db, fabricated, {})
        assert not ok and reason == "excerpt_not_in_snapshot"


@pytest.mark.parametrize("kwargs,reason", [
    ({"approved": False}, "unapproved"),
    ({"with_snapshot": False}, "no_snapshot"),
    ({"rights": "link_only"}, "rights_not_cleared"),
    ({"approved_source": False}, "rights_not_cleared"),
    ({"excerpt": ""}, "no_evidence_excerpt"),
])
def test_invalid_claims_are_rejected_with_a_reason(kwargs, reason):
    with SessionLocal() as db:
        e = _event(db)
        claim = _claim(db, e, **kwargs)
        db.commit()
        ok, got = claim_is_valid(db, claim, {})
    assert not ok and got == reason


# ---------------------------------------------------------------- substance

def test_a_summary_does_not_inherit_support_from_its_lesson():
    """Inheritance let summaries asserting mineral formulas and pressure-temperature
    relationships count as grounded with no evidence. Every teaching block needs its own."""
    with SessionLocal() as db:
        e = _event(db)
        claim = _claim(db, e)
        _lesson(db, e, [
            {"type": "opening", "claim_ids": [claim.id]},
            {"type": "property_cards", "claim_ids": [claim.id]},
            {"type": "summary"},          # asserts, but carries no evidence
        ], claim_ids=[claim.id])
        db.commit()
        row = audit_event(db, e, {})
    assert row["supported_blocks"] == 2, "the unevidenced summary must not be credited"
    assert row["substantive_coverage"] == pytest.approx(2 / 3, abs=0.01)


def test_a_snapshot_from_another_source_is_rejected():
    """Rights are checked on claim.source_id while evidence is read from
    claim.source_snapshot_id; without this check a cleared source could launder a
    restricted source's text."""
    with SessionLocal() as db:
        e = _event(db)
        cleared = _claim(db, e)                       # public-domain source + its snapshot
        restricted = _claim(db, e, rights="link_only")
        cleared.source_snapshot_id = restricted.source_snapshot_id   # borrow the other snapshot
        db.commit()
        ok, reason = claim_is_valid(db, cleared, {})
    assert not ok and reason == "snapshot_belongs_to_another_source"


def test_coverage_counts_teaching_blocks_not_claims():
    """One broad claim must not mark an entire lesson as grounded."""
    with SessionLocal() as db:
        e = _event(db)
        claim = _claim(db, e)
        blocks = [
            {"type": "opening", "claim_ids": [claim.id]},   # supported
            {"type": "property_cards"},                      # not supported
            {"type": "steps"},                               # not supported
            {"type": "checkpoint"},                          # not substantive
        ]
        _lesson(db, e, blocks, claim_ids=[claim.id])
        db.commit()
        row = audit_event(db, e, {})
    assert row["substantive_blocks"] == 3, "checkpoints assert nothing and are excluded"
    # only the opening is evidenced; property_cards is not, and steps cannot inherit because
    # the lesson's asserting blocks are only 50% supported
    assert row["supported_blocks"] == 1
    assert row["substantive_coverage"] == pytest.approx(1 / 3, abs=0.01)


def test_a_block_citing_an_invalid_claim_is_not_supported():
    with SessionLocal() as db:
        e = _event(db)
        bad = _claim(db, e, excerpt="not in the snapshot at all")
        _lesson(db, e, [{"type": "opening", "claim_ids": [bad.id]}], claim_ids=[bad.id])
        db.commit()
        row = audit_event(db, e, {})
    assert row["supported_blocks"] == 0, "an unverifiable claim is not evidence"


def test_unsupported_skills_must_carry_a_content_gap():
    with SessionLocal() as db:
        e = _event(db)
        course = Course(event_id=e.id, slug="c", title="C", status="draft")
        db.add(course); db.flush()
        from app.models.entities import CourseUnit
        unit = CourseUnit(course_id=course.id, slug="u", title="U", sequence=1)
        db.add(unit); db.flush()
        db.add(Skill(course_id=course.id, unit_id=unit.id, slug="s", name="S", sequence=1))
        db.commit()
        row = audit_event(db, e, {})
    assert row["skills_unsupported_without_gap"] == 1


# ---------------------------------------------------------------- fail closed

def test_an_empty_population_is_a_failure_not_full_coverage():
    with pytest.raises(SystemExit, match="empty population"):
        run("no-such-event")


def test_a_lesson_with_no_substantive_blocks_scores_zero_not_one():
    with SessionLocal() as db:
        e = _event(db)
        _lesson(db, e, [{"type": "checkpoint"}])
        db.commit()
        row = audit_event(db, e, {})
    assert row["substantive_coverage"] == 0.0
