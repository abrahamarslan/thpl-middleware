"""Users module — business logic (service layer).

Covers: registration, password login with lockout, token issuance/refresh,
password change/forgot/reset, Authentik JIT provisioning, and the full
user CRUD lifecycle (list/get/create/update/soft-delete/restore/hard-delete).
"""

import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import structlog
from geoalchemy2 import WKTElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AuthError, ConflictError, ForbiddenError, NotFoundError
from app.common.security.jwt import create_access_token, create_refresh_token, decode_token
from app.core.conf import settings
from app.modules.users import authentik_sync, crud
from app.modules.users.authentik_sync import AUTHENTIK_SYNCED_FIELDS, SyncResult
from app.modules.users.model import User
from app.modules.users.schema import (
    GEO_FIELDS,
    LoginRequest,
    RegisterRequest,
    TokenPair,
    UserCreate,
    UserListFilters,
    UserUpdate,
)

logger = structlog.get_logger("app.users.service")

_RESET_TOKEN_TTL_MINUTES = 30


# ── Authentik sync enqueue helper ─────────────────────────────────────────────

def _enqueue_authentik(task_name: str, *args) -> None:
    """Best-effort enqueue of an Authentik retry task. Importing lazily avoids a
    hard dependency on Celery at request time; a broker hiccup must not fail the
    HTTP request (the row already carries an actionable sync status)."""
    try:
        from app.tasks import authentik as ak_tasks

        getattr(ak_tasks, task_name).delay(*args)
    except Exception as e:  # noqa: BLE001
        logger.error("authentik_enqueue_failed", task=task_name, error=str(e))


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _geo_to_elements(values: dict) -> dict:
    """Convert WKT strings to PostGIS-bindable elements (SRID 4326)."""
    for field in GEO_FIELDS:
        if values.get(field):
            values[field] = WKTElement(values[field], srid=4326)
    return values


def _token_pair(user: User) -> TokenPair:
    claims = {"email": user.email, "role_id": user.role_id, "user_type": user.user_type}
    return TokenPair(
        access_token=create_access_token(str(user.id), claims=claims),
        refresh_token=create_refresh_token(str(user.id)),
        expires_in=settings.JWT_EXPIRATION_HOURS * 3600,
    )


# ── Authentication ────────────────────────────────────────────────────────────

async def register(db: AsyncSession, body: RegisterRequest) -> User:
    if await crud.get_by_email(db, body.email, include_deleted=True):
        raise ConflictError("A user with this email already exists")
    if body.username and await crud.get_by_username(db, body.username):
        raise ConflictError("This username is taken")

    user = await crud.create(db, {
        "name": body.name,
        "email": body.email.lower(),
        "username": body.username,
        "phone": body.phone,
        "password": hash_password(body.password),
        "last_password_change_at": datetime.now(UTC),
    })
    logger.info("user_registered", user_id=user.id)

    # Mirror into Authentik (best-effort). Plaintext is only available here.
    result = await authentik_sync.sync_create(db, user, body.password)
    if result is SyncResult.FAILED:
        _enqueue_authentik("provision_user", user.id)
    return user


async def login(db: AsyncSession, body: LoginRequest) -> tuple[User, TokenPair]:
    user = await crud.get_by_email(db, body.email_or_username) or await crud.get_by_username(
        db, body.email_or_username
    )
    if user is None:
        raise AuthError("Invalid credentials")

    # Lockout window
    if user.locked_at is not None:
        unlock_at = user.locked_at + timedelta(minutes=settings.AUTH_LOCKOUT_MINUTES)
        if datetime.now(UTC) < unlock_at:
            raise AuthError("Account locked due to failed login attempts; try again later")
        user.locked_at = None
        user.failed_login_attempts = 0

    if user.is_deactivated or user.deleted_at is not None:
        raise ForbiddenError("Account is deactivated")

    if not verify_password(body.password, user.password):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= settings.AUTH_MAX_FAILED_LOGINS:
            user.locked_at = datetime.now(UTC)
            logger.warning("user_locked", user_id=user.id, attempts=user.failed_login_attempts)
        await db.flush()
        raise AuthError("Invalid credentials")

    user.failed_login_attempts = 0
    user.locked_at = None
    user.last_login = datetime.now(UTC)
    user.has_active_session = True
    if body.device_id:
        user.device_id = body.device_id
    if body.device_type:
        user.device_type = body.device_type
    await db.flush()

    logger.info("user_login", user_id=user.id, device_id=body.device_id)
    return user, _token_pair(user)


async def refresh_tokens(db: AsyncSession, refresh_token: str) -> TokenPair:
    payload = decode_token(refresh_token, expected_type="refresh")
    user = await crud.get_by_id(db, int(payload["sub"]))
    if user is None or user.is_deactivated:
        raise AuthError("User no longer active")
    return _token_pair(user)


async def change_password(db: AsyncSession, user: User, *, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.password):
        raise AuthError("Current password is incorrect")
    user.password = hash_password(new_password)
    user.last_password_change_at = datetime.now(UTC)
    await db.flush()
    logger.info("password_changed", user_id=user.id)

    # Mirror the new password into Authentik (best-effort; plaintext in scope).
    await authentik_sync.sync_set_password(db, user, new_password)


async def request_password_reset(db: AsyncSession, *, email: str, reset_type: str) -> dict:
    """Create a reset token/code. Returns it only when DEBUG (no SMTP wired
    yet) — in production, deliver via email and return nothing."""
    user = await crud.get_by_email(db, email)
    if user is None:
        # Do not reveal account existence
        return {"sent": True}

    token = secrets.token_urlsafe(48)
    code = f"{secrets.randbelow(1_000_000):06d}" if reset_type == "code" else None
    await crud.upsert_reset_token(db, email=user.email, token=token, reset_type=reset_type, code=code)
    logger.info("password_reset_requested", user_id=user.id, reset_type=reset_type)

    # TODO: send via SMTP / notification service
    if settings.DEBUG:
        return {"sent": True, "debug_token": token, "debug_code": code}
    return {"sent": True}


async def reset_password(db: AsyncSession, *, email: str, token_or_code: str, new_password: str) -> None:
    row = await crud.get_reset_token(db, email.lower())
    if row is None:
        raise AuthError("Invalid or expired reset token")
    if row.created_at and datetime.now(UTC) - row.created_at > timedelta(minutes=_RESET_TOKEN_TTL_MINUTES):
        await crud.delete_reset_token(db, email.lower())
        raise AuthError("Reset token expired")
    if not secrets.compare_digest(token_or_code, row.token) and not (
        row.code and secrets.compare_digest(token_or_code, row.code)
    ):
        raise AuthError("Invalid or expired reset token")

    user = await crud.get_by_email(db, email)
    if user is None:
        raise NotFoundError("User not found")
    user.password = hash_password(new_password)
    user.last_password_change_at = datetime.now(UTC)
    user.failed_login_attempts = 0
    user.locked_at = None
    await crud.delete_reset_token(db, email.lower())
    logger.info("password_reset_complete", user_id=user.id)

    # Mirror the reset password into Authentik (best-effort; plaintext in scope).
    await authentik_sync.sync_set_password(db, user, new_password)


# ── Authentik JIT provisioning ───────────────────────────────────────────────

async def provision_from_authentik(db: AsyncSession, claims: dict) -> User:
    """Resolve an Authentik token to a local user, creating one on first sight.

    Linking: external_id <- Authentik `sub`; falls back to email match for
    users that pre-existed Authentik (and back-fills external_id).
    """
    sub = str(claims["sub"])
    user = await crud.get_by_external_id(db, sub)
    if user is None and claims.get("email"):
        user = await crud.get_by_email(db, claims["email"])
        if user and not user.external_id:
            user.external_id = sub

    if user is None:
        user = await crud.create(db, {
            "external_id": sub,
            "email": (claims.get("email") or f"{sub}@authentik.local").lower(),
            "name": claims.get("name") or claims.get("preferred_username") or "Authentik User",
            "username": claims.get("preferred_username"),
            "first_name": claims.get("given_name"),
            "last_name": claims.get("family_name"),
            "email_verified_at": datetime.now(UTC) if claims.get("email_verified") else None,
            "password": hash_password(secrets.token_urlsafe(32)),  # unusable; SSO-only account
            "user_type": "sso",
            "onboarding_status": "provisioned",
        })
        logger.info("user_provisioned_from_authentik", user_id=user.id, sub=sub)

    if user.is_deactivated or user.deleted_at is not None:
        raise ForbiddenError("Account is deactivated")
    user.last_login = datetime.now(UTC)
    await db.flush()
    return user


# ── User CRUD lifecycle ───────────────────────────────────────────────────────

async def list_users(db: AsyncSession, filters: UserListFilters) -> tuple[list[User], int]:
    return await crud.list_users(db, **filters.model_dump())


async def get_user(db: AsyncSession, user_id: int, *, include_deleted: bool = False) -> User:
    user = await crud.get_by_id(db, user_id, include_deleted=include_deleted)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user


async def create_user(db: AsyncSession, body: UserCreate, *, created_by: int | None = None) -> User:
    if await crud.get_by_email(db, body.email, include_deleted=True):
        raise ConflictError("A user with this email already exists")
    if body.username and await crud.get_by_username(db, body.username):
        raise ConflictError("This username is taken")

    values = _geo_to_elements(body.model_dump(exclude_unset=True, exclude_none=True))
    values["email"] = body.email.lower()
    values["password"] = hash_password(values.pop("password"))
    values["created_by"] = created_by
    values["last_password_change_at"] = datetime.now(UTC)
    user = await crud.create(db, values)
    logger.info("user_created", user_id=user.id, created_by=created_by)

    # Mirror into Authentik (best-effort). Plaintext is only available here.
    result = await authentik_sync.sync_create(db, user, body.password)
    if result is SyncResult.FAILED:
        _enqueue_authentik("provision_user", user.id)
    return user


async def update_user(db: AsyncSession, user_id: int, body: UserUpdate, *, updated_by: int | None = None) -> User:
    user = await get_user(db, user_id)

    values = _geo_to_elements(body.model_dump(exclude_unset=True))
    if "email" in values and values["email"]:
        existing = await crud.get_by_email(db, values["email"], include_deleted=True)
        if existing and existing.id != user.id:
            raise ConflictError("A user with this email already exists")
        values["email"] = values["email"].lower()
    if values.get("username"):
        existing = await crud.get_by_username(db, values["username"])
        if existing and existing.id != user.id:
            raise ConflictError("This username is taken")

    values["updated_by"] = updated_by
    user = await crud.update(db, user, values)
    logger.info("user_updated", user_id=user.id, updated_by=updated_by, fields=list(values.keys()))

    # Mirror profile changes into Authentik only when a synced field changed.
    changed = AUTHENTIK_SYNCED_FIELDS & set(values.keys())
    if changed:
        result = await authentik_sync.sync_update_profile(db, user, changed)
        if result is SyncResult.FAILED:
            _enqueue_authentik("sync_profile", user.id, sorted(changed))
    return user


async def delete_user(db: AsyncSession, user_id: int, *, deleted_by: int | None = None, hard: bool = False) -> None:
    user = await get_user(db, user_id, include_deleted=hard)
    if hard:
        authentik_pk = user.authentik_pk  # capture before the row is removed
        await crud.hard_delete(db, user)
        logger.warning("user_hard_deleted", user_id=user_id, deleted_by=deleted_by)
        if authentik_pk:
            result = await authentik_sync.sync_delete(authentik_pk)
            if result is SyncResult.FAILED:
                _enqueue_authentik("delete_user", authentik_pk)
    else:
        await crud.soft_delete(db, user, deleted_by=deleted_by)
        logger.info("user_soft_deleted", user_id=user_id, deleted_by=deleted_by)
        # A soft delete deactivates the Authentik account (keeps it for restore).
        result = await authentik_sync.sync_set_active(db, user, False)
        if result is SyncResult.FAILED:
            _enqueue_authentik("sync_status", user.id, False)


async def restore_user(db: AsyncSession, user_id: int) -> User:
    user = await crud.get_by_id(db, user_id, include_deleted=True)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    if user.deleted_at is None:
        raise ConflictError("User is not deleted")
    user = await crud.restore(db, user)
    logger.info("user_restored", user_id=user.id)

    # Reactivate the Authentik account that the soft delete disabled.
    result = await authentik_sync.sync_set_active(db, user, True)
    if result is SyncResult.FAILED:
        _enqueue_authentik("sync_status", user.id, True)
    return user
