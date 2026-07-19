from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.entities import (
    Event, EventSourceMap, Exam, Organization, Question, QuestionCalibration, Source, SourceMetadataCheck,
    Team, User,
)
from app.services.crawl_schedule import mark_crawl_success


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def add_question(db, event_id, status="published"):
    question = Question(
        event_id=event_id, status=status,
        stem="Which observation is the strongest repeatable evidence for this identification?",
        choices=["Measured hardness", "Specimen color alone", "A guess", "Container shape"],
        answer_spec={"correct_index": 0}, explanation="Hardness is a repeatable diagnostic property.",
        validation_report={"passed": True},
    )
    db.add(question)
    db.flush()
    return question


def test_foundational_exam_is_labeled_as_foundational_practice(client, admin_token):
    with SessionLocal() as db:
        event = Event(
            slug="foundational-ecology", name="Ecology", division="B", season=2026,
            season_status="foundational",
        )
        db.add(event)
        db.flush()
        add_question(db, event.id)
        db.commit()
        event_id = event.id
    created = client.post("/api/exams", headers=auth(admin_token), json={
        "event_id": event_id, "title": "Ecology Foundations", "question_count": 1,
        "published": True, "release_class": "reviewed_practice",
    })
    assert created.status_code == 200
    assert created.json()["release_class"] == "foundational_practice"
    listed = client.get("/api/exams", headers=auth(admin_token)).json()
    assert listed[0]["release_label"] == "Foundational Practice"
    assert listed[0]["season_status"] == "foundational"
    assert listed[0]["event_id"] == event_id
    assert listed[0]["event_slug"] == "foundational-ecology"
    assert listed[0]["event_division"] == "B"


def test_competition_release_requires_complete_current_source_coverage(client, admin_token):
    with SessionLocal() as db:
        event = Event(
            slug="unmapped-current", name="Current Event", division="C", season=2026,
            season_status="current",
        )
        db.add(event)
        db.flush()
        add_question(db, event.id, status="calibrated")
        db.commit()
        event_id = event.id
    blocked = client.post("/api/exams", headers=auth(admin_token), json={
        "event_id": event_id, "title": "Unsafe Competition Form", "question_count": 1,
        "published": True, "release_class": "competition_ready",
    })
    assert blocked.status_code == 409
    assert "event_source_coverage_not_release_ready" in blocked.json()["detail"]["blockers"]


def test_competition_release_records_coverage_snapshot_and_needs_calibrated_items(client, admin_token):
    with SessionLocal() as db:
        event = Event(
            slug="covered-current", name="Covered Current Event", division="C", season=2026,
            season_status="current",
        )
        source = Source(
            url="https://www.soinc.org/covered-event", title="Official Event Control",
            rights_status="metadata_only", approved=True,
        )
        db.add_all([event, source])
        db.flush()
        db.add(EventSourceMap(
            event_id=event.id, source_id=source.id, purpose="rules_control", source_tier=0,
            required=True, required_artifact_types=["metadata"], source_universe_version="2026.1",
            freshness_minutes=60, coverage_owner="Rules editor", reviewed=True,
        ))
        db.add(SourceMetadataCheck(
            source_id=source.id, final_url=source.url, status_code=200,
            content_type="text/html", checked_at=datetime.now(timezone.utc),
        ))
        mark_crawl_success(db, source, checked_at=datetime.now(timezone.utc))
        source.next_crawl_at = datetime.now(timezone.utc) + timedelta(hours=1)
        question = add_question(db, event.id, status="published")
        db.commit()
        event_id, question_id, source_id = event.id, question.id, source.id

    insufficient = client.post("/api/exams", headers=auth(admin_token), json={
        "event_id": event_id, "title": "Needs Calibration", "question_count": 1,
        "published": True, "release_class": "competition_ready",
    })
    assert insufficient.status_code == 409
    assert insufficient.json()["detail"]["available"] == 0

    with SessionLocal() as db:
        question = db.get(Question, question_id)
        question.status = "calibrated"
        db.commit()
    forged = client.post("/api/exams", headers=auth(admin_token), json={
        "event_id": event_id, "title": "Forged Calibration", "question_count": 1,
        "published": True, "release_class": "competition_ready",
    })
    assert forged.status_code == 409
    assert "calibration_evidence_missing" in forged.json()["detail"]["blockers"]

    with SessionLocal() as db:
        question = db.get(Question, question_id)
        db.add(QuestionCalibration(
            question_id=question.id, question_version=question.version, sample_size=30,
            metrics={"sample_size": 30, "facility": 0.5, "corrected_item_total_discrimination": 0.4},
            thresholds={"minimum_unique_students": 30}, deterministic_passed=True,
            decision="accepted", reviewer_user_id=1, notes="Synthetic release-gate fixture.",
        ))
        db.commit()
    released = client.post("/api/exams", headers=auth(admin_token), json={
        "event_id": event_id, "title": "Covered Competition Form", "question_count": 1,
        "published": True, "release_class": "competition_ready",
    })
    assert released.status_code == 200
    with SessionLocal() as db:
        exam = db.get(Exam, released.json()["id"])
        assert exam.coverage_snapshot["summary"]["competition_release_ready"] is True
        assert exam.coverage_snapshot["sources"][0]["source_universe_version"] == "2026.1"

    with SessionLocal() as db:
        db.get(Source, source_id).next_crawl_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    stale = client.post("/api/exams", headers=auth(admin_token), json={
        "event_id": event_id, "title": "Stale Competition Form", "question_count": 1,
        "published": True, "release_class": "competition_ready",
    })
    assert stale.status_code == 409
    assert "event_source_coverage_not_release_ready" in stale.json()["detail"]["blockers"]


def test_unpublished_exam_cannot_be_started_or_assigned(client, student_token):
    with SessionLocal() as db:
        org = Organization(name="Release Gate School", slug="release-gate-school")
        coach = User(email="release-coach@example.com", full_name="Release Coach", role="coach", organization_id=None)
        event = Event(slug="draft-exam", name="Draft Event", division="B", season=2026)
        db.add_all([org, coach, event])
        db.flush()
        coach.organization_id = org.id
        team = Team(
            organization_id=org.id, name="Draft Team", division="B", season=2026,
            created_by_user_id=coach.id,
        )
        exam = Exam(event_id=event.id, organization_id=org.id, title="Draft", published=False)
        db.add_all([team, exam])
        db.commit()
        coach_token = create_access_token(str(coach.id))
        exam_id, team_id = exam.id, team.id
    assert client.post(f"/api/exams/{exam_id}/start", headers=auth(student_token)).status_code == 404
    assigned = client.post("/api/assignments", headers=auth(coach_token), json={
        "team_id": team_id, "exam_id": exam_id, "title": "Do Not Release",
    })
    assert assigned.status_code == 409
    assert "Publish" in assigned.json()["detail"]
