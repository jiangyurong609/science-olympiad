from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.entities import Event, Question, ScientificClaim, Source, SourceSnapshot, User


def auth(token):
    return {"Authorization": f"Bearer {token}"}


EDITOR_CHECKS = {
    "clear_language": True, "single_best_answer": True, "distractors_plausible": True,
    "age_appropriate": True, "original_wording": True,
}
SME_CHECKS = {
    "factually_supported": True, "answer_key_verified": True,
    "citations_verified": True, "no_material_ambiguity": True,
}


def test_generated_question_cannot_enter_exam_before_publication(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="editorial-gate", name="Editorial Gate", division="B", season=2026)
        db.add(event)
        db.commit()
        event_id = event.id
    generated = client.post("/api/questions/generate", headers=auth(admin_token), json={
        "event_id": event_id, "count": 1, "difficulty": 0.5,
        "cognitive_level": "application", "question_type": "single_choice",
    })
    assert generated.status_code == 200
    exam = client.post("/api/exams", headers=auth(admin_token), json={
        "event_id": event_id, "title": "Unsafe", "question_count": 1, "published": True,
    })
    assert exam.status_code == 409
    assert exam.json()["detail"]["available"] == 0


def test_review_order_checklists_and_independent_reviewer(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="review-flow", name="Review Flow", division="B", season=2026)
        db.add(event)
        db.flush()
        question = Question(
            event_id=event.id, status="machine_validated", stem="Which observation provides the strongest evidence?",
            choices=["A repeated result", "A guess", "One anecdote", "No measurement"],
            answer_spec={"correct_index": 0}, validation_report={"passed": True},
        )
        db.add(question)
        db.flush()
        qid = question.id
        editor = User(email="editor@example.com", full_name="Editor", role="editor")
        sme = User(email="sme@example.com", full_name="SME", role="sme")
        db.add_all([editor, sme])
        db.commit()
        editor_token = create_access_token(str(editor.id))
        sme_token = create_access_token(str(sme.id))

    incomplete = client.post(f"/api/content/questions/{qid}/reviews", headers=auth(editor_token), json={
        "stage": "editor", "decision": "approved", "checklist": {"clear_language": True},
    })
    assert incomplete.status_code == 422
    approved = client.post(f"/api/content/questions/{qid}/reviews", headers=auth(editor_token), json={
        "stage": "editor", "decision": "approved", "checklist": EDITOR_CHECKS,
    })
    assert approved.status_code == 200 and approved.json()["status"] == "editor_reviewed"
    wrong_role = client.post(f"/api/content/questions/{qid}/reviews", headers=auth(editor_token), json={
        "stage": "sme", "decision": "approved", "checklist": SME_CHECKS,
    })
    assert wrong_role.status_code == 403
    sme_approved = client.post(f"/api/content/questions/{qid}/reviews", headers=auth(sme_token), json={
        "stage": "sme", "decision": "approved", "checklist": SME_CHECKS,
    })
    assert sme_approved.status_code == 200 and sme_approved.json()["status"] == "sme_approved"
    publish = client.post(f"/api/content/questions/{qid}/publish", headers=auth(sme_token))
    assert publish.status_code == 409
    assert "citations_required" in publish.json()["detail"]["blockers"]


def test_snapshot_grounded_question_completes_release_and_exam_flow(client, admin_token):
    evidence = "Calcite has a Mohs hardness of 3 and scratches gypsum but not fluorite."
    with SessionLocal() as db:
        event = Event(slug="grounded-release", name="Rocks and Minerals", division="B", season=2026)
        source = Source(
            url="https://example.edu/mineral-hardness", title="University Mineral Guide",
            publisher="Example University", rights_status="fact_grounding_allowed",
            approved=True, content_hash="d" * 64, extracted_text=evidence,
        )
        db.add_all([event, source])
        db.flush()
        snapshot = SourceSnapshot(
            source_id=source.id, final_url=source.url, content_hash=source.content_hash,
            content_type="text/html", byte_count=len(evidence), extracted_text=evidence,
        )
        db.add(snapshot)
        db.flush()
        claim = ScientificClaim(
            source_id=source.id, source_snapshot_id=snapshot.id,
            claim_text="Calcite has Mohs hardness 3.", evidence_excerpt=evidence,
            locator="Mineral table, calcite row", confidence=1.0, approved=True,
        )
        db.add(claim)
        db.flush()
        question = Question(
            event_id=event.id, source_id=source.id, status="machine_validated",
            stem="A specimen scratches gypsum but cannot scratch fluorite. Which listed mineral best matches the evidence?",
            choices=["Calcite", "Quartz", "Talc", "Corundum"],
            answer_spec={"correct_index": 0, "points": 1},
            explanation="Calcite has Mohs hardness 3, between gypsum and fluorite.",
            citations=[{"source_id": source.id, "claim_id": claim.id}],
            validation_report={"passed": True, "errors": [], "warnings": []},
            similarity_report={"outcome": "clear", "max_similarity": 0.18},
        )
        editor = User(email="release-editor@example.com", full_name="Release Editor", role="editor")
        sme = User(email="release-sme@example.com", full_name="Release SME", role="sme")
        db.add_all([question, editor, sme])
        db.commit()
        event_id, qid = event.id, question.id
        editor_token = create_access_token(str(editor.id))
        sme_token = create_access_token(str(sme.id))

    queue = client.get("/api/content/questions/review-queue", headers=auth(editor_token))
    assert queue.status_code == 200
    citation = queue.json()[0]["citation_evidence"][0]
    assert citation["evidence_excerpt"] == evidence
    assert citation["snapshot_hash"] == "d" * 64

    assert client.post(f"/api/content/questions/{qid}/reviews", headers=auth(editor_token), json={
        "stage": "editor", "decision": "approved", "checklist": EDITOR_CHECKS,
    }).status_code == 200
    assert client.post(f"/api/content/questions/{qid}/reviews", headers=auth(sme_token), json={
        "stage": "sme", "decision": "approved", "checklist": SME_CHECKS,
    }).status_code == 200
    published = client.post(f"/api/content/questions/{qid}/publish", headers=auth(sme_token))
    assert published.status_code == 200 and published.json()["status"] == "published"

    exam = client.post("/api/exams", headers=auth(admin_token), json={
        "event_id": event_id, "title": "Grounded Mineral Practice", "duration_minutes": 10,
        "question_count": 1, "published": True,
    })
    assert exam.status_code == 200 and exam.json()["question_count"] == 1
