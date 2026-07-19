from sqlalchemy import func, select
from types import SimpleNamespace

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.entities import BackgroundJob, NotificationOutbox, User, UserNotification
from app.services.jobs import run_next_job
from app.services.notifications import create_notification


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_notification_creation_is_idempotent_transactional_and_user_isolated(client):
    with SessionLocal() as db:
        recipient = User(email="notice@example.com", full_name="Notice Student", role="student")
        other = User(email="other-notice@example.com", full_name="Other Student", role="student")
        db.add_all([recipient, other])
        db.commit()
        recipient_id, other_id = recipient.id, other.id
        recipient_token = create_access_token(str(recipient.id))
        other_token = create_access_token(str(other.id))

    with SessionLocal() as db:
        first = create_notification(
            db, user_id=recipient_id, notification_type="score_correction",
            title="A score changed", body="Review the published correction and your updated learning plan.",
            action_url="/#errors", dedupe_key="test:score-correction:1",
        )
        second = create_notification(
            db, user_id=recipient_id, notification_type="score_correction",
            title="A score changed", body="This duplicate call must not create another message.",
            action_url="/#errors", dedupe_key="test:score-correction:1",
        )
        assert first.id == second.id
        db.commit()
        notification_id = first.id
        assert db.scalar(select(func.count(UserNotification.id))) == 1
        assert db.scalar(select(func.count(NotificationOutbox.id))) == 1
        assert db.scalar(select(func.count(BackgroundJob.id)).where(
            BackgroundJob.job_type == "deliver_notification_outbox"
        )) == 1

    listed = client.get("/api/notifications", headers=auth(recipient_token))
    assert listed.status_code == 200
    assert listed.json()["unread_count"] == 1
    assert listed.json()["notifications"][0]["body"].startswith("Review")
    assert client.post(
        f"/api/notifications/{notification_id}/read", headers=auth(other_token)
    ).status_code == 404
    assert client.post(
        f"/api/notifications/{notification_id}/read", headers=auth(recipient_token)
    ).status_code == 200
    assert client.get("/api/notifications", headers=auth(recipient_token)).json()["unread_count"] == 0

    with SessionLocal() as db:
        create_notification(
            db, user_id=other_id, notification_type="assignment_published",
            title="Temporary", body="This transaction will roll back.", action_url="/#practice",
            dedupe_key="test:rollback:1",
        )
        db.rollback()
    with SessionLocal() as db:
        assert db.scalar(select(UserNotification).where(
            UserNotification.dedupe_key == "test:rollback:1"
        )) is None


def test_outbox_worker_records_disabled_external_delivery_without_losing_in_app_notice():
    with SessionLocal() as db:
        user = User(email="worker-notice@example.com", full_name="Worker Notice", role="student")
        db.add(user)
        db.flush()
        create_notification(
            db, user_id=user.id, notification_type="exam_content_hold",
            title="Exam paused", body="Your answers remain saved.", action_url="/#overview",
            dedupe_key="test:outbox-worker:1",
        )
        db.commit()
    with SessionLocal() as db:
        job = run_next_job(db)
        assert job.job_type == "deliver_notification_outbox"
        assert job.status == "completed"
        assert job.result["suppressed"] == 1
        outbox = db.scalar(select(NotificationOutbox))
        assert outbox.status == "suppressed"
        assert db.scalar(select(func.count(UserNotification.id))) == 1


def test_outbox_worker_persists_provider_failure_and_schedules_retry(monkeypatch):
    with SessionLocal() as db:
        user = User(email="retry-notice@example.com", full_name="Retry Notice", role="student")
        db.add(user)
        db.flush()
        create_notification(
            db, user_id=user.id, notification_type="assignment_published",
            title="New assignment", body="Open your reviewed practice assignment.",
            action_url="/#practice", dedupe_key="test:outbox-retry:1",
        )
        db.commit()
    monkeypatch.setattr(
        "app.services.notifications.get_settings",
        lambda: SimpleNamespace(email_delivery_provider="smtp"),
    )
    monkeypatch.setattr(
        "app.services.notifications._send_smtp",
        lambda row: (_ for _ in ()).throw(OSError("simulated provider outage")),
    )
    with SessionLocal() as db:
        job = run_next_job(db)
        assert job.status == "completed"
        assert job.result["retrying"] == 1
        outbox = db.scalar(select(NotificationOutbox))
        assert outbox.status == "retrying" and outbox.attempts == 1
        assert "simulated provider outage" in outbox.last_error
        retries = db.scalars(select(BackgroundJob).where(
            BackgroundJob.job_type == "deliver_notification_outbox",
            BackgroundJob.status == "queued",
        )).all()
        assert len(retries) == 1
