from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from app.core.config import get_settings


class ArtifactError(ValueError):
    pass


def _extension(media_type: str) -> str:
    if "pdf" in media_type:
        return ".pdf"
    if "html" in media_type:
        return ".html"
    if "json" in media_type:
        return ".json"
    return ".bin"


def validate_raw_artifact(content: bytes, media_type: str) -> str:
    if not content:
        raise ArtifactError("Fetched artifact is empty")
    lowered = media_type.lower()
    if "pdf" in lowered and not content.startswith(b"%PDF-"):
        raise ArtifactError("PDF content does not match its declared media type")
    if ("html" in lowered or lowered.startswith("text/")) and b"\x00" in content[:8192]:
        raise ArtifactError("Text artifact contains unexpected binary data")
    return "basic_pass"


def store_raw_artifact(content: bytes, media_type: str) -> dict:
    scan_status = validate_raw_artifact(content, media_type)
    digest = hashlib.sha256(content).hexdigest()
    relative = Path(digest[:2]) / f"{digest}{_extension(media_type)}"
    settings = get_settings()
    if settings.artifact_store_backend == "gcs":
        if not settings.artifact_store_bucket:
            raise ArtifactError("GCS artifact bucket is not configured")
        try:
            from google.cloud import storage

            client = storage.Client()
            bucket = client.bucket(settings.artifact_store_bucket)
            blob = bucket.blob(relative.as_posix())
            if not blob.exists(client):
                blob.upload_from_string(content, content_type=media_type or "application/octet-stream")
        except Exception as error:  # noqa: BLE001 — normalize provider failures
            raise ArtifactError(f"GCS artifact upload failed: {error}") from error
        return {
            "storage_key": relative.as_posix(),
            "content_hash": digest,
            "byte_count": len(content),
            "detected_media_type": media_type,
            "scan_status": scan_status,
        }

    root = Path(settings.artifact_store_path).expanduser().resolve()
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
    return {
        "storage_key": relative.as_posix(),
        "content_hash": digest,
        "byte_count": len(content),
        "detected_media_type": media_type,
        "scan_status": scan_status,
    }
