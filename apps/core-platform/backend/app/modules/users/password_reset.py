"""Password reset feature: 4-digit code (default) + link fallback.

Accepts a single ``identifier`` (email | username | phone) and resolves it to
the account, never revealing whether it exists. The code is stored only as a
keyed HMAC; TTL is short, attempts are capped (row destroyed at the cap and on
success), resends are throttled per row. A successful reset also emails a
security confirmation.

The link flow reuses the same row and its high-entropy token, so it works for
clients that can open a URL; the app-first clients use the 4-digit code.

Every request/verify (and every suppression/failure) is audited; failure paths
commit explicitly because the request transaction is rolled back when the domain
error propagates.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.client_info import ClientInfo
from app.common.exception.errors import AppError, AuthError, RateLimitedError
from app.core.conf import settings
from app.modules.users import auth_emails, crud, identifiers, moderation
from app.modules.users.audit import Event, audit
from app.modules.users.authentik_sync import sync_set_password
from app.modules.users.password_policy import validate_password
from app.modules.users.security import (
    generate_numeric_code,
    hash_one_time_code,
    hash_password,
    verify_one_time_code,
)

logger = structlog.get_logger("app.users.password_reset")

RESET_TYPE_CODE = "code"
RESET_TYPE_LINK = "link"


@dataclass(slots=True)
class ResetRequestResult:
    sent: bool
    expires_at: datetime | None = None
    # DEBUG-only echoes so local/dev clients don't need a mailbox.
    debug_code: str | None = None
    debug_token: str | None = None


async def _suppress(db, *, user=None, identifier: str | None = None, reason: str, client=None) -> None:
    await audit(
        db, Event.PASSWORD_RESET_REQUEST, user=user, actor_label=identifier,
        status="failure", description=reason, client=client,
    )


async def request_password_reset(
    db: AsyncSession,
    *,
    identifier: str,
    reset_type: str = RESET_TYPE_CODE,
    client: ClientInfo | None = None,
) -> ResetRequestResult:
    user = await identifiers.resolve_user_by_identifier(db, identifier)
    if (
        user is None
        or user.is_deactivated
        or user.deleted_at is not None
        or moderation.is_banned(user)
    ):
        # Uniform response — never reveal account existence/state.
        await _suppress(db, identifier=identifier, reason="unknown or unavailable account", client=client)
        return ResetRequestResult(sent=True)
    if moderation.is_throttled(user):
        await audit(
            db, Event.PASSWORD_RESET_REQUEST, user=user, status="failure",
            description="account throttled", client=client, commit=True,
        )
        raise RateLimitedError("Account is temporarily throttled; try again later")

    now = datetime.now(UTC)
    existing = await crud.get_reset_token(db, user.email)

    cooldown = settings.PASSWORD_RESET_RESEND_COOLDOWN_SECONDS
    if existing and existing.last_sent_at and (now - existing.last_sent_at).total_seconds() < cooldown:
        await _suppress(db, user=user, reason="resend cooldown", client=client)
        return ResetRequestResult(sent=True)
    if (
        existing
        and existing.created_at
        and (now - existing.created_at) < timedelta(hours=1)
        and (existing.sent_count or 0) >= settings.PASSWORD_RESET_MAX_PER_HOUR
    ):
        await _suppress(db, user=user, reason="hourly cap reached", client=client)
        return ResetRequestResult(sent=True)

    is_code = reset_type == RESET_TYPE_CODE
    code = generate_numeric_code(settings.PASSWORD_RESET_CODE_LENGTH) if is_code else None
    token = secrets.token_urlsafe(48)
    ttl_minutes = (
        settings.PASSWORD_RESET_CODE_TTL_MINUTES if is_code else settings.PASSWORD_RESET_LINK_TTL_MINUTES
    )
    expires_at = now + timedelta(minutes=ttl_minutes)

    await crud.upsert_reset_token(
        db,
        email=user.email,
        token=token,
        reset_type=reset_type,
        code_hash=hash_one_time_code(code) if code else None,
        expires_at=expires_at,
        max_attempts=settings.PASSWORD_RESET_MAX_ATTEMPTS,
        request_ip=client.ip if client else None,
    )

    if is_code:
        await auth_emails.send_password_reset_code_email(
            db,
            user,
            code=code,
            expires_minutes=ttl_minutes,
            expires_at=expires_at,
            attempts_allowed=settings.PASSWORD_RESET_MAX_ATTEMPTS,
            client=client,
        )
    else:
        reset_url = (
            f"{settings.FRONTEND_URL.rstrip('/')}/reset-password"
            f"?identifier={user.email}&token={token}"
        )
        await auth_emails.send_password_reset_link_email(
            db, user, reset_url=reset_url, expires_minutes=ttl_minutes, client=client
        )

    await audit(
        db, Event.PASSWORD_RESET_REQUEST, user=user, client=client,
        context={"reset_type": reset_type, "expires_at": expires_at.isoformat()},
    )

    result = ResetRequestResult(sent=True, expires_at=expires_at)
    if settings.DEBUG:
        result.debug_code = code
        result.debug_token = token
    return result


async def reset_password(
    db: AsyncSession,
    *,
    identifier: str,
    token_or_code: str,
    new_password: str,
    client: ClientInfo | None = None,
) -> None:
    user = await identifiers.resolve_user_by_identifier(db, identifier)
    if user is None:
        await audit(
            db, Event.PASSWORD_RESET_FAILURE, actor_label=identifier, status="failure",
            description="unknown identifier", client=client, commit=True,
        )
        raise AuthError("Invalid or expired reset code")
    try:
        moderation.ensure_can_authenticate(user)
    except AppError as exc:
        await audit(
            db, Event.PASSWORD_RESET_FAILURE, user=user, status="failure", description=exc.msg,
            client=client, context={"reason": exc.code}, commit=True,
        )
        raise

    row = await crud.get_reset_token(db, user.email)
    if row is None:
        await audit(
            db, Event.PASSWORD_RESET_FAILURE, user=user, status="failure",
            description="no challenge", client=client, commit=True,
        )
        raise AuthError("Invalid or expired reset code")

    now = datetime.now(UTC)
    if row.expires_at is not None and now > row.expires_at:
        await crud.delete_reset_token(db, user.email)
        await audit(
            db, Event.PASSWORD_RESET_FAILURE, user=user, status="failure",
            description="expired", client=client, commit=True,
        )
        raise AuthError("Reset code expired")

    max_attempts = row.max_attempts or settings.PASSWORD_RESET_MAX_ATTEMPTS
    if (row.attempts or 0) >= max_attempts:
        await crud.delete_reset_token(db, user.email)
        await audit(
            db, Event.PASSWORD_RESET_FAILURE, user=user, status="failure",
            description="attempt cap reached", client=client, commit=True,
        )
        raise AuthError("Too many invalid attempts; request a new code")

    matches = False
    if row.reset_type == RESET_TYPE_CODE:
        matches = verify_one_time_code(token_or_code, row.code_hash)
    if not matches and row.token:
        matches = secrets.compare_digest(token_or_code, row.token)
    if not matches:
        row.attempts = (row.attempts or 0) + 1
        exhausted = row.attempts >= max_attempts
        if exhausted:
            await crud.delete_reset_token(db, user.email)
        else:
            await db.flush()
        await audit(
            db, Event.PASSWORD_RESET_FAILURE, user=user, status="failure",
            description="invalid code", client=client,
            context={"attempts": row.attempts, "exhausted": exhausted}, commit=True,
        )
        raise AuthError("Invalid or expired reset code")

    # Schema already enforces complexity; this adds the user-specific rules
    # (email/name must not appear in the password) that need that context.
    validate_password(new_password, email=user.email, name=user.name)

    user.password = hash_password(new_password)
    user.last_password_change_at = now
    user.failed_login_attempts = 0
    user.locked_at = None
    reset_type = row.reset_type
    await crud.delete_reset_token(db, user.email)
    await audit(
        db, Event.PASSWORD_RESET_COMPLETED, user=user, client=client,
        context={"method": reset_type},
    )

    # Mirror into Authentik (best-effort; plaintext only in scope here).
    await sync_set_password(db, user, new_password)
    # Security confirmation to the account holder — best-effort: a mail hiccup
    # must never roll back a completed password reset.
    try:
        await auth_emails.send_password_changed_email(db, user, client=client)
    except Exception as e:  # noqa: BLE001
        logger.error("password_changed_email_failed", user_id=user.id, error=str(e))
