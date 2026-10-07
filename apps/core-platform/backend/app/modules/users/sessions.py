"""Sign-in sessions: create, check, rotate, revoke (docs/auth/sessions.md).

THE rule: a first-party token with a ``sid`` works only while its ``auth.user_sessions`` row is live.

* ``start``   — every sign-in (password, OTP) creates a session. A FIELD-APP sign-in applies the user's
  single-session rule (``SessionRule``: max live field sessions, and what to do when exceeded):
  ``revoke_previous`` revokes the oldest live field sessions (reason ``signed_in_elsewhere``, with a
  telemetry-drain grant), ``refuse`` answers 409 ``active_session_exists``. Web and service sessions
  are unlimited unless ``MAX_WEB_SESSIONS`` says otherwise.
* ``check``   — per request: the session's state, Redis DB 0 key ``auth:session:<sid>`` (TTL
  ``SESSION_CACHE_TTL_SECONDS``) in front of the row. Revocation writes the key FIRST, then the row.
  ``last_seen_at`` is touched at most once a minute (a Redis NX gate), never on every request.
* ``refresh`` — rotation: every refresh issues a new refresh jti; presenting the PREVIOUS one again is
  reuse (a stolen token racing the real client) and revokes the whole session (``refresh_reuse``).
* ``revoke``  — logout, logout-all, admin, password change.

WHO decides the field rule is not this module: ``users`` must not import ``fieldops`` (it is a leaf),
so field operations REGISTERS a provider (``register_rule_provider``) that resolves the policy setting
``session.field`` for the user (organization / role / user layers). Without one, ``FIELD_MAX_SESSIONS``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid as uuid_lib
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.client_info import ClientInfo
from app.common.exception.errors import AuthError, ConflictError, NotFoundError
from app.common.security.jwt import create_access_token, create_refresh_token
from app.core.conf import settings
from app.modules.users.schema import TokenPair
from app.modules.users.session_model import UserSession

logger = structlog.get_logger("app.users.sessions")

#: The verified claims of the current request's first-party token (set by ``deps._authenticate``).
_claims: ContextVar[dict[str, Any] | None] = ContextVar("auth_claims", default=None)


def current_claims() -> dict[str, Any] | None:
    return _claims.get()


def bind_claims(claims: dict[str, Any] | None) -> None:
    _claims.set(claims)

FIELD_APP, WEB, SERVICE = "field_app", "web", "service"
_FIELD_DEVICE_TYPES = {"android", "ios", "mobile", "field_app"}
_STATE_KEY = "auth:session:{sid}"
_SEEN_KEY = "auth:session:seen:{sid}"
#: Requests a displaced field session may still make during its drain grant (queued telemetry only).
DRAIN_PATHS = ("/api/me/location-pings", "/api/me/device-events")
#: Two refreshes racing from ONE app (parallel requests) present the same token twice: within this
#: window the immediately previous refresh token still rotates instead of being treated as theft.
REFRESH_REUSE_GRACE = dt.timedelta(seconds=30)


class SessionRevoked(AuthError):
    """401 ``session_revoked`` — distinct from an expired/invalid token so the app can tell the user WHY."""

    code = "session_revoked"


class SessionConflict(ConflictError):
    code = "active_session_exists"


@dataclass(frozen=True, slots=True)
class SessionRule:
    max_sessions: int = 0                  # 0 = unlimited
    on_new_login: str = "revoke_previous"  # revoke_previous | refuse
    drain_grant_hours: int = 24


RuleProvider = Callable[[AsyncSession, Any], Awaitable[SessionRule]]
_providers: list[RuleProvider] = []


def register_rule_provider(provider: RuleProvider) -> None:
    """Field operations registers the ``session.field`` resolver here (users never imports fieldops)."""
    if provider not in _providers:
        _providers.append(provider)


async def field_rule(db: AsyncSession, user: Any) -> SessionRule:
    for provider in _providers:
        try:
            return await provider(db, user)
        except Exception as exc:  # noqa: BLE001 — a broken policy must not lock everyone out
            logger.warning("session_rule_provider_failed", error=str(exc), user_id=user.id)
    return SessionRule(max_sessions=settings.FIELD_MAX_SESSIONS)


def client_type_of(explicit: str | None, device_type: str | None) -> str:
    if explicit in (FIELD_APP, WEB, SERVICE):
        return explicit
    if device_type and device_type.strip().lower() in _FIELD_DEVICE_TYPES:
        return FIELD_APP
    return WEB


def _hash(jti: str) -> str:
    return hashlib.sha256(jti.encode()).hexdigest()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _tokens(user: Any, session: UserSession, refresh_jti: str) -> TokenPair:
    sid = str(session.uuid)
    claims = {"email": user.email, "role_id": user.role_id, "user_type": user.user_type, "sid": sid,
              "jti": uuid_lib.uuid4().hex}
    return TokenPair(
        access_token=create_access_token(str(user.id), claims=claims),
        refresh_token=create_refresh_token(str(user.id), claims={"sid": sid, "jti": refresh_jti}),
        expires_in=settings.JWT_EXPIRATION_HOURS * 3600,
        session_uuid=session.uuid,
    )


# ── cache ───────────────────────────────────────────────────────────────────────

async def _cache_set(session: UserSession) -> None:
    ttl = int(settings.SESSION_CACHE_TTL_SECONDS)
    if ttl <= 0:
        return
    try:
        from app.database.redis import redis_client

        await redis_client.set(_STATE_KEY.format(sid=session.uuid), _encode(session), ex=ttl)
    except Exception as exc:  # noqa: BLE001 — the database stays authoritative
        logger.warning("session_cache_write_failed", error=str(exc))


async def _cache_get(sid: str) -> dict | None:
    if int(settings.SESSION_CACHE_TTL_SECONDS) <= 0:
        return None
    try:
        from app.database.redis import redis_client

        raw = await redis_client.get(_STATE_KEY.format(sid=sid))
    except Exception:  # noqa: BLE001
        return None
    return _decode(raw) if raw else None


def _encode(session: UserSession) -> str:
    def iso(v):
        return v.isoformat() if v else ""

    return "|".join((str(session.user_id), iso(session.expires_at), session.revoked_reason or "",
                     iso(session.revoked_at), iso(session.drain_until)))


def _decode(raw: str) -> dict:
    user_id, expires, reason, revoked, drain = (raw.split("|") + [""] * 5)[:5]

    def ts(v):
        return dt.datetime.fromisoformat(v) if v else None

    return {"user_id": int(user_id), "expires_at": ts(expires), "revoked_reason": reason or None,
            "revoked_at": ts(revoked), "drain_until": ts(drain)}


# ── create ──────────────────────────────────────────────────────────────────────

async def start(db: AsyncSession, user: Any, *, client: ClientInfo | None = None, client_type: str = WEB,
                installation_id: str | None = None, device_label: str | None = None) -> TokenPair:
    """Create a session for ``user`` (applying the single-session rule) and issue its token pair."""
    displaced: list[UserSession] = []
    rule = await field_rule(db, user) if client_type == FIELD_APP else SessionRule(settings.MAX_WEB_SESSIONS)
    if rule.max_sessions > 0:
        live = (await db.scalars(select(UserSession).where(
            UserSession.tenant_id == user.tenant_id, UserSession.user_id == user.id,
            UserSession.client_type == client_type, UserSession.revoked_at.is_(None), UserSession.expires_at > _now(),
        ).order_by(UserSession.created_at).execution_options(all_tenants=True))).all()
        excess = len(live) - rule.max_sessions + 1
        if excess > 0:
            if rule.on_new_login == "refuse":
                newest = live[-1]
                raise SessionConflict(
                    "You are already signed in on another device; sign out there first",
                    data={"session_uuid": str(newest.uuid), "device": newest.device_label,
                          "last_seen_at": newest.last_seen_at.isoformat()})
            displaced = list(live[:excess])
    refresh_jti = uuid_lib.uuid4().hex
    # Sign-in runs before the request is bound to the user's tenant: stamp it explicitly.
    session = UserSession(
        tenant_id=user.tenant_id, user_id=user.id, organization_id=user.organization_id, client_type=client_type,
        installation_id=installation_id, device_label=(device_label or "")[:160] or None,
        ip_address=client.ip if client else None, user_agent=client.user_agent if client else None,
        expires_at=_now() + dt.timedelta(days=settings.SESSION_MAX_DAYS), refresh_jti_hash=_hash(refresh_jti),
    )
    db.add(session)
    await db.flush()
    for old in displaced:
        await revoke(db, old, reason="signed_in_elsewhere", by_session=session,
                     drain_hours=rule.drain_grant_hours if client_type == FIELD_APP else 0)
    tokens = _tokens(user, session, refresh_jti)
    tokens.displaced_sessions = len(displaced)
    logger.info("auth.session_started", user_id=user.id, client_type=client_type, displaced=len(displaced))
    return tokens


# ── check ───────────────────────────────────────────────────────────────────────

async def check(db: AsyncSession, payload: dict[str, Any], *, path: str | None = None) -> dt.datetime | None:
    """Raise unless the token's session is live. Returns the drain cut-off (``revoked_at``) when a displaced
    field session is uploading its queued telemetry under its grant; ``None`` otherwise."""
    sid = payload.get("sid")
    if not sid:
        if settings.AUTH_REQUIRE_SESSION:
            raise AuthError("This token is not bound to a session; sign in again")
        return None
    state = await _cache_get(sid)
    if state is None:
        row = await db.scalar(select(UserSession).where(UserSession.uuid == _uuid(sid))
                              .execution_options(all_tenants=True))
        if row is None:
            raise SessionRevoked("Your session no longer exists; sign in again", data={"reason": "unknown_session"})
        await _cache_set(row)
        state = {"user_id": row.user_id, "expires_at": row.expires_at, "revoked_reason": row.revoked_reason,
                 "revoked_at": row.revoked_at, "drain_until": row.drain_until}
    if str(state["user_id"]) != str(payload.get("sub")):
        raise AuthError("Token and session do not match")
    now = _now()
    if state["revoked_reason"]:
        drain = state["drain_until"]
        if path in DRAIN_PATHS and drain is not None and now < drain:
            return state["revoked_at"]
        raise SessionRevoked(_REVOKED_MSG.get(state["revoked_reason"], "Your session has ended; sign in again"),
                             data={"reason": state["revoked_reason"],
                                   "revoked_at": state["revoked_at"].isoformat() if state["revoked_at"] else None,
                                   "drain_until": drain.isoformat() if drain and now < drain else None})
    if state["expires_at"] is not None and state["expires_at"] <= now:
        raise SessionRevoked("Your session has expired; sign in again", data={"reason": "expired"})
    await _touch(db, sid)
    return None


_REVOKED_MSG = {
    "signed_in_elsewhere": "You signed in on another device",
    "logout": "You signed out",
    "logout_all": "You signed out of every device",
    "refresh_reuse": "Your session was ended for security reasons; sign in again",
    "admin": "An administrator ended your session",
    "password_changed": "Your password changed; sign in again",
    "user_deactivated": "Your account is deactivated",
}


async def _touch(db: AsyncSession, sid: str) -> None:
    """``last_seen_at`` at most once a minute per session (Redis NX gate; without Redis, every 60 s by row)."""
    try:
        from app.database.redis import redis_client

        if not await redis_client.set(_SEEN_KEY.format(sid=sid), "1", nx=True, ex=60):
            return
    except Exception:  # noqa: BLE001
        pass
    await db.execute(update(UserSession).where(UserSession.uuid == _uuid(sid),
                                               UserSession.last_seen_at < _now() - dt.timedelta(seconds=60))
                     .values(last_seen_at=_now())
                     .execution_options(synchronize_session=False, all_tenants=True))


def _uuid(raw: str) -> uuid_lib.UUID:
    try:
        return uuid_lib.UUID(str(raw))
    except ValueError:
        raise AuthError("Invalid session id") from None


# ── refresh (rotation + reuse detection) ───────────────────────────────────────

async def refresh(db: AsyncSession, payload: dict[str, Any], user: Any) -> TokenPair | None:
    """Rotate a session-bound refresh token. ``None`` when the token has no ``sid`` (legacy: the caller
    issues a session-less pair as before)."""
    sid = payload.get("sid")
    if not sid:
        return None
    session = await db.scalar(select(UserSession).where(UserSession.uuid == _uuid(sid))
                              .execution_options(all_tenants=True))
    if session is None or session.user_id != user.id:
        raise SessionRevoked("Your session no longer exists; sign in again", data={"reason": "unknown_session"})
    if session.revoked_at is not None or session.expires_at <= _now():
        raise SessionRevoked(_REVOKED_MSG.get(session.revoked_reason or "", "Your session has ended; sign in again"),
                             data={"reason": session.revoked_reason or "expired"})
    presented = _hash(str(payload.get("jti") or ""))
    benign_race = (presented == session.previous_refresh_jti_hash and session.updated_at is not None
                   and _now() - session.updated_at < REFRESH_REUSE_GRACE)
    if presented != session.refresh_jti_hash and not benign_race:
        if presented == session.previous_refresh_jti_hash:
            await revoke(db, session, reason="refresh_reuse")
            logger.warning("auth.refresh_reuse_detected", user_id=user.id, session=str(session.uuid))
            raise SessionRevoked(_REVOKED_MSG["refresh_reuse"], data={"reason": "refresh_reuse"})
        raise AuthError("Invalid refresh token")
    new_jti = uuid_lib.uuid4().hex
    session.previous_refresh_jti_hash = session.refresh_jti_hash
    session.refresh_jti_hash = _hash(new_jti)
    await db.flush()
    return _tokens(user, session, new_jti)


# ── revoke / list ───────────────────────────────────────────────────────────────

async def revoke(db: AsyncSession, session: UserSession, *, reason: str, by_session: UserSession | None = None,
                 drain_hours: int = 0) -> None:
    if session.revoked_at is not None:
        return
    session.revoked_at = _now()
    session.revoked_reason = reason
    session.revoked_by_session_id = by_session.id if by_session is not None else None
    session.drain_until = session.revoked_at + dt.timedelta(hours=drain_hours) if drain_hours > 0 else None
    await _cache_set(session)               # the cache first: the next request must not see "live"
    await db.flush()
    logger.info("auth.session_revoked", user_id=session.user_id, session=str(session.uuid), reason=reason)


async def revoke_current(db: AsyncSession, payload: dict[str, Any] | None, *, reason: str = "logout") -> bool:
    sid = (payload or {}).get("sid")
    if not sid:
        return False
    session = await db.scalar(select(UserSession).where(UserSession.uuid == _uuid(sid))
                              .execution_options(all_tenants=True))
    if session is None:
        return False
    await revoke(db, session, reason=reason)
    return True


async def revoke_all(db: AsyncSession, user_id: int, *, reason: str, except_sid: str | None = None) -> int:
    rows = (await db.scalars(select(UserSession).where(UserSession.user_id == user_id,
                                                       UserSession.revoked_at.is_(None))
                             .execution_options(all_tenants=True))).all()
    count = 0
    for row in rows:
        if except_sid and str(row.uuid) == str(except_sid):
            continue
        await revoke(db, row, reason=reason)
        count += 1
    return count


async def list_sessions(db: AsyncSession, user_id: int, *, include_revoked: bool = False,
                        limit: int = 50) -> list[UserSession]:
    stmt = select(UserSession).where(UserSession.user_id == user_id)
    if not include_revoked:
        stmt = stmt.where(UserSession.revoked_at.is_(None), UserSession.expires_at > _now())
    return list((await db.scalars(stmt.order_by(UserSession.created_at.desc()).limit(limit))).all())


async def get_session(db: AsyncSession, ref: str, *, user_id: int | None = None) -> UserSession:
    stmt = select(UserSession).where(UserSession.uuid == _uuid(ref))
    if user_id is not None:
        stmt = stmt.where(UserSession.user_id == user_id)
    row = await db.scalar(stmt)
    if row is None:
        raise NotFoundError("Session not found")
    return row


__all__ = [
    "DRAIN_PATHS", "FIELD_APP", "SERVICE", "WEB", "SessionConflict", "SessionRevoked", "SessionRule", "bind_claims",
    "check", "current_claims",
    "client_type_of", "field_rule", "get_session", "list_sessions", "refresh", "register_rule_provider", "revoke",
    "revoke_all", "revoke_current", "start",
]
