"""Password reset: hashed one-time codes, identifier resolution, attempt cap.

The auth-email send is patched at the ``auth_emails`` boundary — this suite
tests reset logic + delivery triggers, not rendering. Requires the scratch DB.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.common.exception.errors import AuthError
from app.core.conf import settings
from app.modules.users import auth_emails, crud, password_reset
from app.modules.users.model import User
from app.modules.users.security import hash_one_time_code
from app.modules.users.service import hash_password, verify_password


async def _make_user(db, email: str, *, username: str | None = None, phone: str | None = None) -> User:
    user = User(
        name="Reset Tester",
        email=email,
        username=username,
        phone=phone,
        password=hash_password("0ldPassw0rd"),
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_code(db, email: str, code: str, *, max_attempts: int = 3, expires_in_minutes: int = 10):
    await crud.upsert_reset_token(
        db,
        email=email,
        token="link-token",
        reset_type="code",
        code_hash=hash_one_time_code(code),
        expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
        max_attempts=max_attempts,
    )


async def test_request_creates_hashed_code_and_sends_email(db, mocker):
    email = f"reset-{uuid.uuid4().hex[:8]}@example.com"
    await _make_user(db, email)
    send = mocker.patch.object(
        auth_emails, "send_password_reset_code_email", new=mocker.AsyncMock()
    )

    result = await password_reset.request_password_reset(db, identifier=email, reset_type="code")

    assert result.sent is True
    send.assert_awaited_once()
    code = send.await_args.kwargs["code"]
    assert len(code) == settings.PASSWORD_RESET_CODE_LENGTH and code.isdigit()

    row = await crud.get_reset_token(db, email)
    assert row is not None
    assert row.code_hash and row.code_hash != code  # never plaintext
    assert row.attempts == 0 and row.sent_count == 1
    assert row.expires_at is not None


async def test_identifier_resolves_username_and_phone(db, mocker):
    suffix = uuid.uuid4().hex[:8]
    email = f"ident-{suffix}@example.com"
    username = f"ident_{suffix}"
    phone = "+9198" + str(uuid.uuid4().int)[:8]
    await _make_user(db, email, username=username, phone=phone)
    mocker.patch.object(auth_emails, "send_password_reset_code_email", new=mocker.AsyncMock())

    await password_reset.request_password_reset(db, identifier=username, reset_type="code")
    assert await crud.get_reset_token(db, email) is not None

    await crud.delete_reset_token(db, email)
    await password_reset.request_password_reset(db, identifier=phone, reset_type="code")
    assert await crud.get_reset_token(db, email) is not None


async def test_request_unknown_identifier_is_uniform_and_sends_nothing(db, mocker):
    send = mocker.patch.object(
        auth_emails, "send_password_reset_code_email", new=mocker.AsyncMock()
    )
    result = await password_reset.request_password_reset(
        db, identifier="nobody@example.com", reset_type="code"
    )
    assert result.sent is True
    send.assert_not_awaited()
    assert await crud.get_reset_token(db, "nobody@example.com") is None


async def test_request_is_rate_limited_by_cooldown(db, mocker):
    email = f"cool-{uuid.uuid4().hex[:8]}@example.com"
    await _make_user(db, email)
    send = mocker.patch.object(
        auth_emails, "send_password_reset_code_email", new=mocker.AsyncMock()
    )

    await password_reset.request_password_reset(db, identifier=email, reset_type="code")
    await password_reset.request_password_reset(db, identifier=email, reset_type="code")

    send.assert_awaited_once()  # second request suppressed by cooldown
    assert (await crud.get_reset_token(db, email)).sent_count == 1


async def test_reset_with_valid_code_updates_password_and_emails_confirmation(db, mocker):
    email = f"valid-{uuid.uuid4().hex[:8]}@example.com"
    user = await _make_user(db, email)
    await _seed_code(db, email, "1234")
    mocker.patch.object(password_reset, "sync_set_password", new=mocker.AsyncMock())
    confirm = mocker.patch.object(
        auth_emails, "send_password_changed_email", new=mocker.AsyncMock()
    )

    await password_reset.reset_password(
        db, identifier=email, token_or_code="1234", new_password="N3wStr0ng!"
    )

    assert verify_password("N3wStr0ng!", user.password)
    assert await crud.get_reset_token(db, email) is None  # single use
    confirm.assert_awaited_once()


async def test_wrong_code_increments_attempts_then_locks_out(db, mocker):
    email = f"bad-{uuid.uuid4().hex[:8]}@example.com"
    await _make_user(db, email)
    await _seed_code(db, email, "1234", max_attempts=2)

    with pytest.raises(AuthError):
        await password_reset.reset_password(
            db, identifier=email, token_or_code="0000", new_password="N3wStr0ng!"
        )
    assert (await crud.get_reset_token(db, email)).attempts == 1

    with pytest.raises(AuthError):
        await password_reset.reset_password(
            db, identifier=email, token_or_code="0000", new_password="N3wStr0ng!"
        )
    assert await crud.get_reset_token(db, email) is None  # destroyed at the cap


async def test_expired_code_is_rejected(db, mocker):
    email = f"exp-{uuid.uuid4().hex[:8]}@example.com"
    await _make_user(db, email)
    await _seed_code(db, email, "1234", expires_in_minutes=-1)

    with pytest.raises(AuthError):
        await password_reset.reset_password(
            db, identifier=email, token_or_code="1234", new_password="N3wStr0ng!"
        )


async def test_missing_row_is_rejected(db):
    email = f"ghost-{uuid.uuid4().hex[:8]}@example.com"
    await _make_user(db, email)
    with pytest.raises(AuthError):
        await password_reset.reset_password(
            db, identifier=email, token_or_code="1234", new_password="N3wStr0ng!"
        )
