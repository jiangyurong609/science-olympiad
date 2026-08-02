"""Phase V — object storage for render inputs and outputs.

The render worker has no filesystem and no credentials: it fetches every asset from a signed
URL and PUTs the finished MP4 to another one. So slides and narration must live in object
storage with time-limited signed URLs before a render can start.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from threading import Lock

from app.core.config import get_settings

DEFAULT_TTL = timedelta(hours=12)


class MediaStorageError(RuntimeError):
    pass


@dataclass
class StoredObject:
    key: str
    url: str


# Signing is an IAM round trip; this bounds how many a single request may have in flight.
# Kept modest because the cap is per request and concurrent requests multiply it.
_SIGNING_CONCURRENCY = 8

_CLIENT_LOCK = Lock()
_CLIENT = None


def _client():
    """A storage client whose credentials can *sign* URLs.

    Neither user ADC nor Cloud Run's metadata credentials carry a private key, so signing
    has to go through the IAM API. Impersonating a service account gives us credentials that
    do that, and works identically on a laptop and on Cloud Run.

    Built once and shared. Every call used to construct a fresh client and a fresh
    impersonation exchange, which was merely wasteful when signing was serial and became a
    burst of identical token exchanges once it was not. Sharing one client also shares its
    credential refresh instead of racing several.
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = _build_client()
        return _CLIENT


def _build_client():
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


def playback_urls(keys: list[str], ttl: timedelta = DEFAULT_TTL) -> dict[str, str]:
    """Mint playback links for many objects at once.

    Signing costs a round trip. The service account the app runs as has no local private key,
    so `generate_signed_url` calls IAM `signBlob` — about a second each, measured against
    production. A page listing 22 chapters paid that 22 times in series and took 28 seconds;
    the database part of the same call took 1.2.

    There is no batch signing API, so the round trips overlap instead. Each link is still
    minted per request, which is what keeps a withdrawn video from staying reachable, and
    each one still goes through `playback_url` — one signing path, not two that can drift.

    One key that fails to sign costs that key its link, not the caller its whole list: a
    reviewer losing the entire queue because one object hiccuped is a worse failure than a
    reviewer seeing 21 of 22 chapters. Callers already treat a missing key as "no link".
    """
    unique = list(dict.fromkeys(k for k in keys if k))
    if not unique:
        return {}
    if len(unique) == 1:
        return {unique[0]: playback_url(unique[0], ttl=ttl)}

    from concurrent.futures import ThreadPoolExecutor

    def sign(key: str) -> tuple[str, str]:
        try:
            return key, playback_url(key, ttl=ttl)
        except Exception:                      # noqa: BLE001 - one bad key, not one bad page
            return key, ""

    with ThreadPoolExecutor(max_workers=min(_SIGNING_CONCURRENCY, len(unique))) as pool:
        return {key: url for key, url in pool.map(sign, unique) if url}
