"""My Results lists finished exams with how many fixes each still owes. A case that passed its
transfer check (waiting on a dated recheck) or is resolved is not owed any more."""
from datetime import datetime, timezone

from app.api import routes
from app.core.database import SessionLocal
from app.models.entities import Attempt, Event, Exam, RemediationCase, User


def test_open_fixes_counts_only_cases_still_owed():
    with SessionLocal() as db:
        user = User(email="results-owed@example.com", full_name="R O", role="student", is_active=True)
        event = Event(slug="owed-fixes", name="Owed Fixes", division="B", season=2027)
        db.add_all([user, event])
        db.flush()
        exam = Exam(event_id=event.id, title="Owed Fixes Exam")
        db.add(exam)
        db.flush()
        attempt = Attempt(user_id=user.id, exam_id=exam.id, status="remediation_open",
                          submitted_at=datetime.now(timezone.utc), score=1, max_score=4)
        db.add(attempt)
        db.flush()
        for n, status in enumerate(["open", "guided_practice", "delayed_review", "resolved"]):
            db.add(RemediationCase(attempt_id=attempt.id, user_id=user.id, source_ref=f"r{n}",
                                   error_type="x", status=status, plan={}, diagnosis={}))
        db.commit()
        row = routes.my_attempts(limit=50, db=db, user=user)["attempts"][0]
        assert row["attempt_id"] == attempt.id
        assert row["exam_id"] == exam.id
        assert row["open_fixes"] == 2
