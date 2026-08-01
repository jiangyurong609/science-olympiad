"""Phase 0 — unreviewed content must be unservable, not merely labelled.

Four independent paths could publish or serve unreviewed items. These tests assert the
invariant holds at each one, that new exposure is refused, and — critically — that a student
already part-way through an attempt is never stranded.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import create_access_token, hash_password
from app.models.entities import (
    Attempt, Event, Exam, ExamItem, Question, QuestionStatus, User,
)
from app.services import student_visibility as sv


def _event(db, slug="ecology"):
    e = Event(slug=slug, name="Ecology", division="C", season=2026)
    db.add(e); db.flush()
    return e


def _question(db, event_id, status=QuestionStatus.DRAFT.value, stem="A question about ecosystems here."):
    q = Question(event_id=event_id, stem=stem, choices=["a", "b", "c", "d"],
                 answer_spec={"correct_index": 0}, status=status,
                 generation_provenance={"import_kind": "past_test"},
                 question_type="single_choice")
    db.add(q); db.flush()
    return q


def _exam(db, event_id, question_ids, *, published=True, disposition=sv.DISPOSITION_REVIEWED):
    ex = Exam(event_id=event_id, title="Practice", question_ids=question_ids,
              published=published, disposition=disposition, duration_minutes=20)
    db.add(ex); db.flush()
    for i, qid in enumerate(question_ids):
        q = db.get(Question, qid)
        db.add(ExamItem(exam_id=ex.id, question_id=qid, position=i,
                        snapshot={"stem": q.stem, "choices": q.choices,
                                  "answer_spec": q.answer_spec, "question_type": q.question_type}))
    db.flush()
    return ex


# ---------------------------------------------------------------- the rule

def test_only_human_accepted_items_are_student_ready():
    with SessionLocal() as db:
        e = _event(db)
        draft = _question(db, e.id, QuestionStatus.DRAFT.value)
        machine = _question(db, e.id, QuestionStatus.MACHINE_VALIDATED.value)
        published = _question(db, e.id, QuestionStatus.PUBLISHED.value)
        calibrated = _question(db, e.id, QuestionStatus.CALIBRATED.value)
        db.commit()
        assert not sv.item_is_student_ready(draft)
        assert not sv.item_is_student_ready(machine), "machine output is not human acceptance"
        assert sv.item_is_student_ready(published)
        assert sv.item_is_student_ready(calibrated)


def test_assert_publishable_rejects_unreviewed_and_missing_items():
    with SessionLocal() as db:
        e = _event(db)
        ok = _question(db, e.id, QuestionStatus.PUBLISHED.value)
        bad = _question(db, e.id, QuestionStatus.DRAFT.value)
        db.commit()
        sv.assert_publishable(db, [ok.id])
        with pytest.raises(sv.StudentVisibilityError, match="have not been reviewed"):
            sv.assert_publishable(db, [ok.id, bad.id])
        with pytest.raises(sv.StudentVisibilityError):
            sv.assert_publishable(db, [999999])   # a dangling id is not a free pass


# ---------------------------------------------------------------- path 1: mock exams

def test_mock_exam_no_longer_samples_unreviewed_items():
    """This path deliberately drew DRAFT items into a published exam."""
    from app.services.mock_exam import event_question_pool
    with SessionLocal() as db:
        e = _event(db)
        _question(db, e.id, QuestionStatus.DRAFT.value)
        _question(db, e.id, QuestionStatus.MACHINE_VALIDATED.value)
        ready = _question(db, e.id, QuestionStatus.PUBLISHED.value)
        db.commit()
        pool = event_question_pool(db, e)
    assert [q.id for q in pool] == [ready.id]


# ---------------------------------------------------------------- path 2: importer

def test_imported_exams_are_labelled_unreviewed_practice():
    with SessionLocal() as db:
        e = _event(db)
        q = _question(db, e.id, QuestionStatus.DRAFT.value)
        ex = _exam(db, e.id, [q.id], disposition=sv.DISPOSITION_UNREVIEWED_PRACTICE)
        db.commit()
        assert sv.is_unreviewed_practice(ex)
        allowed, reason = sv.can_start_new_attempt(db, ex)
        assert not allowed and "not been reviewed" in reason


# ---------------------------------------------------------------- exposure vs resumption

def test_new_attempts_refused_but_existing_work_is_preserved(client):
    """The critical Phase 0 guarantee: restricting an exam must never strand saved work."""
    with SessionLocal() as db:
        e = _event(db)
        q = _question(db, e.id, QuestionStatus.DRAFT.value)
        ex = _exam(db, e.id, [q.id], disposition=sv.DISPOSITION_REVIEWED)
        student = User(email="s1@example.com", full_name="S", password_hash=hash_password("x"),
                       role="student", division="C")
        other = User(email="s2@example.com", full_name="T", password_hash=hash_password("x"),
                     role="student", division="C")
        db.add_all([student, other]); db.flush()
        # this student is already mid-attempt
        db.add(Attempt(exam_id=ex.id, user_id=student.id, status="in_progress"))
        db.commit()
        exam_id, tok_existing = ex.id, create_access_token(str(student.id))
        tok_new = create_access_token(str(other.id))
        # now the exam is restricted after review found it unreviewed
        db.get(Exam, exam_id).disposition = sv.DISPOSITION_UNREVIEWED_PRACTICE
        db.commit()

    started = client.post(f"/api/exams/{exam_id}/start",
                          headers={"Authorization": f"Bearer {tok_new}"})
    assert started.status_code == 409, "a new student must not be sent into unreviewed content"

    resumed = client.post(f"/api/exams/{exam_id}/start",
                          headers={"Authorization": f"Bearer {tok_existing}"})
    assert resumed.status_code == 200, "a student mid-attempt must keep their saved work"


def test_withdrawn_exams_refuse_new_starts():
    with SessionLocal() as db:
        e = _event(db)
        q = _question(db, e.id, QuestionStatus.PUBLISHED.value)
        ex = _exam(db, e.id, [q.id], disposition=sv.DISPOSITION_WITHDRAWN)
        db.commit()
        allowed, _ = sv.can_start_new_attempt(db, ex)
        assert not allowed


def test_an_undecided_exam_is_judged_by_its_contents_not_waved_through():
    """`pending` must not be a licence, but it must not block legitimately reviewed content
    either — so it is classified from what the exam actually contains."""
    with SessionLocal() as db:
        e = _event(db)
        good = _question(db, e.id, QuestionStatus.PUBLISHED.value)
        bad = _question(db, e.id, QuestionStatus.DRAFT.value)
        clean = _exam(db, e.id, [good.id], disposition=sv.DISPOSITION_PENDING)
        dirty = _exam(db, e.id, [good.id, bad.id], disposition=sv.DISPOSITION_PENDING)
        db.commit()
        assert sv.can_start_new_attempt(db, clean)[0] is True
        assert sv.can_start_new_attempt(db, dirty)[0] is False


# ---------------------------------------------------------------- disposition sweep

def test_every_exam_earns_an_explicit_disposition():
    from scripts.disposition_exams import plan
    with SessionLocal() as db:
        e = _event(db)
        good = _question(db, e.id, QuestionStatus.PUBLISHED.value)
        bad = _question(db, e.id, QuestionStatus.DRAFT.value)
        clean = _exam(db, e.id, [good.id], disposition=sv.DISPOSITION_PENDING)
        dirty = _exam(db, e.id, [good.id, bad.id], disposition=sv.DISPOSITION_PENDING)
        empty = _exam(db, e.id, [], disposition=sv.DISPOSITION_PENDING)
        db.commit()
        rows = {r["exam_id"]: r for r in plan(db)}
    assert rows[clean.id]["to"] == sv.DISPOSITION_REVIEWED
    assert rows[dirty.id]["to"] == sv.DISPOSITION_UNREVIEWED_PRACTICE
    assert rows[empty.id]["to"] == sv.DISPOSITION_WITHDRAWN
    assert all(r["to"] != sv.DISPOSITION_PENDING for r in rows.values()), "nothing stays implicit"


def test_staff_cannot_publish_an_exam_of_unreviewed_items(client, admin_token):
    with SessionLocal() as db:
        e = _event(db)
        bad = _question(db, e.id, QuestionStatus.DRAFT.value)
        db.commit()
        event_id, qid = e.id, bad.id
    response = client.post("/api/exams", json={
        "event_id": event_id, "title": "Should fail", "question_ids": [qid],
        "duration_minutes": 20, "published": True, "release_class": "reviewed_practice",
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code in (400, 409, 422), (
        f"publishing unreviewed items must be refused, got {response.status_code}"
    )


# ---------------------------------------------------------------- review findings

def test_unpublishing_does_not_strand_an_active_attempt(client):
    """Quarantine and content-challenge paths set exam.published=False. Resumption is
    resolved before the publication gate, so saved work survives."""
    with SessionLocal() as db:
        e = _event(db)
        q = _question(db, e.id, QuestionStatus.PUBLISHED.value)
        ex = _exam(db, e.id, [q.id])
        student = User(email="mid@example.com", full_name="M", password_hash=hash_password("x"),
                       role="student", division="C")
        db.add(student); db.flush()
        db.add(Attempt(exam_id=ex.id, user_id=student.id, status="in_progress"))
        db.commit()
        exam_id, token = ex.id, create_access_token(str(student.id))
        db.get(Exam, exam_id).published = False       # withdrawn mid-attempt
        db.commit()

    resumed = client.post(f"/api/exams/{exam_id}/start",
                          headers={"Authorization": f"Bearer {token}"})
    assert resumed.status_code == 200, "unpublishing must not strand an attempt in progress"


def test_classifier_judges_served_snapshots_not_just_the_id_list():
    """start_exam serves ExamItem rows; judging exam.question_ids alone would let reviewed
    current questions authorise extra or stale snapshots."""
    with SessionLocal() as db:
        e = _event(db)
        good = _question(db, e.id, QuestionStatus.PUBLISHED.value)
        sneaky = _question(db, e.id, QuestionStatus.DRAFT.value)
        ex = _exam(db, e.id, [good.id])
        # an extra snapshot that the declared id list does not mention
        db.add(ExamItem(exam_id=ex.id, question_id=sneaky.id, position=1,
                        snapshot={"stem": sneaky.stem, "choices": sneaky.choices,
                                  "answer_spec": sneaky.answer_spec,
                                  "question_type": sneaky.question_type}))
        db.commit()
        assert sv.classify_exam(db, ex) == sv.DISPOSITION_UNREVIEWED_PRACTICE


def test_version_skew_is_not_waved_through_by_a_newer_approval():
    with SessionLocal() as db:
        e = _event(db)
        q = _question(db, e.id, QuestionStatus.PUBLISHED.value)
        ex = _exam(db, e.id, [q.id])
        item = db.scalars(select(ExamItem).where(ExamItem.exam_id == ex.id)).first()
        item.question_version = q.version + 3        # snapshot from a different version
        db.commit()
        assert sv.classify_exam(db, ex) == sv.DISPOSITION_UNREVIEWED_PRACTICE


def test_catalog_builder_no_longer_publishes():
    """scripts/build_courses.py created published lessons and exams outside the ladder."""
    source = open("scripts/build_courses.py").read()
    assert 'status="published"' not in source
    assert "published=True," not in source


def test_exam_creation_refuses_to_publish_an_unreviewed_item():
    """The create-exam endpoint asserts DISPOSITION_REVIEWED from `published=True` alone.
    Its pool filter should make that true; asserting it means a future change to the filter
    fails loudly rather than silently publishing unreviewed items."""
    import pytest

    from app.core.database import SessionLocal
    from app.models.entities import Event, Question
    from app.services import student_visibility as sv

    with SessionLocal() as db:
        event = Event(slug="assert-ev", name="E", division="B", season=2026)
        db.add(event); db.flush()
        draft = Question(event_id=event.id, stem="Unreviewed", question_type="single_choice",
                         choices=["a", "b"], answer_spec={"correct_index": 0},
                         status="machine_validated")
        db.add(draft); db.flush()
        with pytest.raises(sv.StudentVisibilityError):
            sv.assert_publishable(db, [draft.id], what="exam")


def test_the_student_ready_set_is_defined_once():
    """`allowed_statuses` in the create-exam path used to spell the set out again. Two
    spellings of one rule is how every visibility defect in this codebase started."""
    from app.services import student_visibility as sv
    assert sv.STUDENT_READY_ITEM_STATUSES == {"published", "calibrated"}
