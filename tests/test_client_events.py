"""Browser breadcrumbs reach the request log so a silent client-side failure is visible."""
import json
import logging

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_client_events_are_logged_and_truncated(caplog):
    with caplog.at_level(logging.WARNING, logger="soplat.api"):
        r = client.post("/api/client-events", json={
            "events": [{"kind": "submit_blocked", "detail": {"reason": "busy", "note": "x" * 500}}],
            "page": "#practice", "build": "64"})
    assert r.status_code == 204
    line = next(m for m in caplog.messages if m.startswith("client_event "))
    data = json.loads(line.split(" ", 1)[1])
    assert data["kind"] == "submit_blocked" and data["d"]["reason"] == "busy"
    assert len(data["d"]["note"]) == 200


def test_client_events_rejects_oversized_batches():
    r = client.post("/api/client-events", json={"events": [{"kind": "k"}] * 21})
    assert r.status_code == 422
