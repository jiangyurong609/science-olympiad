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


def test_review_queue_can_be_scoped_to_one_course(client, admin_token):
    """820 machine-validated items were returned in one unscoped response.

    A reviewer clearing a single course had no way to see only its items, which makes a
    bounded task look unbounded — and the bottleneck here is reviewer attention, not compute.
    """
    from app.core.database import SessionLocal
    from app.models.entities import (
        Concept, Course, CourseUnit, Event, Question, Skill,
    )
    with SessionLocal() as db:
        event = Event(slug="scoped-ev", name="E", division="B", season=2026)
        db.add(event); db.flush()
        course = Course(event_id=event.id, slug="scoped-course", title="C", status="draft")
        db.add(course); db.flush()
        unit = CourseUnit(course_id=course.id, slug="su", title="U", sequence=1)
        db.add(unit); db.flush()
        concept = Concept(event_id=event.id, name="Scoped concept")
        db.add(concept); db.flush()
        db.add(Skill(course_id=course.id, unit_id=unit.id, concept_id=concept.id,
                     slug="sk", name="S", sequence=1))
        db.add(Question(event_id=event.id, concept_id=concept.id, stem="In scope",
                        question_type="single_choice", choices=["a", "b"],
                        answer_spec={"correct_index": 0}, status="machine_validated"))
        db.add(Question(event_id=event.id, stem="Out of scope — no concept",
                        question_type="single_choice", choices=["a", "b"],
                        answer_spec={"correct_index": 0}, status="machine_validated"))
        db.commit()
        course_id = course.id

    headers = {"Authorization": f"Bearer {admin_token}"}
    scoped = client.get(f"/api/content/questions/review-queue?course_id={course_id}",
                        headers=headers).json()
    stems = {row["stem"] for row in scoped}
    assert "In scope" in stems
    assert "Out of scope — no concept" not in stems


def test_a_course_whose_skills_have_no_concept_returns_nothing_not_everything(
        client, admin_token):
    """An empty IN () clause would otherwise match the whole catalog — the same class of
    error that made every skill report zero questions."""
    from app.core.database import SessionLocal
    from app.models.entities import Course, CourseUnit, Event, Question, Skill
    with SessionLocal() as db:
        event = Event(slug="no-concept-ev", name="E", division="B", season=2026)
        db.add(event); db.flush()
        course = Course(event_id=event.id, slug="no-concept-course", title="C", status="draft")
        db.add(course); db.flush()
        unit = CourseUnit(course_id=course.id, slug="ncu", title="U", sequence=1)
        db.add(unit); db.flush()
        db.add(Skill(course_id=course.id, unit_id=unit.id, slug="nc", name="S", sequence=1))
        db.add(Question(event_id=event.id, stem="Should not appear",
                        question_type="single_choice", choices=["a", "b"],
                        answer_spec={"correct_index": 0}, status="machine_validated"))
        db.commit()
        course_id = course.id

    rows = client.get(f"/api/content/questions/review-queue?course_id={course_id}",
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert rows == []


def test_review_evidence_surfaces_the_decisive_signals(client, admin_token):
    """The solver verdict was several levels down inside validation_report; a reviewer with
    72 items should not have to read nested JSON for the single most decisive signal."""
    from app.core.database import SessionLocal
    from app.models.entities import Event, Question
    with SessionLocal() as db:
        event = Event(slug="ev-evidence", name="E", division="B", season=2026)
        db.add(event); db.flush()
        db.add(Question(
            event_id=event.id, stem="Evidence item", question_type="single_choice",
            choices=["a", "b"], answer_spec={"correct_index": 0},
            status="machine_validated",
            validation_report={
                "passed": True, "claim_ids": [7],
                "independent_solver": {"passed": True, "verdict": "solver_agrees",
                                       "chosen_index": 0},
                "independent_verifier": {"passed": True, "errors": [], "warnings": []},
                "factual_grounding": "approved_claims",   # older runs store a bare string
                "rights_check": True,                      # and a bare bool here
            },
            similarity_report={"max_similarity": 0.41, "outcome": "clear"}))
        db.commit()

    rows = client.get("/api/content/questions/review-queue",
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    row = next(r for r in rows if r["stem"] == "Evidence item")
    evidence = row["review_evidence"]
    assert evidence["gates_run"] is True
    assert evidence["solver_agreed"] is True
    assert evidence["solver_verdict"] == "solver_agrees"
    assert evidence["verifier_passed"] is True
    assert evidence["grounding"] == "approved_claims", "a bare string must not crash or vanish"
    assert evidence["rights_cleared"] is True, "nor a bare bool"
    assert evidence["max_similarity"] == 0.41


def test_an_item_that_never_faced_the_gates_does_not_look_vetted(client, admin_token):
    """684 of 820 machine-validated items predate the hardened generator and were never
    blind-solved. Rendering a missing gate as a passing one would tell a reviewer they had
    been checked."""
    from app.core.database import SessionLocal
    from app.models.entities import Event, Question
    with SessionLocal() as db:
        event = Event(slug="ev-ungated", name="E", division="B", season=2026)
        db.add(event); db.flush()
        db.add(Question(event_id=event.id, stem="Never gated", question_type="single_choice",
                        choices=["a", "b"], answer_spec={"correct_index": 0},
                        status="machine_validated", validation_report={"passed": True}))
        db.commit()

    rows = client.get("/api/content/questions/review-queue",
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    evidence = next(r for r in rows if r["stem"] == "Never gated")["review_evidence"]
    assert evidence["gates_run"] is False
    assert evidence["solver_agreed"] is None, "absent must not read as passed"
    assert evidence["verifier_passed"] is None


def test_a_verifier_check_list_is_not_reported_as_a_verdict(client, admin_token):
    """Some payloads put per-check findings in `passed` instead of a boolean. A reviewer
    glancing at `verifier_passed: [...]` would read a truthy list as a pass."""
    from app.core.database import SessionLocal
    from app.models.entities import Event, Question
    with SessionLocal() as db:
        event = Event(slug="ev-checklist", name="E", division="B", season=2026)
        db.add(event); db.flush()
        db.add(Question(
            event_id=event.id, stem="Checklist verifier", question_type="single_choice",
            choices=["a", "b"], answer_spec={"correct_index": 0},
            status="machine_validated",
            validation_report={
                "passed": True,
                "independent_solver": {"passed": True, "verdict": "solver_agrees"},
                "independent_verifier": {
                    "passed": [{"check": "factual support", "details": "supported"}],
                    "errors": [],
                },
            }))
        db.commit()

    rows = client.get("/api/content/questions/review-queue",
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    evidence = next(r for r in rows if r["stem"] == "Checklist verifier")["review_evidence"]
    assert evidence["verifier_passed"] is True, "derived from there being no errors"
    assert len(evidence["verifier_checks"]) == 1, "and the findings are kept, named honestly"


def test_a_verifier_that_reported_errors_is_not_a_pass(client, admin_token):
    from app.core.database import SessionLocal
    from app.models.entities import Event, Question
    with SessionLocal() as db:
        event = Event(slug="ev-vfail", name="E", division="B", season=2026)
        db.add(event); db.flush()
        db.add(Question(
            event_id=event.id, stem="Verifier objected", question_type="single_choice",
            choices=["a", "b"], answer_spec={"correct_index": 0},
            status="machine_validated",
            validation_report={
                "passed": True,
                "independent_solver": {"passed": True},
                "independent_verifier": {"passed": [], "errors": ["two answers defensible"]},
            }))
        db.commit()

    rows = client.get("/api/content/questions/review-queue",
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    evidence = next(r for r in rows if r["stem"] == "Verifier objected")["review_evidence"]
    assert evidence["verifier_passed"] is False
    assert evidence["verifier_errors"] == ["two answers defensible"]
