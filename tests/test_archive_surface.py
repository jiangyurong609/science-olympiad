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


def test_catalog_keeps_prior_season_events_and_drops_only_retired_twins(client):
    """Prior-season events rotated out of the slate but still hold real lessons and exams —
    hiding them made content-rich events look deleted. Only retired duplicates are dropped."""
    with SessionLocal() as db:
        _seed(db)
    rows = client.get("/api/events").json()
    slugs = {r["slug"] for r in rows}
    assert slugs == {"astronomy-c", "entomology-c"}, "prior-season practice must stay visible"
    prior = next(r for r in rows if r["slug"] == "entomology-c")
    assert prior["season_status"] == "prior_season_practice", "and be labelled as such"


def test_content_bearing_prior_event_is_not_lost_from_the_catalog(client):
    """Regression: a prior-season event holding lessons/questions must remain reachable."""
    with SessionLocal() as db:
        live, prior, twin = _seed(db)
        from app.models.entities import Question
        db.add(Question(event_id=prior, stem="A prior-season question about insects here.",
                        choices=["a", "b", "c", "d"], answer_spec={"correct_index": 0},
                        status="published"))
        db.commit()
    slugs = {r["slug"] for r in client.get("/api/events").json()}
    assert "entomology-c" in slugs


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


def test_review_queue_skips_lessons_on_retired_events(client, admin_token):
    """A reviewer's decision on a retired duplicate can never reach a student, so queueing
    it only wastes review time."""
    from app.models.entities import Course, CourseUnit, LessonSkill, LessonVersion, Skill
    with SessionLocal() as db:
        live, prior, twin = _seed(db)
        for event_id, course_status in ((twin, "draft"), (live, "draft")):
            course = Course(event_id=event_id, slug=f"c{event_id}", title="C", status=course_status)
            db.add(course); db.flush()
            unit = CourseUnit(course_id=course.id, slug=f"u{event_id}", title="U", sequence=1)
            db.add(unit); db.flush()
            skill = Skill(course_id=course.id, unit_id=unit.id, slug=f"s{event_id}", name="S", sequence=1)
            db.add(skill); db.flush()
            lesson = Lesson(event_id=event_id, slug=f"draft-{event_id}", title=f"Draft {event_id}",
                            status="draft", current_version=1)
            db.add(lesson); db.flush()
            db.add(LessonVersion(lesson_id=lesson.id, version=1, content=[], review_status="ai_draft"))
            db.add(LessonSkill(lesson_id=lesson.id, skill_id=skill.id, is_primary=True))
        db.commit()

    queue = client.get("/api/content/lessons/review-queue",
                       headers={"Authorization": f"Bearer {admin_token}"}).json()
    titles = {row.get("title") for row in (queue if isinstance(queue, list) else queue.get("items", []))}
    assert f"Draft {live}" in titles, "work on a live event must still be reviewable"
    assert f"Draft {twin}" not in titles, "work on a retired event must not be queued"
