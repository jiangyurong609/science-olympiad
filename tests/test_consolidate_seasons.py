"""Phase C — tests for season consolidation guards (R-C5 live-content, R-C7 invariant)."""
from __future__ import annotations

import pytest

from app.core.database import SessionLocal
from app.models.entities import Course, Event, Exam, Lesson, PracticeSet, Question
import scripts.consolidate_seasons as cs


def _ev(db, slug, name, division, season, *, active=True, status="current"):
    e = Event(slug=slug, name=name, division=division, season=season,
              active=active, season_status=status)
    db.add(e)
    db.flush()
    return e


def _has_conflict(plan, needle):
    return any(needle in c["issue"] for c in plan["conflicts"])


def test_recurring_pair_merges_clean_when_twin_is_empty():
    with SessionLocal() as db:
        prior = _ev(db, "astronomy-c", "Astronomy", "C", 2026, status="foundational")
        db.add(Course(event_id=prior.id, slug="astronomy-c", title="Astronomy", status="published"))
        _ev(db, "astronomy-c-2027", "Astronomy", "C", 2027, status="current")  # empty twin
        db.commit()

    plan = cs.build_plan(SessionLocal(), resolve_intra=False)
    assert plan["summary"]["conflicts"] == 0
    assert plan["summary"]["recurring_merged"] == 1


@pytest.mark.parametrize("kind", ["course", "exam", "practice_set", "lesson", "question"])
def test_live_content_guard_blocks_archiving_any_student_visible_row(kind):
    with SessionLocal() as db:
        prior = _ev(db, "astronomy-c", "Astronomy", "C", 2026, status="foundational")
        db.add(Course(event_id=prior.id, slug="astronomy-c", title="Astronomy", status="published"))
        twin = _ev(db, "astronomy-c-2027", "Astronomy", "C", 2027, status="current")
        if kind == "course":
            db.add(Course(event_id=twin.id, slug="astronomy-c-2027", title="A", status="published"))
        elif kind == "exam":
            db.add(Exam(event_id=twin.id, title="Mock", question_ids=[], published=True))
        elif kind == "practice_set":
            db.add(PracticeSet(event_id=twin.id, slug="ps", title="PS", status="published"))
        elif kind == "lesson":
            db.add(Lesson(event_id=twin.id, slug="l1", title="L", status="published"))
        elif kind == "question":
            db.add(Question(event_id=twin.id, stem="A published question about stars here.",
                            choices=["a", "b", "c", "d"], answer_spec={"correct_index": 0},
                            status="published"))
        db.commit()

    plan = cs.build_plan(SessionLocal(), resolve_intra=False)
    assert _has_conflict(plan, "live/published content"), plan["conflicts"]


def test_inactive_canonical_is_a_conflict():
    with SessionLocal() as db:
        # canonical (2026) is INACTIVE — archiving the active twin would empty the key
        _ev(db, "astronomy-c", "Astronomy", "C", 2026, active=False, status="foundational")
        _ev(db, "astronomy-c-2027", "Astronomy", "C", 2027, active=True, status="current")
        db.commit()

    plan = cs.build_plan(SessionLocal(), resolve_intra=False)
    assert _has_conflict(plan, "zero active events")


def test_invariant_rejects_emptied_key():
    # Simulate the bad end-state directly: a key whose only events are inactive/archived.
    with SessionLocal() as db:
        _ev(db, "astronomy-c", "Astronomy", "C", 2026, active=False, status=cs.ARCHIVED_STATUS)
        db.commit()
        with pytest.raises(SystemExit, match="INVARIANT FAILED"):
            cs._assert_invariant(db)


def test_invariant_passes_with_exactly_one_active():
    with SessionLocal() as db:
        _ev(db, "astronomy-c", "Astronomy", "C", 2026, active=True, status="current")
        _ev(db, "astronomy-c-2027", "Astronomy", "C", 2027, active=False, status=cs.ARCHIVED_STATUS)
        db.commit()
        cs._assert_invariant(db)  # must not raise


def test_apply_is_blocked_until_archive_surface_ready(monkeypatch):
    # R-C6: --apply must refuse until the archive surface exists, even with a backup + no conflicts.
    monkeypatch.setattr("sys.argv", ["consolidate_seasons", "--apply", "--i-took-a-backup"])
    with pytest.raises(SystemExit, match="archive listing/detail surface"):
        cs.main()
