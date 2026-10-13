"""A short-answer transfer or retention check must accept a correct answer in the student's own
words. It used to demand an exact match with the key, so a case whose key read "Answers will
vary…" (or whose correct answer was merely phrased differently) could never be fixed."""
from app.core.database import SessionLocal
from app.models.entities import RemediationCase, TransferAttempt, User
from app.services import remediation
from app.services.answer_grading import ModelProviderError

KEY = "They are polymorphs. The atoms are arranged differently in their crystal structures."


def _transfer(db, key=KEY, review_phase=None):
    user = User(email="short-answer@example.com", full_name="S A", role="student", is_active=True)
    db.add(user)
    db.flush()
    case = RemediationCase(user_id=user.id, error_type="response_mismatch", status="guided_practice",
                           student_reflection="I confused the two minerals.", plan={}, diagnosis={})
    db.add(case)
    db.flush()
    payload = {"question_type": "short_answer", "stem": "Name the relationship between calcite and aragonite.",
               "answer_spec": {"answer": key, "points": 1}}
    if review_phase:
        payload["review_phase"] = review_phase
    transfer = TransferAttempt(remediation_case_id=case.id, user_id=user.id, question_payload=payload)
    db.add(transfer)
    db.commit()
    return transfer.id, case.id


def _verdict(verdict, credit):
    return lambda items: {0: {"id": 0, "verdict": verdict, "credit": credit, "rationale": "stub"}}


def test_correct_answer_in_own_words_passes_and_moves_the_case_on(monkeypatch):
    monkeypatch.setattr(remediation, "grade_batch", _verdict("correct", 1.0))
    with SessionLocal() as db:
        tid, cid = _transfer(db)
        result = remediation.grade_transfer(db, db.get(TransferAttempt, tid),
                                            {"text": "Polymorphs: the atoms have different arrangements"})
        assert result.is_correct is True
        assert db.get(RemediationCase, cid).status == "delayed_review"


def test_wrong_answer_still_fails_and_stays_in_practice(monkeypatch):
    monkeypatch.setattr(remediation, "grade_batch", _verdict("incorrect", 0.0))
    with SessionLocal() as db:
        tid, cid = _transfer(db)
        result = remediation.grade_transfer(db, db.get(TransferAttempt, tid), {"text": "Isotopes of one element"})
        assert result.is_correct is False
        assert result.diagnostic["error_type"] == "response_mismatch"
        assert db.get(RemediationCase, cid).status == "guided_practice"


def test_answers_will_vary_key_is_given_to_the_grader_as_an_example(monkeypatch):
    seen = {}

    def grader(items):
        seen.update(items[0])
        return {0: {"id": 0, "verdict": "correct", "credit": 1.0, "rationale": "stub"}}

    monkeypatch.setattr(remediation, "grade_batch", grader)
    with SessionLocal() as db:
        tid, _ = _transfer(db, key="Answers will vary. Example: Galena has a gray streak and cubic cleavage.")
        result = remediation.grade_transfer(db, db.get(TransferAttempt, tid),
                                            {"text": "Chalcopyrite: brassy yellow with a greenish-black streak."})
    assert result.is_correct is True
    assert "only an example" in seen["rubric"]


def test_exact_match_passes_without_calling_the_model(monkeypatch):
    def boom(items):
        raise AssertionError("an exact match must not need the model")

    monkeypatch.setattr(remediation, "grade_batch", boom)
    with SessionLocal() as db:
        tid, _ = _transfer(db, key="polymorphs")
        assert remediation.grade_transfer(db, db.get(TransferAttempt, tid), {"text": "Polymorphs"}).is_correct is True


def test_model_unavailable_falls_back_to_the_old_exact_match_rule(monkeypatch):
    def down(items):
        raise ModelProviderError("no provider")

    monkeypatch.setattr(remediation, "grade_batch", down)
    with SessionLocal() as db:
        tid, _ = _transfer(db)
        result = remediation.grade_transfer(db, db.get(TransferAttempt, tid), {"text": "Polymorphs: different arrangements"})
        assert result.is_correct is False  # unchanged behaviour, and no exception reaches the student


def test_blank_answer_never_reaches_the_model(monkeypatch):
    def boom(items):
        raise AssertionError("blank answers are never correct and never sent to the model")

    monkeypatch.setattr(remediation, "grade_batch", boom)
    with SessionLocal() as db:
        tid, _ = _transfer(db)
        assert remediation.grade_transfer(db, db.get(TransferAttempt, tid), {"text": "   "}).is_correct is False


def test_retention_check_uses_the_same_grading(monkeypatch):
    monkeypatch.setattr(remediation, "grade_batch", _verdict("correct", 1.0))
    with SessionLocal() as db:
        tid, cid = _transfer(db, review_phase="delayed")
        result = remediation.grade_delayed_review(db, db.get(TransferAttempt, tid),
                                                  {"text": "They are polymorphs with different atomic arrangements."})
        assert result.is_correct is True
        assert db.get(RemediationCase, cid).status == "resolved"
