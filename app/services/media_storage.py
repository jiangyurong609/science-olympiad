"""Phase V — object storage for render inputs and outputs.

The render worker has no filesystem and no credentials: it fetches every asset from a signed
URL and PUTs the finished MP4 to another one. So slides and narration must live in object
storage with time-limited signed URLs before a render can start.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.core.config import get_settings

DEFAULT_TTL = timedelta(hours=12)


class MediaStorageError(RuntimeError):
    pass


@dataclass
class StoredObject:
    key: str
    url: str


def _bucket():
    settings = get_settings()
    if settings.artifact_store_backend != "gcs" or not settings.artifact_store_bucket:
        raise MediaStorageError(
            "video rendering requires ARTIFACT_STORE_BACKEND=gcs with a bucket: the render "
            "worker can only read signed https URLs"
        )
    try:
        from google.cloud import storage
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise MediaStorageError("google-cloud-storage is required for video rendering") from exc
    return storage.Client().bucket(settings.artifact_store_bucket)


def upload_media(key: str, content: bytes, content_type: str, ttl: timedelta = DEFAULT_TTL) -> StoredObject:
    """Store bytes and return a signed URL the worker can GET."""
    blob = _bucket().blob(key)
    blob.upload_from_string(content, content_type=content_type)
    url = blob.generate_signed_url(version="v4", expiration=ttl, method="GET")
    return StoredObject(key=key, url=url)


def signed_upload_url(key: str, content_type: str = "video/mp4", ttl: timedelta = DEFAULT_TTL) -> StoredObject:
    """Pre-sign a PUT target for the worker's finished render."""
    blob = _bucket().blob(key)
    url = blob.generate_signed_url(
        version="v4", expiration=ttl, method="PUT", content_type=content_type
    )
    return StoredObject(key=key, url=url)


def render_key(storyboard_id: int, version: int, name: str) -> str:
    return f"video/storyboard-{storyboard_id}/v{version}/{name}"
