"""Only an administrator may change roles, and granting admin must not happen quietly.

The role dropdown lists every role including `admin`, so the question "can everyone switch
themselves to admin?" is worth answering with a test rather than a reading of the code. It
also pins the notification: an audit row records the grant, but nobody reads an audit table
unprompted, so the other administrators are told.
"""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import User, UserNotification


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_a_student_cannot_grant_themselves_or_anyone_else_admin(client, student_token):
    with SessionLocal() as db:
        me = db.scalar(select(User).where(User.role == "student"))
        target = User(email="escalation-target@example.com", full_name="Target",
                      role="editor", is_active=True)
        db.add(target)
        db.commit()
        my_id, target_id = me.id, target.id
        target_role = target.role

    assert client.patch(f"/api/admin/users/{my_id}", json={"role": "admin"},
                        headers=_auth(student_token)).status_code == 403
    assert client.patch(f"/api/admin/users/{target_id}", json={"role": "admin"},
                        headers=_auth(student_token)).status_code == 403
    assert client.get("/api/admin/users", headers=_auth(student_token)).status_code == 403

    with SessionLocal() as db:
        assert db.get(User, my_id).role == "student", "a student escalated itself"
        assert db.get(User, target_id).role == target_role


def test_an_unauthenticated_caller_cannot_change_roles(client):
    with SessionLocal() as db:
        target = User(email="anon-target@example.com", full_name="Anon Target",
                      role="student", is_active=True)
        db.add(target)
        db.commit()
        target_id = target.id
    assert client.patch(f"/api/admin/users/{target_id}", json={"role": "admin"}).status_code == 401
    with SessionLocal() as db:
        assert db.get(User, target_id).role == "student"


def test_granting_admin_notifies_the_other_administrators(client, admin_token):
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.role == "admin"))
        other_admin = User(email="second-admin@example.com", full_name="Second Admin",
                           role="admin", is_active=True)
        target = User(email="promote-me@example.com", full_name="Promote Me",
                      role="student", is_active=True)
        db.add_all([other_admin, target])
        db.commit()
        other_id, target_id, actor_id = other_admin.id, target.id, actor.id

    response = client.patch(f"/api/admin/users/{target_id}", json={"role": "admin"},
                            headers=_auth(admin_token))
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        assert db.get(User, target_id).role == "admin"
        notes = db.scalars(select(UserNotification).where(
            UserNotification.user_id == other_id,
            UserNotification.notification_type == "admin_role_change",
        )).all()
        assert notes, "the other administrator was not told about a new administrator"
        assert "Promote Me" in notes[0].body
        # the promoted user is not told about their own promotion by this path
        assert not db.scalars(select(UserNotification).where(
            UserNotification.user_id == target_id,
            UserNotification.notification_type == "admin_role_change",
        )).all()
        assert actor_id != target_id


def test_a_routine_role_change_does_not_raise_an_admin_alert(client, admin_token):
    """Only grants and removals of `admin` are worth interrupting people for."""
    with SessionLocal() as db:
        other_admin = User(email="quiet-admin@example.com", full_name="Quiet Admin",
                           role="admin", is_active=True)
        target = User(email="make-me-sme@example.com", full_name="Make Me Sme",
                      role="student", is_active=True)
        db.add_all([other_admin, target])
        db.commit()
        other_id, target_id = other_admin.id, target.id

    assert client.patch(f"/api/admin/users/{target_id}", json={"role": "sme"},
                        headers=_auth(admin_token)).status_code == 200

    with SessionLocal() as db:
        assert db.get(User, target_id).role == "sme"
        assert not db.scalars(select(UserNotification).where(
            UserNotification.user_id == other_id,
            UserNotification.notification_type == "admin_role_change",
        )).all(), "promoting to sme should not alarm every administrator"
