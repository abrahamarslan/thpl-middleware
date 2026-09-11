"""Login OTP (passwordless email OTP): request + verify (real Postgres)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.common.exception.errors import AuthError
from app.core.conf import settings
from app.modules.users import auth_emails, crud, login_otp
from app.modules.users.model import User
from app.modules.users.security import hash_one_time_code
from app.modules.users.service import hash_password


async def _make_user(db, email: str, *, username: str | None = None) -> User:
    user = User(name="OTP Tester", email=email, username=username, password=hash_password("0ldPassw0rd"))
    db.add(user)
    await db.flush()
    return user


async def _seed_otp(db, email: str, code: str, *, max_attempts: int = 5, expires_in_minutes: int = 15):
    await crud.upsert_login_otp(
        db,
        email=email,
        code_hash=hash_one_time_code(code),
        expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
        max_attempts=max_attempts,
    )


async def test_request_sends_six_digit_code_and_stores_hash(db, mocker):
    email = f"otp-{uuid.uuid4().hex[:8]}@example.com"
    await _make_user(db, email)
    send = mocker.patch.object(auth_emails, "send_login_otp_email", new=mocker.AsyncMock())

    result = await login_otp.request_login_otp(db, identifier=email)

    assert result.sent is True
    send.assert_awaited_once()
    code = send.await_args.kwargs["code"]
    assert len(code) == settings.LOGIN_OTP_CODE_LENGTH and code.isdigit()

    row = await crud.get_login_otp(db, email)
    assert row is not None and row.code_hash != code
    assert row.attempts == 0 and row.sent_count == 1


async def test_request_unknown_identifier_is_uniform(db, mocker):
    send = mocker.patch.object(auth_emails, "send_login_otp_email", new=mocker.AsyncMock())
    result = await login_otp.request_login_otp(db, identifier="nobody@example.com")
    assert result.sent is True
    send.assert_not_awaited()
    assert await crud.get_login_otp(db, "nobody@example.com") is None


async def test_request_cooldown_suppresses_second_send(db, mocker):
    email = f"otp-cd-{uuid.uuid4().hex[:8]}@example.com"
    await _make_user(db, email)
    send = mocker.patch.object(auth_emails, "send_login_otp_email", new=mocker.AsyncMock())

    await login_otp.request_login_otp(db, identifier=email)
    await login_otp.request_login_otp(db, identifier=email)

    send.assert_awaited_once()


async def test_verify_valid_code_issues_tokens_and_consumes_row(db):
    email = f"otp-ok-{uuid.uuid4().hex[:8]}@example.com"
    user = await _make_user(db, email)
    await _seed_otp(db, email, "123456")

    returned_user, tokens = await login_otp.verify_login_otp(db, identifier=email, code="123456")

    assert returned_user.id == user.id
    assert tokens.access_token and tokens.refresh_token
    assert user.last_login is not None
    assert await crud.get_login_otp(db, email) is None


async def test_verify_wrong_code_locks_out(db):
    email = f"otp-bad-{uuid.uuid4().hex[:8]}@example.com"
    await _make_user(db, email)
    await _seed_otp(db, email, "123456", max_attempts=2)

    with pytest.raises(AuthError):
        await login_otp.verify_login_otp(db, identifier=email, code="000000")
    assert (await crud.get_login_otp(db, email)).attempts == 1

    with pytest.raises(AuthError):
        await login_otp.verify_login_otp(db, identifier=email, code="000000")
    assert await crud.get_login_otp(db, email) is None


async def test_verify_expired_code_rejected(db):
    email = f"otp-exp-{uuid.uuid4().hex[:8]}@example.com"
    await _make_user(db, email)
    await _seed_otp(db, email, "123456", expires_in_minutes=-1)

    with pytest.raises(AuthError):
        await login_otp.verify_login_otp(db, identifier=email, code="123456")


async def test_verify_without_challenge_rejected(db):
    email = f"otp-none-{uuid.uuid4().hex[:8]}@example.com"
    await _make_user(db, email)
    with pytest.raises(AuthError):
        await login_otp.verify_login_otp(db, identifier=email, code="123456")
