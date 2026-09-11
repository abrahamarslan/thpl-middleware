"""User moderation: ban/unban (hard) and throttle/unthrottle (soft).

Two independent levers, deliberately distinct from account lifecycle
(``is_deactivated``) and from automatic lockout (``locked_at``):

  - **Ban** — the account may not authenticate *or* use the API at all. A ban
    can be permanent (``banned_until = NULL``) or temporary; an expired
    temporary ban is transparently treated as lifted. Banning also deactivates
    the Authentik account and destroys any in-flight reset/OTP challenge.
  - **Throttle** — the account may keep its existing session but may not start
    new authentication/credential flows until ``throttled_until``. Useful for
    slowing abuse without a full ban.

Pure predicates (``is_banned``/``is_throttled``) are separated from the async
mutators (which record activity and mirror active state to Authentik) so the
checks can be reused by every auth entry point and tested without I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AuthError, ForbiddenError, RateLimitedError
from app.modules.activity.recorder import record_activity
from app.modules.users import authentik_sync, crud
from app.modules.users.authentik_sync import SyncResult
from app.modules.users.model import User

logger = structlog.get_logger("app.users.moderation")


# ── Pure predicates ───────────────────────────────────────────────────────────

def is_banned(user: User, *, now: datetime | None = None) -> bool:
    if not user.is_banned:
        return False
    if user.banned_until is not None and (now or datetime.now(UTC)) >= user.banned_until:
        return False  # temporary ban expired
    return True


def is_throttled(user: User, *, now: datetime | None = None) -> bool:
    if not user.is_throttled:
        return False
    if user.throttled_until is not None and (now or datetime.now(UTC)) >= user.throttled_until:
        return False
    return True


def moderation_state(user: User, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    banned = is_banned(user, now=now)
    throttled = is_throttled(user, now=now)
    if user.deleted_at is not None:
        state = "deleted"
    elif user.is_deactivated:
        state = "deactivated"
    elif banned:
        state = "banned"
    elif throttled:
        state = "throttled"
    elif user.locked_at is not None:
        state = "locked"
    else:
        state = "active"
    return {
        "state": state,
        "is_banned": banned,
        "ban_reason": user.ban_reason,
        "banned_at": user.banned_at,
        "banned_until": user.banned_until,
        "is_throttled": throttled,
        "throttle_reason": user.throttle_reason,
        "throttled_at": user.throttled_at,
        "throttled_until": user.throttled_until,
        "is_locked": user.locked_at is not None,
        "locked_at": user.locked_at,
        "is_deactivated": bool(user.is_deactivated),
    }


# ── Guards used by auth entry points ─────────────────────────────────────────

def ensure_can_authenticate(user: User, *, now: datetime | None = None) -> None:
    """Raise for a user who may not start/continue an authentication flow."""
    if user.deleted_at is not None:
        raise AuthError("Invalid credentials")
    if user.is_deactivated:
        raise ForbiddenError("Account is deactivated")
    if is_banned(user, now=now):
        raise ForbiddenError("Account is banned")
    if is_throttled(user, now=now):
        raise RateLimitedError("Account is temporarily throttled; try again later")


def ensure_can_use_api(user: User, *, now: datetime | None = None) -> None:
    """Raise for a user who may not use the API at all (session guard)."""
    if user.deleted_at is not None:
        raise AuthError("User no longer exists")
    if user.is_deactivated:
        raise ForbiddenError("Account is deactivated")
    if is_banned(user, now=now):
        raise ForbiddenError("Account is banned")


# ── Async mutators ────────────────────────────────────────────────────────────

def _enqueue_sync_active(user_id: int, is_active: bool) -> None:
    try:
        from app.tasks import authentik as ak_tasks

        ak_tasks.sync_status.delay(user_id, is_active)
    except Exception as e:  # noqa: BLE001
        logger.error("authentik_enqueue_failed", task="sync_status", error=str(e))


async def ban_user(
    db: AsyncSession,
    user: User,
    *,
    reason: str,
    until: datetime | None = None,
    actor_id: int | None = None,
) -> User:
    now = datetime.now(UTC)
    user.is_banned = True
    user.ban_reason = reason
    user.banned_at = now
    user.banned_until = until
    user.banned_by = actor_id
    user.has_active_session = False
    # A banned account must not be mid-recovery.
    await crud.delete_reset_token(db, user.email)
    await crud.delete_login_otp(db, user.email)
    await db.flush()
    await record_activity(
        db,
        action="user_banned",
        actor_id=actor_id,
        subject_type="User",
        subject_id=user.id,
        changes={"reason": reason, "until": until.isoformat() if until else None},
    )
    if await authentik_sync.sync_set_active(db, user, False) is SyncResult.FAILED:
        _enqueue_sync_active(user.id, False)
    logger.warning("user_banned", user_id=user.id, by=actor_id, until=until)
    return user


async def unban_user(db: AsyncSession, user: User, *, actor_id: int | None = None) -> User:
    user.is_banned = False
    user.ban_reason = None
    user.banned_at = None
    user.banned_until = None
    user.banned_by = None
    await db.flush()
    await record_activity(
        db, action="user_unbanned", actor_id=actor_id,
        subject_type="User", subject_id=user.id,
    )
    # Restore Authentik access only if the account is otherwise usable.
    if not user.is_deactivated and user.deleted_at is None:
        if await authentik_sync.sync_set_active(db, user, True) is SyncResult.FAILED:
            _enqueue_sync_active(user.id, True)
    logger.info("user_unbanned", user_id=user.id, by=actor_id)
    return user


async def throttle_user(
    db: AsyncSession,
    user: User,
    *,
    reason: str,
    until: datetime | None = None,
    actor_id: int | None = None,
) -> User:
    user.is_throttled = True
    user.throttle_reason = reason
    user.throttled_at = datetime.now(UTC)
    user.throttled_until = until
    user.throttled_by = actor_id
    await db.flush()
    await record_activity(
        db, action="user_throttled", actor_id=actor_id,
        subject_type="User", subject_id=user.id,
        changes={"reason": reason, "until": until.isoformat() if until else None},
    )
    logger.warning("user_throttled", user_id=user.id, by=actor_id, until=until)
    return user


async def unthrottle_user(db: AsyncSession, user: User, *, actor_id: int | None = None) -> User:
    user.is_throttled = False
    user.throttle_reason = None
    user.throttled_at = None
    user.throttled_until = None
    user.throttled_by = None
    await db.flush()
    await record_activity(
        db, action="user_unthrottled", actor_id=actor_id,
        subject_type="User", subject_id=user.id,
    )
    logger.info("user_unthrottled", user_id=user.id, by=actor_id)
    return user
