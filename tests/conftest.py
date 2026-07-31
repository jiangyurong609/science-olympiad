import os
os.environ["DATABASE_URL"] = "sqlite:///./test_science_olympiad.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["ARTIFACT_STORE_PATH"] = "/tmp/science_olympiad_test_artifacts"
# Pin every externally-backed setting so a developer's .env can never change what the suite
# tests — e.g. ARTIFACT_STORE_BACKEND=gcs would send artifact writes to a real bucket.
os.environ["ARTIFACT_STORE_BACKEND"] = "local"
os.environ["ARTIFACT_STORE_BUCKET"] = ""
os.environ["GCS_SIGNING_SERVICE_ACCOUNT"] = ""
os.environ["VIDEO_RENDER_WORKER_URL"] = ""

import pytest
import shutil
from fastapi.testclient import TestClient
from app.core.database import Base, SessionLocal, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.entities import User


@pytest.fixture(autouse=True)
def reset_db():
    shutil.rmtree("/tmp/science_olympiad_test_artifacts", ignore_errors=True)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    shutil.rmtree("/tmp/science_olympiad_test_artifacts", ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def student_token(client):
    r = client.post("/api/auth/register", json={
        "email": "s@example.com", "full_name": "Student Test",
        "password": "password123", "division": "B",
    })
    return r.json()["access_token"]


@pytest.fixture
def admin_token():
    with SessionLocal() as db:
        user = User(
            email="a@example.com", full_name="Admin Test",
            password_hash=hash_password("password123"), role="admin",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return create_access_token(str(user.id))


@pytest.fixture
def coach_token():
    with SessionLocal() as db:
        user = User(
            email="coach@example.com", full_name="Coach Test",
            password_hash=hash_password("password123"), role="coach",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return create_access_token(str(user.id))
