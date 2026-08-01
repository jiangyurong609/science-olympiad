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


def _client():
    """A storage client whose credentials can *sign* URLs.

    Neither user ADC nor Cloud Run's metadata credentials carry a private key, so signing
    has to go through the IAM API. Impersonating a service account gives us credentials that
    do that, and works identically on a laptop and on Cloud Run.
    """
    settings = get_settings()
    try:
        from google.cloud import storage
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise MediaStorageError("google-cloud-storage is required for video rendering") from exc

    signer = settings.gcs_signing_service_account
    if not signer:
        return storage.Client()
    try:
        import google.auth
        from google.auth import impersonated_credentials
    except ImportError as exc:  # pragma: no cover
        raise MediaStorageError("google-auth is required for signed URLs") from exc
    source, _ = google.auth.default()
    credentials = impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=signer,
        target_scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
    )
    return storage.Client(credentials=credentials)


def _bucket():
    settings = get_settings()
    if settings.artifact_store_backend != "gcs" or not settings.artifact_store_bucket:
        raise MediaStorageError(
            "video rendering requires ARTIFACT_STORE_BACKEND=gcs with a bucket: the render "
            "worker can only read signed https URLs"
        )
    return _client().bucket(settings.artifact_store_bucket)


def upload_media(key: str, content: bytes, content_type: str, ttl: timedelta = DEFAULT_TTL) -> StoredObject:
    """Store bytes and return a signed URL the worker can GET."""
    blob = _bucket().blob(key)
    blob.upload_from_string(content, content_type=content_type)
    url = blob.generate_signed_url(version="v4", expiration=ttl, method="GET")
    return StoredObject(key=key, url=url)


def download_media(key: str) -> bytes:
    """Read stored bytes back.

    Needed because figure recovery re-reads the original PDF an import was extracted from —
    the text was kept but the bytes are where the diagrams still live.
    """
    blob = _bucket().blob(key)
    content = blob.download_as_bytes()
    if content is None:
        raise MediaStorageError(f"No stored object at {key!r}")
    return content


def signed_upload_url(key: str, content_type: str = "video/mp4", ttl: timedelta = DEFAULT_TTL) -> StoredObject:
    """Pre-sign a PUT target for the worker's finished render."""
    blob = _bucket().blob(key)
    url = blob.generate_signed_url(
        version="v4", expiration=ttl, method="PUT", content_type=content_type
    )
    return StoredObject(key=key, url=url)


def render_key(storyboard_id: int, version: int, name: str) -> str:
    return f"video/storyboard-{storyboard_id}/v{version}/{name}"


def playback_url(key: str, ttl: timedelta = DEFAULT_TTL) -> str:
    """Mint a fresh signed GET URL for playback.

    Signed URLs expire, so playback links are minted per request rather than stored; that
    also means a withdrawn video stops being reachable once its last link lapses.
    """
    return _bucket().blob(key).generate_signed_url(version="v4", expiration=ttl, method="GET")
