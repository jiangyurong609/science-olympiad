"""Phase Q — tests for the catalog-wide quality scorecard (R-C8 population/denominator)."""
from __future__ import annotations

from app.core.database import SessionLocal
from app.models.entities import Course, Event
from scripts.audit_catalog_quality import run


def _event(db, slug, *, active=True, season=2026):
    e = Event(slug=slug, name=slug.replace("-", " ").title(), division="C",
              season=season, active=active)
    db.add(e)
    db.flush()
    return e


def _course(db, event_id, slug, status="published"):
    c = Course(event_id=event_id, slug=slug, title=slug, status=status)
    db.add(c)
    db.flush()
    return c


def test_live_scorecard_excludes_archived_and_inactive_events():
    with SessionLocal() as db:
        live = _event(db, "astronomy-c")
        _course(db, live.id, "astronomy-c")
        # archived-status course on an active event
        arch_ev = _event(db, "entomology-c")
        _course(db, arch_ev.id, "entomology-c", status="archived_superseded")
        # published course but on an INACTIVE event (retired twin)
        dead_ev = _event(db, "astronomy-c-2027", active=False, season=2027)
        _course(db, dead_ev.id, "astronomy-c-2027", status="published")
        db.commit()

    result = run()
    slugs = {c["slug"] for c in result["courses"]}
    assert slugs == {"astronomy-c"}          # only the live course is in the population
    assert result["totals"]["courses"] == 1
    assert result["population"] == "live"


def test_archive_mode_audits_only_non_live():
    with SessionLocal() as db:
        live = _event(db, "astronomy-c")
        _course(db, live.id, "astronomy-c")
        arch_ev = _event(db, "entomology-c")
        _course(db, arch_ev.id, "entomology-c", status="archived_superseded")
        db.commit()

    result = run(archive=True)
    slugs = {c["slug"] for c in result["courses"]}
    assert slugs == {"entomology-c"}
    assert result["population"] == "archive"


def test_audit_errors_count_as_not_release_ready_in_denominator(monkeypatch):
    # An audit that raises must be counted NOT release-ready and stay in the denominator,
    # so a failure can never *raise* the headline pass rate (R-C8).
    with SessionLocal() as db:
        e1 = _event(db, "astronomy-c")
        c1 = _course(db, e1.id, "astronomy-c")
        e2 = _event(db, "entomology-c")
        c2 = _course(db, e2.id, "entomology-c")
        db.commit()
        boom_id = c1.id

    import scripts.audit_catalog_quality as mod

    def fake_audit(db, course_id):
        if course_id == boom_id:
            raise RuntimeError("boom")
        return {"release_ready": False, "counts": {"blockers": 3}, "blocker_counts": {"x": 3}}

    monkeypatch.setattr(mod, "audit_course", fake_audit)

    result = mod.run()
    t = result["totals"]
    assert t["courses"] == 2          # both selected
    assert t["errored"] == 1
    assert t["release_ready"] == 0
    assert t["not_release_ready"] == 2  # error + the non-ready course, over the full denominator
    assert t["release_ready_pct"] == 0.0


def test_error_cannot_inflate_pass_rate(monkeypatch):
    # One ready course + one erroring course => 50%, not 100%.
    with SessionLocal() as db:
        e1 = _event(db, "astronomy-c")
        c1 = _course(db, e1.id, "astronomy-c")
        e2 = _event(db, "entomology-c")
        c2 = _course(db, e2.id, "entomology-c")
        db.commit()
        boom_id = c2.id

    import scripts.audit_catalog_quality as mod

    def fake_audit(db, course_id):
        if course_id == boom_id:
            raise RuntimeError("boom")
        return {"release_ready": True, "counts": {"blockers": 0}, "blocker_counts": {}}

    monkeypatch.setattr(mod, "audit_course", fake_audit)
    result = mod.run()
    assert result["totals"]["release_ready_pct"] == 50.0
