from __future__ import annotations

import hashlib
import os
import uuid
import io
import zipfile
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
    if "wordprocessingml.document" in media_type:
        return ".docx"
    if "presentationml.presentation" in media_type:
        return ".pptx"
    if media_type == "image/png":
        return ".png"
    if media_type in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if media_type == "image/webp":
        return ".webp"
    return ".bin"


def validate_raw_artifact(content: bytes, media_type: str) -> str:
    if not content:
        raise ArtifactError("Fetched artifact is empty")
    lowered = media_type.lower()
    if "pdf" in lowered and not content.startswith(b"%PDF-"):
        raise ArtifactError("PDF content does not match its declared media type")
    if ("html" in lowered or lowered.startswith("text/")) and b"\x00" in content[:8192]:
        raise ArtifactError("Text artifact contains unexpected binary data")
    if "wordprocessingml" in lowered or "presentationml" in lowered or content[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
                if any(name.lower().endswith("vbaproject.bin") for name in names):
                    raise ArtifactError("Office macros are not accepted; upload a macro-free file")
                if any(info.flag_bits & 0x1 for info in archive.infolist()):
                    raise ArtifactError("Encrypted archives are not accepted")
                if sum(info.file_size for info in archive.infolist()) > 100_000_000:
                    raise ArtifactError("Compressed upload expands beyond the safety limit")
        except zipfile.BadZipFile:
            if "wordprocessingml" in lowered or "presentationml" in lowered:
                raise ArtifactError("Office file is not a valid ZIP package")
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


def read_raw_artifact(storage_key: str) -> bytes:
    """Read an immutable artifact for a background ingestion worker."""
    settings = get_settings()
    if settings.artifact_store_backend == "gcs":
        if not settings.artifact_store_bucket:
            raise ArtifactError("GCS artifact bucket is not configured")
        try:
            from google.cloud import storage
            blob = storage.Client().bucket(settings.artifact_store_bucket).blob(storage_key)
            return blob.download_as_bytes()
        except Exception as error:  # noqa: BLE001
            raise ArtifactError(f"GCS artifact read failed: {error}") from error
    path = Path(settings.artifact_store_path).expanduser().resolve() / storage_key
    try:
        return path.read_bytes()
    except OSError as error:
        raise ArtifactError(f"Artifact could not be read: {error}") from error
