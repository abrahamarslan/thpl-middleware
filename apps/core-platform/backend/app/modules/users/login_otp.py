"""Login OTP (passwordless email OTP) — request + verify.

Mirrors the password-reset security model: the code is stored only as a keyed
HMAC, TTL is short, attempts are capped (row destroyed at the cap and on
success), resends are throttled per row, and responses never reveal whether an
identifier exists. Verification issues the same first-party token pair as
password login and clears the account lockout counters.

Every transition is audited (dual-write: activity_logs + structlog). Failure
paths commit their counter/audit explicitly because the request transaction is
rolled back when the domain error propagates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.client_info import ClientInfo
from app.common.exception.errors import AppError, AuthError, RateLimitedError
from app.core.conf import settings
from app.modules.users import auth_emails, crud, identifiers, moderation
from app.modules.users.audit import Event, audit
from app.modules.users.model import User
from app.modules.users.schema import TokenPair
from app.modules.users.security import generate_numeric_code, hash_one_time_code, verify_one_time_code
from app.modules.users.tokens import issue_token_pair

logger = structlog.get_logger("app.users.login_otp")


@dataclass(slots=True)
class OtpRequestResult:
    sent: bool
    expires_at: datetime | None = None
    debug_code: str | None = None


async def request_login_otp(
    db: AsyncSession, *, identifier: str, client: ClientInfo | None = None
) -> OtpRequestResult:
    user = await identifiers.resolve_user_by_identifier(db, identifier)
    if (
        user is None
        or user.is_deactivated
        or user.deleted_at is not None
        or moderation.is_banned(user)
    ):
        # Uniform response — never reveal account existence/state.
        await audit(
            db, Event.OTP_REQUEST_SUPPRESSED, actor_label=identifier, status="failure",
            description="unknown or unavailable account", client=client,
        )
        return OtpRequestResult(sent=True)
    if moderation.is_throttled(user):
        await audit(
            db, Event.OTP_REQUEST_SUPPRESSED, user=user, status="failure",
            description="account throttled", client=client, commit=True,
        )
        raise RateLimitedError("Account is temporarily throttled; try again later")

    now = datetime.now(UTC)
    existing = await crud.get_login_otp(db, user.email)

    cooldown = settings.LOGIN_OTP_RESEND_COOLDOWN_SECONDS
    if existing and existing.last_sent_at and (now - existing.last_sent_at).total_seconds() < cooldown:
        await audit(
            db, Event.OTP_REQUEST_SUPPRESSED, user=user, status="failure",
            description="resend cooldown", client=client,
        )
        return OtpRequestResult(sent=True)
    if (
        existing
        and existing.created_at
        and (now - existing.created_at) < timedelta(hours=1)
        and (existing.sent_count or 0) >= settings.LOGIN_OTP_MAX_PER_HOUR
    ):
        await audit(
            db, Event.OTP_REQUEST_SUPPRESSED, user=user, status="failure",
            description="hourly cap reached", client=client,
        )
        return OtpRequestResult(sent=True)

    code = generate_numeric_code(settings.LOGIN_OTP_CODE_LENGTH)
    expires_at = now + timedelta(minutes=settings.LOGIN_OTP_TTL_MINUTES)
    await crud.upsert_login_otp(
        db,
        email=user.email,
        code_hash=hash_one_time_code(code),
        expires_at=expires_at,
        max_attempts=settings.LOGIN_OTP_MAX_ATTEMPTS,
        request_ip=client.ip if client else None,
    )
    await auth_emails.send_login_otp_email(
        db, user, code=code, expires_minutes=settings.LOGIN_OTP_TTL_MINUTES, client=client
    )
    await audit(
        db, Event.OTP_REQUEST, user=user, client=client,
        context={"expires_at": expires_at.isoformat()},
    )

    result = OtpRequestResult(sent=True, expires_at=expires_at)
    if settings.DEBUG:
        result.debug_code = code
    return result


async def verify_login_otp(
    db: AsyncSession,
    *,
    identifier: str,
    code: str,
    device_id: str | None = None,
    device_type: str | None = None,
    client: ClientInfo | None = None,
) -> tuple[User, TokenPair]:
    user = await identifiers.resolve_user_by_identifier(db, identifier)
    if user is None:
        await audit(
            db, Event.OTP_FAILURE, actor_label=identifier, status="failure",
            description="unknown identifier", client=client, commit=True,
        )
        raise AuthError("Invalid or expired code")

    now = datetime.now(UTC)
    try:
        moderation.ensure_can_authenticate(user)
    except AppError as exc:
        await audit(
            db, Event.OTP_FAILURE, user=user, status="failure", description=exc.msg,
            client=client, context={"reason": exc.code}, commit=True,
        )
        raise

    # OTP is a possession factor, so a *password* lockout deliberately does not
    # block it — the user may be recovering. OTP brute-force is instead bounded
    # by the per-challenge attempt cap + resend throttle on the row, so it
    # never increments the account-wide password failure counter (which would
    # let an attacker lock a legitimate user out of OTP too).
    row = await crud.get_login_otp(db, user.email)
    if row is None:
        await audit(
            db, Event.OTP_FAILURE, user=user, status="failure",
            description="no challenge", client=client, commit=True,
        )
        raise AuthError("Invalid or expired code")
    if row.expires_at is not None and now > row.expires_at:
        await crud.delete_login_otp(db, user.email)
        await audit(
            db, Event.OTP_FAILURE, user=user, status="failure",
            description="expired", client=client, commit=True,
        )
        raise AuthError("Code expired")

    max_attempts = row.max_attempts or settings.LOGIN_OTP_MAX_ATTEMPTS
    if (row.attempts or 0) >= max_attempts:
        await crud.delete_login_otp(db, user.email)
        await audit(
            db, Event.OTP_FAILURE, user=user, status="failure",
            description="attempt cap reached", client=client, commit=True,
        )
        raise AuthError("Too many invalid attempts; request a new code")

    if not verify_one_time_code(code, row.code_hash):
        row.attempts = (row.attempts or 0) + 1
        exhausted = row.attempts >= max_attempts
        if exhausted:
            await crud.delete_login_otp(db, user.email)
        else:
            await db.flush()
        await audit(
            db, Event.OTP_FAILURE, user=user, status="failure",
            description="invalid code", client=client,
            context={"attempts": row.attempts, "exhausted": exhausted}, commit=True,
        )
        raise AuthError("Invalid or expired code")

    # Success — single use, clear any password lockout, record the session.
    await crud.delete_login_otp(db, user.email)
    user.failed_login_attempts = 0
    user.locked_at = None
    user.last_login = now
    user.has_active_session = True
    if device_id:
        user.device_id = device_id
    if device_type:
        user.device_type = device_type
    await db.flush()

    await audit(db, Event.OTP_LOGIN, user=user, client=client, context={"device_id": device_id})
    await audit(
        db, Event.TOKEN_ISSUED, user=user, client=client,
        context={"method": "otp", "access": True, "refresh": True},
    )
    return user, issue_token_pair(user)
