"""User moderation: ban/unban, throttle/unthrottle (real Postgres)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.common.exception.errors import ForbiddenError, RateLimitedError
from app.modules.users import crud, login_otp, moderation, password_reset, service
from app.modules.users.model import User
from app.modules.users.schema import LoginRequest
from app.modules.users.security import hash_password

PASSWORD = "0ldPassw0rd"


def test_ban_request_coerces_naive_until_to_utc():
    from datetime import datetime

    from app.modules.users.schema import BanRequest

    req = BanRequest(reason="x", until=datetime(2030, 1, 1, 12, 0))
    assert req.until is not None and req.until.tzinfo is not None


async def _user(db, **overrides) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        name="Mod Tester",
        email=overrides.pop("email", f"mod-{suffix}@example.com"),
        password=hash_password(PASSWORD),
        **overrides,
    )
    db.add(user)
    await db.flush()
    return user


async def test_ban_blocks_login_and_destroys_challenges(db):
    user = await _user(db)
    # Seed an in-flight reset challenge to prove banning cleans it up.
    await crud.upsert_reset_token(
        db,
        email=user.email,
        token="tok",
        reset_type="code",
        code_hash="hash",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        max_attempts=3,
    )

    await moderation.ban_user(db, user, reason="abuse", actor_id=None)

    assert moderation.is_banned(user)
    assert moderation.moderation_state(user)["state"] == "banned"
    with pytest.raises(ForbiddenError):
        await service.login(db, LoginRequest(email_or_username=user.email, password=PASSWORD))
    assert await crud.get_reset_token(db, user.email) is None


async def test_unban_restores_login(db):
    user = await _user(db)
    await moderation.ban_user(db, user, reason="abuse")
    await moderation.unban_user(db, user)

    assert not moderation.is_banned(user)
    _, tokens = await service.login(
        db, LoginRequest(email_or_username=user.email, password=PASSWORD)
    )
    assert tokens.access_token


async def test_temporary_ban_expires_on_its_own(db):
    user = await _user(db)
    await moderation.ban_user(
        db, user, reason="cool-off", until=datetime.now(UTC) - timedelta(minutes=1)
    )
    assert not moderation.is_banned(user)  # expired
    await service.login(db, LoginRequest(email_or_username=user.email, password=PASSWORD))


async def test_throttle_blocks_new_auth_but_keeps_existing_session(db):
    user = await _user(db)
    await moderation.throttle_user(db, user, reason="rate", actor_id=None)

    assert moderation.moderation_state(user)["state"] == "throttled"
    # New authentication is refused with 429...
    with pytest.raises(RateLimitedError):
        await service.login(db, LoginRequest(email_or_username=user.email, password=PASSWORD))
    # ...and OTP / reset requests too.
    with pytest.raises(RateLimitedError):
        await login_otp.request_login_otp(db, identifier=user.email)
    with pytest.raises(RateLimitedError):
        await password_reset.request_password_reset(db, identifier=user.email)
    # ...but an already-authenticated session still passes the API guard.
    moderation.ensure_can_use_api(user)


async def test_unthrottle_restores_auth(db):
    user = await _user(db)
    await moderation.throttle_user(db, user, reason="rate")
    await moderation.unthrottle_user(db, user)
    _, tokens = await service.login(
        db, LoginRequest(email_or_username=user.email, password=PASSWORD)
    )
    assert tokens.access_token


async def test_ban_records_activity(db):
    from sqlalchemy import select

    from app.modules.activity.model import ActivityLog

    user = await _user(db)
    await moderation.ban_user(db, user, reason="abuse", actor_id=user.id)
    rows = (
        await db.scalars(select(ActivityLog).where(ActivityLog.action == "user.moderation.ban"))
    ).all()
    assert rows and rows[-1].subject_id == str(user.id)
