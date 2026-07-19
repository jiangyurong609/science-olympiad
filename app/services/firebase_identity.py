from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import get_settings


class FirebaseIdentityError(ValueError):
    pass


@lru_cache(maxsize=1)
def _firebase_app():
    try:
        import firebase_admin
    except ImportError as exc:  # pragma: no cover - dependency is mandatory in production
        raise FirebaseIdentityError("Firebase Admin SDK is not installed") from exc

    settings = get_settings()
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": settings.firebase_project_id})


def verify_firebase_id_token(id_token: str) -> dict[str, Any]:
    if not id_token:
        raise FirebaseIdentityError("Missing Firebase ID token")
    try:
        from firebase_admin import auth

        claims = auth.verify_id_token(
            id_token,
            app=_firebase_app(),
            check_revoked=get_settings().firebase_check_revoked,
        )
    except Exception as exc:
        raise FirebaseIdentityError("Firebase ID token is invalid, expired, or revoked") from exc
    if not claims.get("uid"):
        raise FirebaseIdentityError("Firebase token does not contain a user identifier")
    return claims
