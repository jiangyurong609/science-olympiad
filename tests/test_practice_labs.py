from sqlalchemy import select
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, MasteryState, PracticeSession, PracticeSet, PracticeSetVersion,
    RemediationCase, TransferAttempt,
)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_practice_set():
    with SessionLocal() as db:
        event = Event(slug="practice-rocks", name="Rocks", division="B", season=2026)
        db.add(event)
        db.flush()
        concept = Concept(event_id=event.id, name="Identification")
        db.add(concept)
        db.flush()
        practice_set = PracticeSet(
            event_id=event.id,
            concept_id=concept.id,
            slug="mystery",
            title="Mystery Lab",
            summary="Use evidence.",
            status="published",
            current_version=1,
        )
        db.add(practice_set)
        db.flush()
        db.add(PracticeSetVersion(
            practice_set_id=practice_set.id,
            version=1,
            review_status="sme_approved",
            claim_ids=[1],
            citations=[{"title": "Government source"}],
            items=[
                {
                    "id": "one",
                    "prompt": "Identify one.",
                    "property_profile": [{"label": "Hardness", "value": "7"}],
                    "choices": ["Quartz", "Gypsum"],
                    "correct_index": 0,
                    "explanation": "Quartz has hardness 7.",
                    "misconception_by_choice": {"1": "Gypsum is softer."},
                },
                {
                    "id": "two",
                    "prompt": "Identify two.",
                    "property_profile": [{"label": "Magnetism", "value": "Strong"}],
                    "choices": ["Calcite", "Magnetite"],
                    "correct_index": 1,
                    "explanation": "Magnetite is strongly magnetic.",
                },
            ],
        ))
        db.commit()
        return event.id, concept.id, practice_set.id


def test_practice_catalog_start_hides_answers_and_resumes(client, student_token):
    event_id, _, practice_set_id = create_practice_set()
    catalog = client.get(
        f"/api/events/{event_id}/practice-sets", headers=auth(student_token)
    )
    assert catalog.status_code == 200
    assert catalog.json()[0]["latest_session"] is None
    started = client.post(
        f"/api/practice-sets/{practice_set_id}/start", headers=auth(student_token)
    )
    assert started.status_code == 200
    assert started.json()["current_item"]["id"] == "one"
    assert "correct_index" not in started.json()["current_item"]
    assert "explanation" not in started.json()["current_item"]
    resumed = client.post(
        f"/api/practice-sets/{practice_set_id}/start", headers=auth(student_token)
    )
    assert resumed.json()["session_id"] == started.json()["session_id"]


def test_practice_commits_once_completes_and_updates_mastery(client, student_token):
    _, concept_id, practice_set_id = create_practice_set()
    session = client.post(
        f"/api/practice-sets/{practice_set_id}/start", headers=auth(student_token)
    ).json()
    first = client.post(
        f"/api/practice/sessions/{session['session_id']}/answer",
        headers=auth(student_token),
        json={"item_id": "one", "selected_index": 1},
    )
    assert first.status_code == 200
    assert first.json()["correct"] is False
    assert first.json()["misconception"] == "Gypsum is softer."
    assert first.json()["current_item"]["id"] == "two"
    duplicate = client.post(
        f"/api/practice/sessions/{session['session_id']}/answer",
        headers=auth(student_token),
        json={"item_id": "one", "selected_index": 0},
    )
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["correct"] is False
    second = client.post(
        f"/api/practice/sessions/{session['session_id']}/answer",
        headers=auth(student_token),
        json={"item_id": "two", "selected_index": 1},
    )
    assert second.json()["status"] == "completed"
    assert second.json()["score"] == 1
    assert second.json()["current_item"] is None
    with SessionLocal() as db:
        stored = db.get(PracticeSession, session["session_id"])
        mastery = db.scalar(select(MasteryState).where(
            MasteryState.concept_id == concept_id
        ))
        assert stored.status == "completed"
        assert len(stored.results) == 2
        assert mastery.evidence_count == 2
        assert mastery.mastery_probability > 0.5


def test_station_mode_uses_server_deadline_and_separate_session(client, student_token):
    _, _, practice_set_id = create_practice_set()
    study = client.post(
        f"/api/practice-sets/{practice_set_id}/start",
        headers=auth(student_token),
        json={"mode": "study"},
    ).json()
    station = client.post(
        f"/api/practice-sets/{practice_set_id}/start",
        headers=auth(student_token),
        json={"mode": "station", "seconds_per_item": 45},
    ).json()
    assert station["session_id"] != study["session_id"]
    assert station["mode"] == "station"
    assert station["seconds_per_item"] == 45
    assert station["item_deadline_at"].endswith("Z")

    early_timeout = client.post(
        f"/api/practice/sessions/{station['session_id']}/answer",
        headers=auth(student_token),
        json={"item_id": "one", "timed_out": True},
    )
    assert early_timeout.status_code == 409
    with SessionLocal() as db:
        stored = db.get(PracticeSession, station["session_id"])
        stored.item_started_at = datetime.now(timezone.utc) - timedelta(seconds=46)
        db.commit()
    expired = client.post(
        f"/api/practice/sessions/{station['session_id']}/answer",
        headers=auth(student_token),
        json={"item_id": "one", "selected_index": 0},
    )
    assert expired.status_code == 200
    assert expired.json()["timed_out"] is True
    assert expired.json()["correct"] is False
    assert expired.json()["score"] == 0
    assert expired.json()["current_item"]["id"] == "two"


def test_practice_miss_follows_through_transfer_and_delayed_review(client, student_token):
    _, _, practice_set_id = create_practice_set()
    session = client.post(
        f"/api/practice-sets/{practice_set_id}/start",
        headers=auth(student_token),
        json={"mode": "study"},
    ).json()
    miss = client.post(
        f"/api/practice/sessions/{session['session_id']}/answer",
        headers=auth(student_token),
        json={"item_id": "one", "selected_index": 1},
    ).json()
    case_id = miss["remediation_case_id"]
    assert case_id
    duplicate = client.post(
        f"/api/practice/sessions/{session['session_id']}/answer",
        headers=auth(student_token),
        json={"item_id": "one", "selected_index": 1},
    ).json()
    assert duplicate["remediation_case_id"] == case_id
    with SessionLocal() as db:
        cases = db.scalars(select(RemediationCase).where(
            RemediationCase.source_ref == f"practice:{session['session_id']}:one"
        )).all()
        assert len(cases) == 1
        assert cases[0].question_id is None
        assert cases[0].diagnosis["evidence_profile"][0]["value"] == "7"

    dashboard = client.get("/api/student/dashboard", headers=auth(student_token)).json()
    notebook_case = next(row for row in dashboard["open_remediation"] if row["id"] == case_id)
    assert notebook_case["source_type"] == "practice"
    assert notebook_case["question_stem"] == "Identify one."
    reflection = client.put(
        f"/api/remediation/{case_id}/reflection",
        headers=auth(student_token),
        json={"reflection": "I relied on the name instead of using hardness as the deciding clue."},
    )
    assert reflection.json()["status"] == "guided_practice"
    transfer = client.post(
        f"/api/remediation/{case_id}/transfer", headers=auth(student_token)
    ).json()
    with SessionLocal() as db:
        transfer_row = db.get(TransferAttempt, transfer["transfer_id"])
        correct_index = transfer_row.question_payload["answer_spec"]["correct_index"]
    transfer_result = client.post(
        f"/api/remediation/transfer/{transfer['transfer_id']}/submit",
        headers=auth(student_token),
        json={"answer": {"selected_index": correct_index}},
    ).json()
    assert transfer_result["correct"] is True
    assert transfer_result["remediation_status"] == "delayed_review"

    with SessionLocal() as db:
        case = db.get(RemediationCase, case_id)
        case.plan = {
            **case.plan,
            "next_review_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        }
        db.commit()
    delayed = client.post(
        f"/api/remediation/{case_id}/delayed-review", headers=auth(student_token)
    ).json()
    with SessionLocal() as db:
        delayed_row = db.get(TransferAttempt, delayed["transfer_id"])
        delayed_correct = delayed_row.question_payload["answer_spec"]["correct_index"]
    retained = client.post(
        f"/api/remediation/delayed-review/{delayed['transfer_id']}/submit",
        headers=auth(student_token),
        json={"answer": {"selected_index": delayed_correct}},
    ).json()
    assert retained["correct"] is True
    assert retained["remediation_status"] == "resolved"
    dashboard = client.get("/api/student/dashboard", headers=auth(student_token)).json()
    assert case_id not in {row["id"] for row in dashboard["open_remediation"]}
