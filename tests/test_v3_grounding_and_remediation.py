from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, ExamItem, GuardianConsent, MasteryState, Question, RemediationCase,
    ScientificClaim, Source, SourceSnapshot, TransferAttempt,
)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_minor_registration_requires_and_accepts_guardian_consent(client):
    missing = client.post("/api/auth/register", json={
        "email": "minor1@example.com", "full_name": "Minor Student",
        "password": "password123", "division": "B", "age_years": 11,
    })
    assert missing.status_code == 422

    created = client.post("/api/auth/register", json={
        "email": "minor2@example.com", "full_name": "Minor Student",
        "password": "password123", "division": "B", "age_years": 11,
        "guardian_email": "guardian@example.com",
    })
    assert created.status_code == 200
    body = created.json()
    assert body["pending_guardian_consent"] is True
    assert body["access_token"] is None
    assert client.post("/api/auth/login", json={
        "email": "minor2@example.com", "password": "password123",
    }).status_code == 401

    granted = client.post("/api/auth/guardian-consent", json={
        "token": body["development_consent_token"],
    })
    assert granted.status_code == 200
    assert client.post("/api/auth/login", json={
        "email": "minor2@example.com", "password": "password123",
    }).status_code == 200
    with SessionLocal() as db:
        consent = db.scalar(select(GuardianConsent))
        assert consent.status == "granted"


def test_claim_approval_and_grounded_generation(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="claim-event", name="Claim Event", division="B", season=2026)
        db.add(event)
        db.flush()
        concept = Concept(event_id=event.id, name="Reliability")
        source = Source(
            url="https://science.nasa.gov/claim-source", title="Approved Source",
            rights_status="fact_grounding_allowed", approved=True,
            content_hash="b" * 64,
            extracted_text="Repeating measurements improves reliability.",
        )
        db.add_all([concept, source])
        db.flush()
        snapshot = SourceSnapshot(
            source_id=source.id, final_url=source.url, content_hash=source.content_hash,
            content_type="text/html", byte_count=45, extracted_text=source.extracted_text,
        )
        db.add(snapshot)
        db.commit()
        event_id, concept_id, source_id, snapshot_id = event.id, concept.id, source.id, snapshot.id

    claim = client.post("/api/claims", headers=auth(admin_token), json={
        "source_id": source_id, "source_snapshot_id": snapshot_id, "concept_id": concept_id,
        "claim_text": "Repeated trials reduce the influence of random variation.",
        "evidence_excerpt": "Repeating measurements improves reliability.",
        "locator": "section 2",
    })
    assert claim.status_code == 200
    claim_id = claim.json()["id"]
    assert client.post(f"/api/claims/{claim_id}/approve", headers=auth(admin_token)).status_code == 200

    generated = client.post("/api/questions/generate", headers=auth(admin_token), json={
        "event_id": event_id, "concept_id": concept_id, "count": 1,
        "difficulty": 0.5, "cognitive_level": "application", "question_type": "single_choice",
    })
    assert generated.status_code == 200
    report = generated.json()[0]["validation_report"]
    assert report["passed"] is True
    assert report["factual_grounding"] == "approved_claims"
    assert claim_id in report["claim_ids"]
    with SessionLocal() as db:
        assert db.get(ScientificClaim, claim_id).approved is True


def test_transfer_item_required_and_updates_mastery(client, admin_token, student_token):
    with SessionLocal() as db:
        event = Event(slug="transfer-event", name="Transfer Event", division="B", season=2026)
        db.add(event)
        db.flush()
        concept = Concept(event_id=event.id, name="Experimental reliability")
        db.add(concept)
        db.commit()
        event_id, concept_id = event.id, concept.id

    generated = client.post("/api/questions/generate", headers=auth(admin_token), json={
        "event_id": event_id, "concept_id": concept_id, "count": 1,
        "difficulty": 0.5, "cognitive_level": "application", "question_type": "single_choice",
    })
    assert generated.status_code == 200
    with SessionLocal() as db:
        for question in db.query(Question).filter(Question.event_id == event_id):
            question.status = "published"
        db.commit()
    exam = client.post("/api/exams", headers=auth(admin_token), json={
        "event_id": event_id, "title": "Transfer Mock", "duration_minutes": 10,
        "question_count": 1, "published": True,
    })
    assert exam.status_code == 200
    started = client.post(f"/api/exams/{exam.json()['id']}/start", headers=auth(student_token)).json()
    qid = started["questions"][0]["id"]
    with SessionLocal() as db:
        item = db.scalar(select(ExamItem).where(ExamItem.exam_id == exam.json()["id"]))
        correct = item.snapshot["answer_spec"]["correct_index"]
        wrong = (correct + 1) % len(item.snapshot["choices"])
    saved = client.put(f"/api/attempts/{started['attempt_id']}/responses", headers=auth(student_token), json={
        "question_id": qid, "answer": {"selected_index": wrong}, "confidence": 4,
        "time_spent_seconds": 15, "sequence_number": 1, "idempotency_key": "transfer-wrong-0001",
    })
    assert saved.status_code == 200
    assert client.post(f"/api/attempts/{started['attempt_id']}/submit", headers=auth(student_token)).status_code == 200
    review = client.get(f"/api/attempts/{started['attempt_id']}/review", headers=auth(student_token)).json()
    case_id = review["remediation_cases"][0]["id"]

    assert client.post(f"/api/remediation/{case_id}/transfer", headers=auth(student_token)).status_code == 400
    assert client.put(f"/api/remediation/{case_id}/reflection", headers=auth(student_token), json={
        "reflection": "I confused reliability with changing multiple variables and should repeat trials.",
    }).status_code == 200
    transfer = client.post(f"/api/remediation/{case_id}/transfer", headers=auth(student_token))
    assert transfer.status_code == 200
    transfer_id = transfer.json()["transfer_id"]
    with SessionLocal() as db:
        row = db.get(TransferAttempt, transfer_id)
        transfer_correct = row.question_payload["answer_spec"]["correct_index"]
    result = client.post(f"/api/remediation/transfer/{transfer_id}/submit", headers=auth(student_token), json={
        "answer": {"selected_index": transfer_correct},
    })
    assert result.status_code == 200
    assert result.json()["correct"] is True
    assert result.json()["remediation_status"] == "delayed_review"
    mastery = client.get("/api/mastery", headers=auth(student_token))
    assert mastery.status_code == 200
    assert mastery.json()[0]["concept_id"] == concept_id
    assert mastery.json()[0]["evidence_count"] == 1
    with SessionLocal() as db:
        case = db.get(RemediationCase, case_id)
        state = db.scalar(select(MasteryState).where(MasteryState.concept_id == concept_id))
        assert case.status == "delayed_review"
        assert state.mastery_probability > 0.25
