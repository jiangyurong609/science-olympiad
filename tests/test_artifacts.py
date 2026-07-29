import sys

import pytest

from app.services.artifacts import ArtifactError, scan_artifact_bytes


class _Settings:
    antivirus_command = ""
    antivirus_required = False


def test_optional_antivirus_preserves_basic_validation(monkeypatch):
    monkeypatch.setattr("app.services.artifacts.get_settings", lambda: _Settings())
    assert scan_artifact_bytes(b"safe educational content") == "basic_pass"


def test_configured_antivirus_streams_bytes_and_fails_closed(monkeypatch):
    settings = _Settings()
    settings.antivirus_required = True
    settings.antivirus_command = f"{sys.executable} -c 'import sys; sys.stdin.buffer.read()'"
    monkeypatch.setattr("app.services.artifacts.get_settings", lambda: settings)
    assert scan_artifact_bytes(b"safe educational content") == "antivirus_pass"

    settings.antivirus_command = f"{sys.executable} -c 'raise SystemExit(1)'"
    with pytest.raises(ArtifactError, match="rejected"):
        scan_artifact_bytes(b"known test signature")
