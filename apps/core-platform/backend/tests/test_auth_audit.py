"""Auth audit trail: every lifecycle event is recorded in activity_logs."""

import uuid

from sqlalchemy import select

from app.modules.activity.model import ActivityLog
from app.modules.users import moderation, service
from app.modules.users.model import User
from app.modules.users.schema import LoginRequest, RegisterRequest, UserUpdate
from app.modules.users.security import hash_password

PASSWORD = "Str0ngPass1"


async def _actions_for(db, user_id: int) -> list[str]:
    rows = (
        await db.scalars(
            select(ActivityLog).where(ActivityLog.subject_id == str(user_id)).order_by(ActivityLog.id)
        )
    ).all()
    return [r.action for r in rows]


async def _make_user(db, **overrides) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        name=overrides.pop("name", "Audit"),
        email=overrides.pop("email", f"audit-{suffix}@example.com"),
        password=hash_password(PASSWORD),
        **overrides,
    )
    db.add(user)
    await db.flush()
    return user


async def test_register_login_logout_are_audited(db, mocker):
    mocker.patch("app.modules.users.auth_emails.send_welcome_email", new=mocker.AsyncMock())
    email = f"audit-{uuid.uuid4().hex[:8]}@example.com"

    user = await service.register(
        db, RegisterRequest(name="Aud", email=email, password=PASSWORD)
    )
    assert "auth.register" in await _actions_for(db, user.id)

    user, _ = await service.login(db, LoginRequest(identifier=email, password=PASSWORD))
    actions = await _actions_for(db, user.id)
    assert "auth.login.success" in actions
    assert "auth.token.issued" in actions

    await service.logout(db, user)
    assert "auth.logout" in await _actions_for(db, user.id)


async def test_profile_update_records_field_level_diff(db):
    user = await _make_user(db)
    actor = await _make_user(db, name="Admin")

    await service.update_user(
        db, user.id, UserUpdate(city="Ahmedabad", phone="+919999999999"),
        updated_by=actor.id, actor_label=actor.email,
    )

    row = (
        await db.scalars(
            select(ActivityLog).where(ActivityLog.action == "user.profile.updated").order_by(ActivityLog.id.desc())
        )
    ).first()
    assert row is not None
    assert row.actor_id == actor.id
    assert set(row.changes.keys()) == {"city", "phone"}
    assert row.changes["city"] == {"old": None, "new": "Ahmedabad"}
    assert row.changes["phone"] == {"old": None, "new": "+919999999999"}


async def test_moderation_events_are_audited(db):
    user = await _make_user(db)
    actor = await _make_user(db, name="Admin")

    await moderation.ban_user(db, user, reason="abuse", actor_id=actor.id)
    await moderation.unban_user(db, user, actor_id=actor.id)
    await moderation.throttle_user(db, user, reason="rate", actor_id=actor.id)
    await moderation.unthrottle_user(db, user, actor_id=actor.id)

    actions = await _actions_for(db, user.id)
    for expected in (
        "user.moderation.ban",
        "user.moderation.unban",
        "user.moderation.throttle",
        "user.moderation.unthrottle",
    ):
        assert expected in actions


async def test_password_change_is_audited(db):
    user = await _make_user(db)
    await service.change_password(
        db, user, current_password=PASSWORD, new_password="N3wSecurePass!"
    )
    assert "auth.password.changed" in await _actions_for(db, user.id)
