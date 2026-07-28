from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import Event, EventSourceMap, Source
from app.services.material_sheet_import import import_materials, parse_material_csv


SHEET_ID = "1tiGm0vIj-3H8eGBotL8zJ2kwR52v7L7-Rjw9aC7d29A"


def _csv(*rows: str) -> bytes:
    return (
        "Link Text,Internal URL Reference\n"
        + "\n".join(rows)
        + "\n"
    ).encode()


def test_material_sheet_dry_run_does_not_write_and_requires_target_season_events():
    payload = _csv(
        "Rocks & Minerals Introductory Video,https://youtu.be/example",
        "Rock Cycle Worksheet,https://www.soinc.org/files/rock-cycle.pdf",
    )
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(Source))
        report = import_materials(
            db, payload, season=2027, spreadsheet_id=SHEET_ID, apply=False
        )
        after = db.scalar(select(func.count()).select_from(Source))
    assert before == after
    assert report.rows_ready == 0
    assert len(report.rejected) == 2
    assert {row["reason"] for row in report.rejected} == {
        "event_not_registered_for_target_season"
    }


def test_material_sheet_apply_is_idempotent_and_propagates_event_sections():
    payload = _csv(
        "Rocks & Minerals Introductory Video,https://youtu.be/example",
        "Rock Cycle Worksheet,https://www.soinc.org/files/rock-cycle.pdf",
        "Division C Ternary Diagrams,https://www.soinc.org/files/ternary.pdf",
    )
    with SessionLocal() as db:
        db.add_all(
            [
                Event(
                    slug="rocks-and-minerals-b",
                    name="Rocks and Minerals",
                    division="B",
                    season=2027,
                ),
                Event(
                    slug="rocks-and-minerals-c",
                    name="Rocks and Minerals",
                    division="C",
                    season=2027,
                ),
            ]
        )
        db.commit()
        first = import_materials(
            db, payload, season=2027, spreadsheet_id=SHEET_ID, apply=True
        )
        source_count = db.scalar(select(func.count()).select_from(Source))
        mapping_count = db.scalar(select(func.count()).select_from(EventSourceMap))
        second = import_materials(
            db, payload, season=2027, spreadsheet_id=SHEET_ID, apply=True
        )
        assert db.scalar(select(func.count()).select_from(Source)) == source_count
        assert db.scalar(select(func.count()).select_from(EventSourceMap)) == mapping_count
    assert first.sources_created == 3
    assert first.mappings_created == 5
    assert second.sources_created == 0
    assert second.mappings_created == 0
    assert second.sources_existing == 3
    assert second.mappings_existing == 5


def test_material_sheet_quarantines_corrupt_and_global_rows():
    payload = _csv(
        "Welcome Video,https://youtu.be/welcome",
        "Heredity Introductory Video,https://www.soinc.org/files/heredity.pdf6",
        "[![Google Logo]],https://www.soinc.org/files/certificate.pdf8",
    )
    rows = parse_material_csv(payload)
    assert len(rows) == 3
    with SessionLocal() as db:
        report = import_materials(
            db, payload, season=2027, spreadsheet_id=SHEET_ID, apply=False
        )
    assert len(report.skipped_global) == 1
    assert {row["reason"] for row in report.rejected} == {"malformed_pdf_url"}


def test_material_sheet_can_map_global_rows_to_season_resources():
    payload = _csv("Welcome Video,https://youtu.be/welcome")
    with SessionLocal() as db:
        db.add(
            Event(
                slug="season-resources-bc-2027",
                name="Season Resources",
                division="B/C",
                season=2027,
            )
        )
        db.commit()
        report = import_materials(
            db,
            payload,
            season=2027,
            spreadsheet_id=SHEET_ID,
            apply=True,
            include_global=True,
        )
    assert report.rows_ready == 1
    assert report.sources_created == 1
    assert report.mappings_created == 1
    assert report.skipped_global == []


def test_event_catalog_reports_imported_material_count(client):
    response = client.get("/api/events")
    assert response.status_code == 200
    assert all("material_count" in event for event in response.json())
