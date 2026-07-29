from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import create_access_token, hash_password
from app.models.entities import Event, EventSourceMap, ExtractionAsset, Lesson, ParentMaterialShare, Source, SourcePassage, SourceSnapshot, UploadSubmission, User


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


def test_office_formats_extract_into_reviewable_assets(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="office-ingestion-2027", name="Office Ingestion", division="B", season=2027)
        db.add(event)
        db.commit()
        event_id = event.id

    docx = BytesIO()
    with ZipFile(docx, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<w:document><w:p><w:t>Document lesson content with enough detail for extraction and review. Students compare observations, record evidence, and explain their reasoning.</w:t></w:p></w:document>")
    pptx = BytesIO()
    with ZipFile(pptx, "w", ZIP_DEFLATED) as archive:
        archive.writestr("ppt/slides/slide1.xml", "<p:sld><a:t>Slide lesson content with an observation routine and evidence. Students apply the routine to a new specimen and justify a conclusion.</a:t></p:sld>")

    for filename, body, media_type in (("lesson.docx", docx.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), ("lesson.pptx", pptx.getvalue(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")):
        uploaded = client.post(
            "/api/content/intake/uploads", headers=auth(admin_token),
            data={"event_id": str(event_id), "rights_attestation": "Fieldstone owns this source."},
            files={"file": (filename, BytesIO(body), media_type)},
        )
        assert uploaded.status_code == 200
        ran = client.post("/api/jobs/run-next", headers=auth(admin_token))
        assert ran.json()["status"] == "completed"

    with SessionLocal() as db:
        assets = db.query(ExtractionAsset).all()
        assert {asset.diagnostics_json["extraction"] for asset in assets} == {"docx-xml", "pptx-xml"}
        assert all(asset.text_chars > 40 for asset in assets)


def test_staff_url_import_is_durable_and_quarantined(client, admin_token, monkeypatch):
    with SessionLocal() as db:
        event = Event(slug="url-ingestion-2027", name="URL Ingestion", division="B", season=2027)
        db.add(event)
        db.commit()
        event_id = event.id

    imported = client.post(
        "/api/content/intake/imports", headers=auth(admin_token),
        data={
            "url": "https://example.com/fieldstone-handout",
            "event_id": str(event_id),
            "title": "Fieldstone URL Handout",
            "rights_attestation": "Fieldstone has permission to use this educational page.",
        },
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]

    def fake_crawl(db, source, *, allow_unapproved=False):
        assert allow_unapproved is True
        snapshot = SourceSnapshot(
            source_id=source.id, final_url=source.url, content_hash="f" * 64,
            content_type="text/html", byte_count=120,
            extracted_text="A durable URL handout explains evidence and observation routines for students.",
            metadata_json={"parser": "test"},
        )
        db.add(snapshot)
        source.extracted_text = snapshot.extracted_text
        source.content_hash = snapshot.content_hash
        db.flush()
        return source

    monkeypatch.setattr("app.services.jobs.crawl_source", fake_crawl)
    ran = client.post("/api/jobs/run-next", headers=auth(admin_token))
    assert ran.status_code == 200 and ran.json()["status"] == "completed"
    inbox = client.get("/api/content/intake/imports", headers=auth(admin_token))
    assert inbox.status_code == 200 and any(row["source_id"] == source_id and row["text_chars"] > 40 for row in inbox.json())
    with SessionLocal() as db:
        source = db.get(Source, source_id)
        assert source and source.approved is False
        mapping = db.scalar(select(EventSourceMap).where(EventSourceMap.source_id == source_id))
        assert mapping and mapping.reviewed is False
    accepted = client.post(
        f"/api/content/intake/imports/{source_id}/review", headers=auth(admin_token),
        data={"decision": "accepted", "rights_status": "derivative_generation_allowed", "notes": "URL rights verified."},
    )
    assert accepted.status_code == 200 and accepted.json()["source_approved"] is True
    # A second submission is URL-idempotent and only schedules a retry.
    duplicate = client.post(
        "/api/content/intake/imports", headers=auth(admin_token),
        data={"url": "https://example.com/fieldstone-handout", "rights_attestation": "Permission is recorded for review."},
    )
    assert duplicate.status_code == 200 and duplicate.json()["deduplicated"] is True


def test_scanned_image_uses_ocr_and_retains_confidence(client, admin_token, monkeypatch):
    with SessionLocal() as db:
        event = Event(slug="ocr-ingestion-2027", name="OCR Ingestion", division="B", season=2027)
        db.add(event)
        db.commit()
        event_id = event.id

    monkeypatch.setattr(
        "app.services.content_ingestion._ocr_image",
        lambda content: ("A scanned handout explains mineral hardness and streak for evidence-based identification.", {
            "page_count": 1, "extraction": "google-vision-ocr", "ocr_confidence": 0.93,
        }),
    )
    uploaded = client.post(
        "/api/content/intake/uploads", headers=auth(admin_token),
        data={"event_id": str(event_id), "rights_attestation": "Fieldstone has permission to process this scan."},
        files={"file": ("scan.png", BytesIO(b"not-a-real-png-but-the-ocr-adapter-is-real"), "image/png")},
    )
    assert uploaded.status_code == 200
    ran = client.post("/api/jobs/run-next", headers=auth(admin_token))
    assert ran.status_code == 200 and ran.json()["status"] == "completed"
    with SessionLocal() as db:
        asset = db.scalar(select(ExtractionAsset).where(ExtractionAsset.upload_id == uploaded.json()["upload_id"]))
        assert asset and asset.diagnostics_json["extraction"] == "google-vision-ocr"
        assert asset.ocr_confidence == 0.93


def test_resumable_upload_retries_chunks_and_ingests(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="chunk-ingestion-2027", name="Chunk Ingestion", division="B", season=2027)
        db.add(event)
        db.commit()
        event_id = event.id
    prefix = ("A durable chunked handout explains observation, evidence, and reasoning for students.\n\n")
    content = (prefix * 20_000).encode()
    split = 1_000_000
    assert len(content) > split
    started = client.post(
        "/api/content/intake/uploads/resumable", headers=auth(admin_token),
        data={"filename": "large-handout.txt", "media_type": "text/plain", "total_bytes": str(len(content)), "event_id": str(event_id), "rights_attestation": "Fieldstone owns this large handout."},
    )
    assert started.status_code == 200
    upload_id = started.json()["upload_id"]
    first, second = content[:split], content[split:]
    # Chunks are resumable and may arrive out of order.
    assert client.put(f"/api/content/intake/uploads/{upload_id}/chunks/1", headers=auth(admin_token), files={"file": ("chunk", second, "application/octet-stream")}).status_code == 200
    missing = client.post(f"/api/content/intake/uploads/{upload_id}/complete", headers=auth(admin_token))
    assert missing.status_code == 409
    assert client.put(f"/api/content/intake/uploads/{upload_id}/chunks/0", headers=auth(admin_token), files={"file": ("chunk", first, "application/octet-stream")}).status_code == 200
    completed = client.post(f"/api/content/intake/uploads/{upload_id}/complete", headers=auth(admin_token))
    assert completed.status_code == 200
    assert client.post(f"/api/content/intake/uploads/{upload_id}/complete", headers=auth(admin_token)).json()["deduplicated"] is True
    ran = client.post("/api/jobs/run-next", headers=auth(admin_token))
    assert ran.status_code == 200 and ran.json()["status"] == "completed"
    with SessionLocal() as db:
        upload = db.get(UploadSubmission, upload_id)
        assert upload and upload.status == "needs_review"


def test_parent_materials_are_private_and_staff_reviewed(client, admin_token):
    with SessionLocal() as db:
        parent = User(email="parent@example.com", full_name="Parent", password_hash=hash_password("password123"), role="parent")
        student = User(email="child@example.com", full_name="Child", password_hash=hash_password("password123"), role="student", division="B")
        event = Event(slug="parent-event-2027", name="Parent Event", division="B", season=2027)
        db.add_all([parent, student, event])
        db.commit()
        parent_token, student_id, event_id = create_access_token(str(parent.id)), student.id, event.id

    response = client.post(
        "/api/parent/materials", headers=auth(parent_token),
        data={"rights_attestation": "I created and own this handout."},
        files={"file": ("family-notes.txt", BytesIO(b"A private family contribution with enough educational detail for extraction and review."), "text/plain")},
    )
    assert response.status_code == 200
    upload_id = response.json()["upload_id"]
    listed = client.get("/api/parent/materials", headers=auth(parent_token))
    assert listed.status_code == 200 and len(listed.json()) == 1
    # The parent cannot inspect staff intake or trigger review decisions.
    assert client.get("/api/content/intake/uploads", headers=auth(parent_token)).status_code == 403
    assert client.post("/api/jobs/run-next", headers=auth(admin_token)).json()["status"] == "completed"
    accepted = client.post(
        f"/api/content/intake/uploads/{upload_id}/review", headers=auth(admin_token),
        data={"decision": "accepted", "event_id": str(event_id), "student_user_id": str(student_id), "notes": "Parent ownership verified and event assigned."},
    )
    assert accepted.status_code == 200
    with SessionLocal() as db:
        share = db.scalar(select(ParentMaterialShare).where(ParentMaterialShare.upload_id == upload_id))
        assert share and share.student_user_id == student_id
