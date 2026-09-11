"""Auth audit events — one catalog + one dual-write recorder.

Every authentication, credential and moderation event goes through
:func:`audit`, which writes **both**:

* a persisted, queryable ``activity_logs`` row (compliance: who did what, to whom,
  when, from where — with ``request_id`` linking back to Loki/Tempo); and
* a structured ``structlog`` line (operational; shipped to Loki).

Emitting both from one call means the audit trail and the operational log can
never drift apart.

**`commit=True` is for failure paths that raise a domain error.** When a
domain error (e.g. ``AuthError``) propagates out of a route, the ``get_db``
dependency rolls the transaction back — discarding any counter increment or
audit row written just before the raise. Failure paths therefore commit the
security state (attempt counters, lockouts) *and* their audit row explicitly
before raising. Success paths let the request commit them normally.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.client_info import ClientInfo
from app.modules.activity.recorder import record_activity

logger = structlog.get_logger("app.users.audit")


class Event:
    """Canonical action names (dotted; stable, queryable in `activity_logs`)."""

    # Identity lifecycle
    REGISTER = "auth.register"
    PROVISIONED = "auth.provisioned"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.profile.updated"
    USER_DELETED = "user.deleted"
    USER_HARD_DELETED = "user.hard_deleted"
    USER_RESTORED = "user.restored"

    # Sessions / tokens
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILURE = "auth.login.failure"
    LOGIN_LOCKED = "auth.login.locked"
    LOGOUT = "auth.logout"
    TOKEN_ISSUED = "auth.token.issued"
    TOKEN_REFRESH = "auth.token.refresh"
    TOKEN_REFRESH_FAILURE = "auth.token.refresh.failure"

    # Password / OTP
    OTP_REQUEST = "auth.otp.request"
    OTP_REQUEST_SUPPRESSED = "auth.otp.request.suppressed"
    OTP_LOGIN = "auth.otp.login"
    OTP_FAILURE = "auth.otp.failure"
    PASSWORD_CHANGED = "auth.password.changed"
    PASSWORD_CHANGE_FAILURE = "auth.password.change.failure"
    PASSWORD_RESET_REQUEST = "auth.password.reset.request"
    PASSWORD_RESET_COMPLETED = "auth.password.reset.completed"
    PASSWORD_RESET_FAILURE = "auth.password.reset.failure"

    # Moderation
    BAN = "user.moderation.ban"
    UNBAN = "user.moderation.unban"
    THROTTLE = "user.moderation.throttle"
    UNTHROTTLE = "user.moderation.unthrottle"


def _client_context(client: ClientInfo | None) -> dict[str, Any]:
    if client is None:
        return {}
    return {
        "device": client.device,
        "location": client.location,
        "country": client.country_code,
        "user_agent": client.user_agent,
    }


async def audit(
    db: AsyncSession,
    event: str,
    *,
    user: Any | None = None,
    actor_id: int | None = None,
    actor_label: str | None = None,
    status: str = "success",
    description: str | None = None,
    changes: dict | None = None,
    client: ClientInfo | None = None,
    context: dict | None = None,
    best_effort: bool = True,
    commit: bool = False,
) -> None:
    """Record one auth event (structured log + persisted audit row).

    ``user`` is the *subject*; ``actor_id``/``actor_label`` default to the
    subject (self-service) but override it for admin actions.
    """
    subject_id = getattr(user, "id", None)
    if actor_id is None:
        actor_id = subject_id
    if actor_label is None and user is not None:
        actor_label = getattr(user, "email", None)

    ctx: dict[str, Any] = {**_client_context(client), **(context or {})}
    ctx = {k: v for k, v in ctx.items() if v is not None}

    # Operational log (Loki) — request_id is already bound to contextvars.
    logger.info(
        event,
        status=status,
        actor_id=actor_id,
        subject_id=subject_id,
        **ctx,
    )

    # Persisted audit row (same transaction as the business change).
    await record_activity(
        db,
        action=event,
        status=status,
        description=description,
        actor_id=actor_id,
        actor_type="user" if actor_id is not None else "anonymous",
        actor_label=actor_label,
        subject_type="User" if subject_id is not None else None,
        subject_id=subject_id,
        changes=changes,
        context=ctx or None,
        best_effort=best_effort,
    )

    if commit:
        # Persist security state + audit even though the caller will now raise
        # (the request dependency would otherwise roll this transaction back).
        await db.commit()
