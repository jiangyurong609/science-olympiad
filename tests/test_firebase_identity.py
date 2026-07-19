from types import SimpleNamespace

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import User


def firebase_settings():
    return SimpleNamespace(auth_provider="firebase", environment="test")


def verified_claims():
    return {
        "uid": "firebase-student-001",
        "email": "firebase@example.com",
        "email_verified": True,
    }


def test_firebase_bootstrap_creates_identity_mapping(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.get_settings", firebase_settings)
    monkeypatch.setattr("app.api.routes.verify_firebase_id_token", lambda token: verified_claims())

    response = client.post(
        "/api/auth/firebase/bootstrap",
        headers={"Authorization": "Bearer verified-token"},
        json={"full_name": "Firebase Student", "division": "B", "age_years": 14},
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "firebase@example.com"
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.firebase_uid == "firebase-student-001"))
        assert user is not None
        assert user.password_hash is None


def test_firebase_bootstrap_requires_verified_email(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.get_settings", firebase_settings)
    claims = {**verified_claims(), "email_verified": False}
    monkeypatch.setattr("app.api.routes.verify_firebase_id_token", lambda token: claims)

    response = client.post(
        "/api/auth/firebase/bootstrap",
        headers={"Authorization": "Bearer unverified-token"},
        json={"full_name": "Firebase Student", "division": "B"},
    )

    assert response.status_code == 403


def test_firebase_current_user_maps_uid_not_email(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.get_settings", firebase_settings)
    monkeypatch.setattr("app.api.routes.verify_firebase_id_token", lambda token: verified_claims())
    with SessionLocal() as db:
        db.add(User(
            email="firebase@example.com",
            full_name="Mapped Student",
            password_hash=None,
            firebase_uid="firebase-student-001",
            role="student",
            division="B",
        ))
        db.commit()

    response = client.get(
        "/api/student/dashboard",
        headers={"Authorization": "Bearer verified-token"},
    )

    assert response.status_code == 200
    assert response.json()["student"]["full_name"] == "Mapped Student"
