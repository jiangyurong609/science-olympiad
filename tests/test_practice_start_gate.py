"""Machine-gated skill labs must be startable — as labelled practice.

The start gate used to demand human sign-off (sme_approved/calibrated) while the catalog
showed every published lab's card. No lab version ever carried those statuses, so every
start attempt since launch returned 409 and zero practice sessions were ever created.
The platform's actual policy is the disposition model: machine-gated content may serve as
practice when it is labelled as such — the same rule machine_practice exams follow.
"""
from app.core.database import SessionLocal
from app.models.entities import Event, PracticeSet, PracticeSetVersion


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _lab(db, slug, review_status):
    event = Event(slug=f"gate-{slug}", name=f"Gate {slug}", division="B", season=2026)
    db.add(event)
    db.flush()
    lab = PracticeSet(event_id=event.id, slug=slug, title=f"Lab {slug}", status="published")
    db.add(lab)
    db.flush()
    db.add(PracticeSetVersion(practice_set_id=lab.id, version=1, review_status=review_status,
                              items=[{"id": "i1", "prompt": "Which?", "choices": ["A", "B"],
                                      "correct_index": 0, "property_profile": []}]))
    lab.current_version = 1
    db.commit()
    return lab.id


def test_machine_validated_lab_starts_and_is_labelled(client, student_token):
    with SessionLocal() as db:
        lab_id = _lab(db, "machine-ok", "machine_validated")
    response = client.post(f"/api/practice-sets/{lab_id}/start", json={"mode": "study"},
                           headers=_auth(student_token))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["practice_set"]["unreviewed"] is True, \
        "machine-gated practice must carry the label the banner reads"
    assert payload["status"] == "in_progress"


def test_human_reviewed_lab_is_not_labelled(client, student_token):
    with SessionLocal() as db:
        lab_id = _lab(db, "sme-ok", "sme_approved")
    payload = client.post(f"/api/practice-sets/{lab_id}/start", json={"mode": "study"},
                          headers=_auth(student_token)).json()
    assert payload["practice_set"]["unreviewed"] is False


def test_unvalidated_lab_version_still_blocked(client, student_token):
    with SessionLocal() as db:
        lab_id = _lab(db, "draft-blocked", "draft")
    response = client.post(f"/api/practice-sets/{lab_id}/start", json={"mode": "study"},
                           headers=_auth(student_token))
    assert response.status_code == 409
