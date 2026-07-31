"""Phase V — adapter for the existing Remotion render worker.

We do not host Remotion. The worker already running in the `video-agent-493605` project
exposes `POST /render/edit-spec` and is deployed `--no-allow-unauthenticated`, so every call
carries a Google OIDC identity token whose audience is the worker URL. The call is
synchronous: it blocks for the length of the render, so it belongs in a background job and
never in a request handler.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.services.video_editspec import validate_edit_spec


class RenderWorkerError(RuntimeError):
    pass


@dataclass
class RenderResult:
    ok: bool
    bytes_written: int = 0
    video: bytes | None = None   # only when no uploadUrl was supplied
    detail: str = ""


def fetch_identity_token(audience: str) -> str:
    """Mint a Google OIDC token for the worker. Import is local so the dependency is only
    required where rendering is actually used."""
    try:
        import google.auth.transport.requests
        from google.oauth2 import id_token
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RenderWorkerError("google-auth is required to call the render worker") from exc
    try:
        request = google.auth.transport.requests.Request()
        return id_token.fetch_id_token(request, audience)
    except Exception as exc:
        raise RenderWorkerError(f"could not mint an identity token: {exc}") from exc


class RemotionRenderClient:
    def __init__(self, worker_url: str | None = None, token: str | None = None) -> None:
        settings = get_settings()
        self.worker_url = (worker_url or settings.video_render_worker_url or "").rstrip("/")
        self.timeout = settings.video_render_timeout_seconds
        self._token = token

    @property
    def configured(self) -> bool:
        return bool(self.worker_url)

    def _auth_headers(self) -> dict:
        token = self._token or fetch_identity_token(self.worker_url)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def render(self, spec: dict, upload_url: str | None = None) -> RenderResult:
        """POST an EditSpec. With `upload_url` the worker PUTs the MP4 there and returns
        {"ok":true,"bytes":N}; without one the response body *is* the MP4."""
        if not self.configured:
            raise RenderWorkerError("video_render_worker_url is not configured")
        validate_edit_spec(spec)  # never spend a render on a spec the worker would reject

        body: dict = {"spec": spec}
        if upload_url:
            body["uploadUrl"] = upload_url
        try:
            response = httpx.post(
                f"{self.worker_url}/render/edit-spec",
                headers=self._auth_headers(),
                json=body,
                timeout=httpx.Timeout(self.timeout, connect=20.0),
            )
        except httpx.TimeoutException as exc:
            raise RenderWorkerError(f"render timed out after {self.timeout}s") from exc
        except httpx.HTTPError as exc:
            raise RenderWorkerError(f"render request failed: {exc}") from exc

        if response.status_code >= 400:
            raise RenderWorkerError(
                f"worker returned {response.status_code}: {response.text[:300]}"
            )

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = response.json()
            if not payload.get("ok"):
                raise RenderWorkerError(f"worker reported failure: {payload}")
            return RenderResult(ok=True, bytes_written=int(payload.get("bytes", 0)))
        return RenderResult(ok=True, bytes_written=len(response.content), video=response.content)
