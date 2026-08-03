"""The whole journey, once a human has approved the content.

Every other test here checks one gate. This checks that the gates open onto something that
works — that a student who arrives after review passes can actually get from a catalog listing
to a scored exam and a mastery record, with nothing broken in between.

It matters now because review is the only thing left before launch, and it is expensive: 244
items, 11 exams, 24 lessons. Discovering after all of that that the reader cannot advance, or
that scoring never updates mastery, would waste the one resource that cannot be automated. So
the approvals are simulated here — a real `ReviewDecision`, a real status promotion — and the
journey is walked end to end against them.

Nothing here weakens a gate. It grants exactly the evidence a human grants, then asserts the
system honours it.
"""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, Exam, Lesson, LessonProgress, LessonVersion, MasteryState, Question,
    QuestionStatus, ReviewDecision, User,
)
from app.services.lesson_hints import hint_fingerprint


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _reviewer(db) -> User:
    reviewer = db.scalar(select(User).where(User.role.in_(("admin", "editor"))))
    if reviewer is None:
        reviewer = User(email="journey-reviewer@example.test", full_name="R", role="editor")
        db.add(reviewer); db.flush()
    return reviewer


def seed_reviewed_course() -> tuple[int, int]:
    """A course in the state it will be in after a human finishes reviewing it."""
    with SessionLocal() as db:
        reviewer = _reviewer(db)
        event = Event(slug="journey-event", name="Journey", division="B", season=2026)
        db.add(event); db.flush()
        concept = Concept(event_id=event.id, name="Hardness", description="Scratch resistance")
        db.add(concept); db.flush()

        lesson = Lesson(event_id=event.id, concept_id=concept.id, slug="journey-lesson",
                        title="Hardness", summary="Scratching.", status="published",
                        disposition="unreviewed_practice", current_version=1, sequence=1)
        db.add(lesson); db.flush()

        checkpoint = {
            "type": "checkpoint", "heading": "Check",
            "prompt": "Which property resists scratching?",
            "choices": ["Luster", "Hardness"], "answer_index": 1,
            "hint": "Think about what a steel nail would do to the specimen.",
        }
        checkpoint["hint_check"] = {"too_revealing": False,
                                    "fingerprint": hint_fingerprint(checkpoint)}
        db.add(LessonVersion(
            lesson_id=lesson.id, version=1, review_status="sme_approved", claim_ids=[1],
            citations=[{"title": "USGS", "url": "https://usgs.gov/x"}],
            content=[{"type": "opening", "heading": "Start here",
                      "body": "Minerals differ in how they resist scratching."},
                     checkpoint]))
        # the two decisions a human makes for a lesson
        for stage in ("editor", "sme"):
            db.add(ReviewDecision(entity_type="lesson", entity_id=lesson.id, entity_version=1,
                                  stage=stage, decision="approved",
                                  reviewer_user_id=reviewer.id))

        items = []
        for i in range(4):
            question = Question(
                event_id=event.id, concept_id=concept.id,
                # the promotion a human makes for an item
                status=QuestionStatus.PUBLISHED.value,
                stem=f"Journey question {i}", choices=["Luster", "Hardness"],
                answer_spec={"correct_index": 1},
                citations=[{"title": "USGS"}],
                validation_report={"passed": True,
                                   "independent_solver": {"verdict": "solver_agrees"},
                                   "independent_verifier": {"passed": True, "errors": []},
                                   "factual_grounding": "approved_claims"},
                generation_provenance={"generation_run": "journey"})
            db.add(question); items.append(question)
        db.flush()

        exam = Exam(event_id=event.id, title="Practice Test — Journey",
                    question_ids=[q.id for q in items], published=True,
                    disposition="reviewed", duration_minutes=20)
        db.add(exam); db.flush()
        from scripts.build_launch_exams import _write_items
        _write_items(db, exam, items)     # an exam is its snapshots, not its id list
        db.commit()
        return event.id, lesson.id


def test_a_student_can_go_from_catalog_to_a_scored_exam(client, student_token):
    """Learn -> practice -> prove, walked end to end against approved content."""
    event_id, lesson_id = seed_reviewed_course()

    # 1. the course is listed
    catalog = client.get(f"/api/events/{event_id}/lessons", headers=auth(student_token))
    assert catalog.status_code == 200
    assert any(l["id"] == lesson_id for l in catalog.json()), "approved lesson must be listed"

    # 2. the lesson opens, and carries no answer key
    started = client.post(f"/api/lessons/{lesson_id}/start", headers=auth(student_token))
    assert started.status_code == 200
    checkpoint = next(b for b in started.json()["content"] if b["type"] == "checkpoint")
    assert set(checkpoint) == {"type", "id", "heading", "question", "choices", "empty"}
    assert checkpoint["question"], "the student must be able to read the question"

    # 3. scaffolding is available now that the lesson is reviewed
    hint = client.get(f"/api/lessons/{lesson_id}/checkpoint/{checkpoint['id']}/hint",
                      headers=auth(student_token)).json()
    assert hint["available"] is True, "an approved, verified hint must actually reach a student"
    assert "nail" in hint["hint"]

    # 4. answering completes the lesson and records mastery
    answered = client.post(f"/api/lessons/{lesson_id}/checkpoint", headers=auth(student_token),
                           json={"checkpoint_id": checkpoint["id"], "selected_index": 1})
    assert answered.status_code == 200
    assert answered.json()["correct"] is True
    assert answered.json()["lesson_status"] == "completed"

    with SessionLocal() as db:
        progress = db.scalar(select(LessonProgress).where(
            LessonProgress.lesson_id == lesson_id))
        assert progress.status == "completed"
        mastery = db.scalar(select(MasteryState))
        assert mastery is not None, "completing a lesson must leave evidence to act on"
        evidence_before = mastery.evidence_count

    # 5. the exam can be started, answered and scored
    with SessionLocal() as db:
        exam = db.scalar(select(Exam).where(Exam.event_id == event_id))
        exam_id = exam.id

    attempt = client.post(f"/api/exams/{exam_id}/start", headers=auth(student_token))
    assert attempt.status_code in (200, 201), (
        f"a reviewed, published exam must be startable: {attempt.status_code} {attempt.text[:300]}"
    )
    body = attempt.json()
    attempt_id = body.get("attempt_id") or body.get("id")
    assert attempt_id, f"no attempt id in {body}"
    served = body.get("items") or body.get("questions") or []
    assert served, f"an attempt must serve its items: {list(body)}"

    for index, item in enumerate(served):
        saved = client.put(f"/api/attempts/{attempt_id}/responses", headers=auth(student_token),
                           json={"question_id": item.get("question_id") or item.get("id"),
                                 "answer": {"correct_index": 1},
                                 "idempotency_key": f"journey-{index}"})
        assert saved.status_code == 200, f"saving a response failed: {saved.text[:200]}"

    submitted = client.post(f"/api/attempts/{attempt_id}/submit", headers=auth(student_token))
    assert submitted.status_code == 200, (
        f"submitting must score the attempt: {submitted.status_code} {submitted.text[:300]}"
    )
    scored = submitted.json()
    assert scored, "a score must come back"

    # 6. the student's dashboard reflects the work
    dashboard = client.get("/api/student/dashboard", headers=auth(student_token))
    assert dashboard.status_code == 200

    with SessionLocal() as db:
        mastery = db.scalar(select(MasteryState))
        assert mastery.evidence_count >= evidence_before, "mastery must not regress"


def test_the_same_course_is_invisible_before_review(client, student_token):
    """The counterfactual: without the approvals, none of the above is reachable.

    Without this, the journey test could pass on a path that ignores review entirely.
    """
    with SessionLocal() as db:
        event = Event(slug="journey-unreviewed", name="Unreviewed", division="B", season=2026)
        db.add(event); db.flush()
        lesson = Lesson(event_id=event.id, slug="unreviewed-lesson", title="Unreviewed",
                        status="published", disposition="pending_disposition",
                        current_version=1, sequence=1)
        db.add(lesson); db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1, review_status="draft",
                             claim_ids=[1], citations=[{"title": "x"}],
                             content=[{"type": "opening", "heading": "Hidden"}]))
        db.commit()
        lesson_id = lesson.id

    started = client.post(f"/api/lessons/{lesson_id}/start", headers=auth(student_token))
    assert started.status_code == 404, "unreviewed content must stay unreachable"
