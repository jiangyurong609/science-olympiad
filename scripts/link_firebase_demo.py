"""Provision seeded demo accounts in Firebase Auth and link their UIDs.

Idempotent. Intended for staging/demo deployments where AUTH_PROVIDER=firebase:
the seed creates local users with password hashes that Firebase logins never
consult, so without linked firebase_uid values the demo accounts cannot log in.

Requires Application Default Credentials with Firebase Auth admin access on
FIREBASE_PROJECT_ID (on Cloud Run, the runtime service account).
"""
from __future__ import annotations

import firebase_admin
from firebase_admin import auth
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import User

DEMO_ACCOUNTS = [
    ("student@example.com", "StudentPass123!"),
    ("coach@example.com", "CoachPass123!"),
    ("admin@example.com", "AdminPass123!"),
]


def main() -> None:
    settings = get_settings()
    if settings.auth_provider != "firebase":
        print("AUTH_PROVIDER is not firebase; nothing to link.")
        return
    app = firebase_admin.initialize_app(options={"projectId": settings.firebase_project_id})
    with SessionLocal() as db:
        for email, password in DEMO_ACCOUNTS:
            local = db.scalar(select(User).where(User.email == email))
            if local is None:
                print(f"skip {email}: no seeded local user")
                continue
            try:
                record = auth.get_user_by_email(email, app=app)
            except auth.UserNotFoundError:
                record = auth.create_user(
                    email=email, password=password, email_verified=True, app=app
                )
                print(f"created Firebase user for {email}")
            if local.firebase_uid != record.uid:
                local.firebase_uid = record.uid
                print(f"linked {email} -> {record.uid}")
        db.commit()
    print("Demo Firebase linking complete.")


if __name__ == "__main__":
    main()
