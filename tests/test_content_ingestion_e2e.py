from io import BytesIO

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Source, SourcePassage, UploadSubmission


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_upload_extract_review_and_student_visibility(client, admin_token, student_token):
    with SessionLocal() as db:
        event = Event(slug="ingestion-event-2027", name="Ingestion Event", division="B", season=2027)
        db.add(event)
        db.commit()
        event_id = event.id

    material = (
        "Rocks and minerals are identified using observable evidence.\n\n"
        "Color is useful for narrowing possibilities, but streak and hardness are often more diagnostic.\n\n"
        "A careful observer records the test, the result, and the inference separately."
    ).encode()
    uploaded = client.post(
        "/api/content/intake/uploads",
        headers=auth(admin_token),
        data={"event_id": str(event_id), "rights_attestation": "Fieldstone owns this teaching handout."},
        files={"file": ("rocks-handout.txt", BytesIO(material), "text/plain")},
    )
    assert uploaded.status_code == 200
    upload_id = uploaded.json()["upload_id"]

    # The durable job is explicitly run as an admin worker in this integration test.
    ran = client.post("/api/jobs/run-next", headers=auth(admin_token))
    assert ran.status_code == 200 and ran.json()["status"] == "completed"
    listed = client.get("/api/content/intake/uploads", headers=auth(admin_token))
    row = next(item for item in listed.json() if item["id"] == upload_id)
    assert row["status"] == "needs_review"
    assert row["ingestion"]["stage"] == "ready_for_review"

    with SessionLocal() as db:
        source = db.scalar(select(Source).where(Source.content_hash == row["sha256"]))
        assert source is not None and source.approved is False
        assert db.scalar(select(SourcePassage).where(SourcePassage.source_id == source.id)) is not None
        source_id = source.id

    # Quarantined intake is not student-visible.
    before = client.get(f"/api/events/{event_id}/materials", headers=auth(student_token))
    assert before.status_code == 200
    assert all(item["source_id"] != source_id for item in before.json()["materials"])

    accepted = client.post(
        f"/api/content/intake/uploads/{upload_id}/review",
        headers=auth(admin_token),
        data={"decision": "accepted", "rights_status": "derivative_generation_allowed", "notes": "Verified ownership and scope."},
    )
    assert accepted.status_code == 200
    assert accepted.json()["source_approved"] is True

    after = client.get(f"/api/events/{event_id}/materials", headers=auth(student_token))
    assert after.status_code == 200
    assert any(item["source_id"] == source_id and item["has_text"] for item in after.json()["materials"])

    # Parent/student roles cannot use the staff intake surface.
    denied = client.get("/api/content/intake/uploads", headers=auth(student_token))
    assert denied.status_code == 403
