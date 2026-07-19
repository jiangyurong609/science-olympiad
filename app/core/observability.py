"""Structured logging, request IDs, and a global exception handler.

Cloud Run ingests stdout as structured logs, so we emit one JSON line per record
with a `severity` field it understands. Every request gets a short id (echoed in
the `X-Request-ID` response header and attached to each log line) so a report of
"something broke" can be traced to the exact request and stack trace — previously
the backend had no logging at all and swallowed errors silently.
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

logger = logging.getLogger("soplat")

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        # Any non-standard attribute set via `extra=` is promoted to a top-level field.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key != "request_id":
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # we emit our own request log


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        request_id_var.set(rid)
        start = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        path = request.url.path
        if path not in ("/health", "/api/health") and not path.startswith("/static"):
            logger.info("request", extra={"request_id": rid, "method": request.method,
                                          "path": path, "status": response.status_code,
                                          "duration_ms": round((time.monotonic() - start) * 1000, 1)})
        return response


async def unhandled_exception_handler(request, exc: Exception) -> JSONResponse:
    rid = getattr(request.state, "request_id", "-")
    logger.error("unhandled_exception", exc_info=exc,
                 extra={"request_id": rid, "method": request.method, "path": request.url.path})
    return JSONResponse(status_code=500,
                        content={"detail": "Something went wrong. Please try again.", "request_id": rid})


def install_observability(app) -> None:
    configure_logging()
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(Exception, unhandled_exception_handler)
