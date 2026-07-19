def test_register_login_and_duplicate(client):
    payload = {
        "email": "user@example.com", "full_name": "Test User",
        "password": "password123", "division": "B",
    }
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 200
    assert r.json()["access_token"]
    assert r.json()["user"]["role"] == "student"
    assert client.post("/api/auth/register", json=payload).status_code == 409
    login = client.post("/api/auth/login", json={"email": payload["email"], "password": payload["password"]})
    assert login.status_code == 200


def test_public_registration_cannot_escalate_role(client):
    r = client.post("/api/auth/register", json={
        "email": "attacker@example.com", "full_name": "Attacker",
        "password": "password123", "role": "admin",
    })
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "student"


def test_bad_login(client):
    assert client.post("/api/auth/login", json={"email": "none@example.com", "password": "wrongpass"}).status_code == 401


def test_auth_config_defaults_to_local_without_exposing_firebase(client):
    response = client.get("/api/auth/config")
    assert response.status_code == 200
    assert response.json() == {
        "provider": "local",
        "firebase_project_id": None,
        "firebase_web_api_key": None,
    }
