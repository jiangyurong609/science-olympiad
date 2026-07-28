from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import Event
from app.services.season_catalog import events_2027, register_2027_catalog


def test_2027_catalog_has_official_and_trial_event_counts():
    rows = events_2027()
    official = [row for row in rows if row.season_status == "current"]
    trials = [row for row in rows if row.season_status == "trial"]
    assert len(rows) == 50
    assert len([row for row in official if row.division == "B"]) == 23
    assert len([row for row in official if row.division == "C"]) == 23
    assert len([row for row in official if row.division == "B/C"]) == 1
    assert len(trials) == 3
    assert len({row.slug for row in rows}) == len(rows)


def test_register_2027_catalog_is_idempotent_and_archives_older_current_events():
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(Event))
        dry_run = register_2027_catalog(db, apply=False)
        assert db.scalar(select(func.count()).select_from(Event)) == before
        assert dry_run.created == 50

        first = register_2027_catalog(db, apply=True)
        after = db.scalar(select(func.count()).select_from(Event))
        second = register_2027_catalog(db, apply=True)
        assert db.scalar(select(func.count()).select_from(Event)) == after
        assert not db.scalars(
            select(Event).where(Event.season < 2027, Event.season_status == "current")
        ).all()
    assert first.created == 50
    assert second.created == 0
    assert second.updated == 50
