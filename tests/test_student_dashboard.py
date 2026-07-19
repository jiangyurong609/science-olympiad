from app.core.database import SessionLocal
from app.models.entities import Concept, Event


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_student_dashboard_requires_authentication(client):
    response = client.get("/api/student/dashboard")
    assert response.status_code == 401


def test_student_dashboard_returns_learning_state(client, student_token):
    with SessionLocal() as db:
        event = Event(
            slug="rocks-and-minerals",
            name="Rocks and Minerals",
            division="B/C",
            season=2026,
            modality="stations",
            description="Identification and Earth science.",
        )
        db.add(event)
        db.flush()
        db.add(Concept(event_id=event.id, name="Mineral properties", description="Use evidence."))
        db.commit()

    response = client.get("/api/student/dashboard", headers=auth(student_token))

    assert response.status_code == 200
    body = response.json()
    assert body["student"]["division"] == "B"
    assert any(item["name"] == "Mineral properties" for item in body["concepts"])
    assert body["open_remediation"] == []
    assert body["assignments"] == []


def test_login_returns_division(client):
    client.post(
        "/api/auth/register",
        json={
            "email": "division@example.com",
            "full_name": "Division Student",
            "password": "password123",
            "division": "C",
        },
    )
    response = client.post(
        "/api/auth/login",
        json={"email": "division@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["division"] == "C"
