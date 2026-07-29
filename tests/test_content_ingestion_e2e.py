from io import BytesIO

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Lesson, Source, SourcePassage


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_upload_extract_review_and_student_visibility(client, admin_token, student_token, monkeypatch):
    with SessionLocal() as db:
        event = Event(slug="ingestion-event-2027", name="Ingestion Event", division="B", season=2027)
        db.add(event)
        db.commit()
        event_id = event.id

    material = (
        "Rocks and minerals are identified using observable evidence.\n\n"
        "Color is useful for narrowing possibilities, but streak and hardness are often more diagnostic.\n\n"
        "A careful observer records the test, the result, and the inference separately. "
        "Density, luster, cleavage, fracture, magnetism, and acid reaction can provide additional evidence. "
        "The goal is not to guess from one visual cue, but to choose the most diagnostic next test and record a defensible claim."
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

    class FakeProvider:
        configured = True

        def generate_json(self, system, user):
            if "design a SYSTEMATIC course" in system:
                return type("Result", (), {"payload": {"lessons": [{"title": "Evidence Basics", "focus": "Use observable evidence.", "subtopics": ["color", "hardness"]}]}})()
            return type("Result", (), {"payload": {"title": "Evidence Basics", "summary": "Practice evidence-based identification.", "estimated_minutes": 12, "blocks": [
                {"type": "opening", "heading": "Start with evidence", "body": "Observe before inferring."},
                {"type": "steps", "heading": "Test routine", "steps": [{"label": "Observe", "detail": "Record color."}, {"label": "Test", "detail": "Measure hardness."}]},
                {"type": "worked_example", "heading": "Worked example", "prompt": "Classify a specimen.", "steps": ["Record streak", "Compare hardness"]},
                {"type": "checkpoint", "heading": "Check", "question": "What should you record?", "choices": ["Evidence", "Guess"], "correct_index": 0, "explanation": "Evidence is observable."},
                {"type": "property_cards", "heading": "Diagnostic properties", "body": "Use multiple tests.", "cards": [{"name": "Streak", "cue": "powder", "detail": "More reliable than surface color."}, {"name": "Hardness", "cue": "scratch", "detail": "Compare against known materials."}]},
                {"type": "summary", "heading": "Remember", "points": ["Separate evidence from inference."]},
            ]}})()

    monkeypatch.setattr("app.services.lesson_generation.OpenAICompatibleProvider", FakeProvider)
    queued = client.post(f"/api/content/authoring/events/{event_id}/lessons", headers=auth(admin_token))
    assert queued.status_code == 200 and queued.json()["output_status"] == "draft"
    authored = client.post("/api/jobs/run-next", headers=auth(admin_token))
    assert authored.status_code == 200 and authored.json()["status"] == "completed"
    with SessionLocal() as db:
        lesson = db.scalar(select(Lesson).where(Lesson.event_id == event_id))
        assert lesson is not None and lesson.status == "draft"

    # Draft lessons are not launchable by a student until review/publish gates pass.
    lessons = client.get(f"/api/events/{event_id}/lessons", headers=auth(student_token))
    assert lessons.status_code == 200
    assert all(item["id"] != lesson.id for item in lessons.json())

    # Parent/student roles cannot use the staff intake surface.
    denied = client.get("/api/content/intake/uploads", headers=auth(student_token))
    assert denied.status_code == 403
