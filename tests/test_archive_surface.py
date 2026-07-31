"""Phase C (R-C6) — archive listing + canonical slug redirects keep archived content reachable."""
from __future__ import annotations

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson


def _seed(db):
    live = Event(slug="astronomy-c", name="Astronomy", division="C", season=2026,
                 active=True, season_status="current")
    prior = Event(slug="entomology-c", name="Entomology", division="C", season=2026,
                  active=True, season_status="prior_season_practice")
    twin = Event(slug="astronomy-c-2027", name="Astronomy", division="C", season=2027,
                 active=False, season_status="archived_superseded")
    db.add_all([live, prior, twin])
    db.flush()
    db.add(Lesson(event_id=twin.id, slug="l1", title="Archived lesson", status="published"))
    db.commit()
    return live.id, prior.id, twin.id


def test_live_catalog_excludes_prior_and_archived(client):
    with SessionLocal() as db:
        _seed(db)
    rows = client.get("/api/events").json()
    slugs = {r["slug"] for r in rows}
    assert slugs == {"astronomy-c"}


def test_archive_requires_auth(client):
    with SessionLocal() as db:
        _seed(db)
    assert client.get("/api/catalog/archive").status_code == 401


def test_archive_lists_prior_and_archived_with_canonical(client, student_token):
    with SessionLocal() as db:
        _seed(db)
    rows = client.get("/api/catalog/archive",
                      headers={"Authorization": f"Bearer {student_token}"}).json()
    by_slug = {r["slug"]: r for r in rows}
    assert set(by_slug) == {"entomology-c", "astronomy-c-2027"}
    # the retired twin points back to its live canonical; its archived lesson is counted
    twin = by_slug["astronomy-c-2027"]
    assert twin["canonical_slug"] == "astronomy-c"
    assert twin["lesson_count"] == 1
    # prior-season-only event has no live canonical
    assert by_slug["entomology-c"]["canonical_event_id"] is None


def test_slug_resolver_redirects_twin_to_canonical(client):
    with SessionLocal() as db:
        _seed(db)
    r = client.get("/api/events/by-slug/astronomy-c-2027").json()
    assert r["redirect"] is True
    assert r["slug"] == "astronomy-c"

    live = client.get("/api/events/by-slug/astronomy-c").json()
    assert live["redirect"] is False
    assert live["slug"] == "astronomy-c"
