from __future__ import annotations

import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import BackgroundJob, NotificationOutbox, User, UserNotification


def create_notification(
    db: Session,
    *,
    user_id: int,
    notification_type: str,
    title: str,
    body: str,
    action_url: str,
    dedupe_key: str,
    metadata: dict | None = None,
) -> UserNotification:
    existing = db.scalar(select(UserNotification).where(UserNotification.dedupe_key == dedupe_key))
    if existing:
        return existing
    user = db.get(User, user_id)
    if not user:
        raise ValueError("Notification user not found")
    notification = UserNotification(
        user_id=user.id, notification_type=notification_type, title=title, body=body,
        action_url=action_url, dedupe_key=dedupe_key, metadata_json=metadata or {},
    )
    db.add(notification)
    db.flush()
    db.add(NotificationOutbox(
        notification_id=notification.id, channel="email", recipient=user.email,
        payload={"subject": title, "body": body, "action_url": action_url},
    ))
    pending = db.scalar(select(BackgroundJob).where(
        BackgroundJob.job_type == "deliver_notification_outbox",
        BackgroundJob.status.in_(["queued", "running"]),
    ))
    if not pending:
        db.add(BackgroundJob(
            job_type="deliver_notification_outbox", payload={"source": "transactional_outbox"},
        ))
    return notification


def _send_smtp(row: NotificationOutbox) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["Subject"] = row.payload["subject"]
    message["From"] = settings.smtp_from_email
    message["To"] = row.recipient
    action = row.payload.get("action_url", "")
    action_url = f"{settings.public_app_url.rstrip('/')}{action}" if action.startswith("/") else action
    message.set_content(f"{row.payload['body']}\n\nOpen Fieldstone: {action_url}" if action_url else row.payload["body"])
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        client.ehlo()
        client.starttls()
        client.ehlo()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password or "")
        client.send_message(message)


def deliver_notification_outbox(db: Session, limit: int = 50) -> dict:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(NotificationOutbox).where(
        NotificationOutbox.status.in_(["queued", "retrying"]),
        NotificationOutbox.next_attempt_at <= now,
    ).order_by(NotificationOutbox.created_at, NotificationOutbox.id).limit(limit)).all()
    result = {"processed": 0, "sent": 0, "suppressed": 0, "retrying": 0, "failed": 0}
    for row in rows:
        result["processed"] += 1
        if settings.email_delivery_provider == "disabled":
            row.status = "suppressed"
            row.last_error = "External email delivery is disabled; in-app notification remains available"
            result["suppressed"] += 1
            continue
        try:
            _send_smtp(row)
            row.status = "sent"
            row.sent_at = now
            row.last_error = ""
            result["sent"] += 1
        except Exception as exc:  # provider/network failures are persisted for retry
            row.attempts += 1
            row.last_error = str(exc)[:2000]
            if row.attempts >= 5:
                row.status = "failed"
                result["failed"] += 1
            else:
                row.status = "retrying"
                row.next_attempt_at = now + timedelta(minutes=min(60, 2 ** row.attempts))
                result["retrying"] += 1
    db.flush()
    next_due = db.scalar(select(NotificationOutbox.next_attempt_at).where(
        NotificationOutbox.status.in_(["queued", "retrying"])
    ).order_by(NotificationOutbox.next_attempt_at))
    if next_due:
        db.add(BackgroundJob(
            job_type="deliver_notification_outbox", payload={"source": "outbox_retry"},
            scheduled_at=next_due,
        ))
    return result
