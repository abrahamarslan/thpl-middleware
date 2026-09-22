"""Users module — business logic (service layer).

Covers: registration, password login with lockout, token issuance/refresh,
password change/forgot/reset, Authentik JIT provisioning, and the full
user CRUD lifecycle (list/get/create/update/soft-delete/restore/hard-delete).
"""

import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.client_info import ClientInfo
from app.common.exception.errors import AppError, AuthError, ConflictError, ForbiddenError, NotFoundError
from app.common.security.jwt import decode_token
from app.common.time import is_valid_iana_timezone
from app.core.conf import settings
from app.database import scope
from app.database.scope import Scope
from app.modules.activity.recorder import model_changes
from app.modules.users import auth_emails, authentik_sync, crud, identifiers, moderation, password_reset
from app.modules.users.audit import Event, audit
from app.modules.users.authentik_sync import AUTHENTIK_SYNCED_FIELDS, SyncResult
from app.modules.users.model import Country, CountryTimezone, Timezone, TimezoneSource, User, UserProfile
from app.modules.users.password_policy import validate_password
from app.modules.users.schema import (
    LocationUpdate,
    LoginRequest,
    RegisterRequest,
    TokenPair,
    UserCreate,
    UserListFilters,
    UserProfileUpdate,
    UserUpdate,
)
from app.modules.users.security import hash_password, verify_password
from app.modules.users.tokens import issue_token_pair

logger = structlog.get_logger("app.users.service")

__all__ = ["hash_password", "verify_password"]  # re-exported for existing callers


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


# ── Helpers ───────────────────────────────────────────────────────────────────

async def resolve_user_organization(db: AsyncSession, *, org_code: str | None = None) -> Scope:
    """Where a new user is created.

    Registration is unauthenticated, so there is no ambient organization to
    stamp from and ``users.organization_id`` is NOT NULL. The caller may name
    an organization by code (``X-Organization-Code``) — for a public sign-up
    that code is what *chooses* the tenant, so it is resolved across tenants;
    otherwise the deployment's configured default
    (``DEFAULT_ORGANIZATION_CODE`` in ``DEFAULT_TENANT_CODE``) applies.

    Both the tenant and the organization are returned because a user created
    outside any request context must be stamped with both — the tenancy
    listener would otherwise default the tenant independently and could put the
    user in a tenant its organization does not belong to.
    """
    return await scope.require(db, org_code=org_code)


# ── Authentication ────────────────────────────────────────────────────────────

async def register(
    db: AsyncSession, body: RegisterRequest, *,
    client: ClientInfo | None = None, org_code: str | None = None,
) -> User:
    if await crud.get_by_email(db, body.email, include_deleted=True):
        raise ConflictError("A user with this email already exists")
    if body.username and await crud.get_by_username(db, body.username):
        raise ConflictError("This username is taken")
    validate_password(body.password, email=body.email, name=body.name)

    # Localization resolution via GeoIP client info
    detected_country_code = (client.country_code.strip().upper() if client and client.country_code else None)
    detected_timezone = (client.timezone.strip() if client and client.timezone else None)

    country_row = None
    if detected_country_code:
        country_row = await db.scalar(select(Country).where(Country.iso2 == detected_country_code))

    resolved_country_iso2 = country_row.iso2 if country_row else (detected_country_code or "IN")
    resolved_currency = country_row.currency_code if (country_row and country_row.currency_code) else "INR"

    resolved_tz = None
    if detected_timezone and is_valid_iana_timezone(detected_timezone):
        resolved_tz = detected_timezone
    elif resolved_country_iso2:
        default_tz = await db.scalar(
            select(CountryTimezone.timezone_name)
            .where(CountryTimezone.country_iso2 == resolved_country_iso2)
            .where(CountryTimezone.is_default.is_(True))
        )
        if default_tz:
            resolved_tz = default_tz

    resolved_tz = resolved_tz or "Asia/Kolkata"

    where = await resolve_user_organization(db, org_code=org_code)
    user = await crud.create(db, {
        "name": body.name,
        "email": body.email.lower(),
        "username": body.username,
        "phone": body.phone,
        "password": hash_password(body.password),
        "last_password_change_at": datetime.now(UTC),
        "country_code": resolved_country_iso2,
        "timezone": resolved_tz,
        "currency": resolved_currency,
        # Both, together: the organization decides the tenant. Letting the
        # tenancy listener default the tenant independently could put the user
        # in a tenant its own organization does not belong to.
        "tenant_id": where.tenant_id,
        "organization_id": where.organization_id,
    })
    await audit(
        db, Event.REGISTER, user=user, client=client,
        context={"has_username": bool(user.username), "has_phone": bool(user.phone)},
    )

    # Mirror into Authentik (best-effort). Plaintext is only available here.
    result = await authentik_sync.sync_create(db, user, body.password)
    if result is SyncResult.FAILED:
        _enqueue_authentik("provision_user", user.id)

    # Welcome email (best-effort — a mail hiccup must not fail registration).
    try:
        await auth_emails.send_welcome_email(db, user, client=client)
    except Exception as e:  # noqa: BLE001
        logger.error("welcome_email_failed", user_id=user.id, error=str(e))

    # Initialize localization profile (auto-timezone)
    await get_or_create_profile(
        db,
        user.id,
        initial_country=resolved_country_iso2 if (country_row or detected_country_code) else None,
        initial_timezone=resolved_tz,
    )

    return user


async def login(
    db: AsyncSession, body: LoginRequest, *, client: ClientInfo | None = None
) -> tuple[User, TokenPair]:
    user = await identifiers.resolve_user_by_identifier(db, body.identifier)
    if user is None:
        await audit(
            db, Event.LOGIN_FAILURE, actor_label=body.identifier, status="failure",
            description="unknown identifier", client=client, commit=True,
        )
        raise AuthError("Invalid credentials")

    # Lockout window (automatic, from failed password attempts)
    if user.locked_at is not None:
        unlock_at = user.locked_at + timedelta(minutes=settings.AUTH_LOCKOUT_MINUTES)
        if datetime.now(UTC) < unlock_at:
            await audit(
                db, Event.LOGIN_FAILURE, user=user, status="failure",
                description="account locked", client=client, commit=True,
            )
            raise AuthError("Account locked due to failed login attempts; try again later")
        user.locked_at = None
        user.failed_login_attempts = 0

    # Moderation: deactivated / banned / throttled.
    try:
        moderation.ensure_can_authenticate(user)
    except AppError as exc:
        await audit(
            db, Event.LOGIN_FAILURE, user=user, status="failure",
            description=exc.msg, client=client, context={"reason": exc.code}, commit=True,
        )
        raise

    if not verify_password(body.password, user.password):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        locked = user.failed_login_attempts >= settings.AUTH_MAX_FAILED_LOGINS
        if locked:
            user.locked_at = datetime.now(UTC)
        await db.flush()
        await audit(
            db, Event.LOGIN_FAILURE, user=user, status="failure",
            description="invalid credentials", client=client,
            context={"attempts": user.failed_login_attempts, "locked": locked}, commit=True,
        )
        if locked:
            await audit(
                db, Event.LOGIN_LOCKED, user=user, status="failure",
                description=f"locked after {user.failed_login_attempts} failed attempts",
                client=client, commit=True,
            )
        raise AuthError("Invalid credentials")

    try:
        tokens = issue_token_pair(user)
    except Exception as exc:  # noqa: BLE001
        await audit(
            db, Event.LOGIN_FAILURE, user=user, status="failure",
            description=f"token issuance failed: {exc}", client=client, commit=True,
        )
        raise

    user.failed_login_attempts = 0
    user.locked_at = None
    user.last_login = datetime.now(UTC)
    user.has_active_session = True
    if body.device_id:
        user.device_id = body.device_id
    if body.device_type:
        user.device_type = body.device_type
    await db.flush()

    await audit(
        db, Event.LOGIN_SUCCESS, user=user, client=client,
        context={"method": "password", "device_id": body.device_id},
    )
    await audit(
        db, Event.TOKEN_ISSUED, user=user, client=client,
        context={"method": "password", "access": True, "refresh": True},
    )
    return user, tokens


async def refresh_tokens(
    db: AsyncSession, refresh_token: str, *, client: ClientInfo | None = None
) -> TokenPair:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except AuthError:
        await audit(
            db, Event.TOKEN_REFRESH_FAILURE, status="failure",
            description="invalid refresh token", client=client, commit=True,
        )
        raise
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        await audit(
            db, Event.TOKEN_REFRESH_FAILURE, status="failure",
            description="invalid subject", client=client, commit=True,
        )
        raise AuthError("Invalid refresh token") from None
    user = await crud.get_by_id(db, user_id)
    if user is None or user.is_deactivated:
        await audit(
            db, Event.TOKEN_REFRESH_FAILURE, user=user, status="failure",
            description="user no longer active", client=client, commit=True,
        )
        raise AuthError("User no longer active")
    tokens = issue_token_pair(user)
    await audit(db, Event.TOKEN_REFRESH, user=user, client=client)
    await audit(
        db, Event.TOKEN_ISSUED, user=user, client=client,
        context={"method": "refresh", "access": True, "refresh": True},
    )
    return tokens


async def change_password(
    db: AsyncSession,
    user: User,
    *,
    current_password: str,
    new_password: str,
    client: ClientInfo | None = None,
) -> None:
    if not verify_password(current_password, user.password):
        await audit(
            db, Event.PASSWORD_CHANGE_FAILURE, user=user, status="failure",
            description="current password incorrect", client=client, commit=True,
        )
        raise AuthError("Current password is incorrect")
    validate_password(new_password, email=user.email, name=user.name)
    user.password = hash_password(new_password)
    user.last_password_change_at = datetime.now(UTC)
    await db.flush()
    await audit(db, Event.PASSWORD_CHANGED, user=user, client=client, context={"method": "self"})

    # Mirror the new password into Authentik (best-effort; plaintext in scope).
    await authentik_sync.sync_set_password(db, user, new_password)
    # Security confirmation to the account holder.
    try:
        await auth_emails.send_password_changed_email(db, user, client=client)
    except Exception as e:  # noqa: BLE001
        logger.error("password_changed_email_failed", user_id=user.id, error=str(e))


async def request_password_reset(
    db: AsyncSession,
    *,
    identifier: str,
    reset_type: str,
    client: ClientInfo | None = None,
) -> dict:
    """Create a reset code/link and deliver it by email.

    Returns a uniform payload regardless of whether the account exists; in
    DEBUG the generated code/token are echoed so dev stacks need no mailbox.
    """
    result = await password_reset.request_password_reset(
        db, identifier=identifier, reset_type=reset_type, client=client
    )
    payload: dict = {
        "sent": result.sent,
        "email": result.email,
        "masked_email": result.masked_email,
        "expires_at": result.expires_at,
    }
    if settings.DEBUG:
        payload["debug_code"] = result.debug_code
        payload["debug_token"] = result.debug_token
    return payload


async def reset_password(
    db: AsyncSession,
    *,
    identifier: str,
    token_or_code: str,
    new_password: str,
    client: ClientInfo | None = None,
) -> None:
    await password_reset.reset_password(
        db,
        identifier=identifier,
        token_or_code=token_or_code,
        new_password=new_password,
        client=client,
    )


# ── Authentik JIT provisioning ───────────────────────────────────────────────

async def provision_from_authentik(db: AsyncSession, claims: dict) -> User:
    """Resolve an Authentik token to a local user, creating one on first sight.

    Linking: external_id <- Authentik `sub`; falls back to email match for
    users that pre-existed Authentik (and back-fills external_id).

    JIT provisioning runs BEFORE the request is bound to a tenant/organization
    (``deps._bind_tenancy`` needs the user this returns), so the new row has no
    organization context to be stamped from — and ``users.organization_id`` is
    NOT NULL. ``resolve_user_organization`` supplies the default tenant's root
    organization, exactly as unauthenticated registration does.
    """
    sub = str(claims["sub"])
    user = await crud.get_by_external_id(db, sub)
    if user is None and claims.get("email"):
        user = await crud.get_by_email(db, claims["email"])
        if user and not user.external_id:
            user.external_id = sub

    if user is None:
        where = await resolve_user_organization(db)
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
            "tenant_id": where.tenant_id,
            "organization_id": where.organization_id,
        })
        await audit(db, Event.PROVISIONED, user=user, context={"method": "authentik", "sub": sub})

    if user.is_deactivated or user.deleted_at is not None:
        raise ForbiddenError("Account is deactivated")
    user.last_login = datetime.now(UTC)
    await db.flush()
    return user


async def get_or_create_dev_user(db: AsyncSession, email: str = "dev@local.test") -> User:
    """The real user row behind ``POST /api/auth/dev-token`` (DEBUG stacks only).

    A token subject must be a numeric user id, so the dev token needs a real
    row — and that row is organization-scoped like every other user. Lives in
    the service layer, not the route, so the organization is resolved by the
    same function every other creation path uses.
    """
    user = await crud.get_by_email(db, email)
    if user is not None:
        return user
    where = await resolve_user_organization(db)
    return await crud.create(db, {
        "email": email,
        "username": email.split("@")[0],
        "name": "Dev Token User",
        "password": hash_password(secrets.token_urlsafe(24)),   # unusable for login
        "tenant_id": where.tenant_id,
        "organization_id": where.organization_id,
    })


# ── User CRUD lifecycle ───────────────────────────────────────────────────────

async def list_users(db: AsyncSession, filters: UserListFilters) -> tuple[list[User], int]:
    return await crud.list_users(db, **filters.model_dump())


async def get_user(db: AsyncSession, user_id: int, *, include_deleted: bool = False) -> User:
    user = await crud.get_by_id(db, user_id, include_deleted=include_deleted)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user


async def create_user(
    db: AsyncSession,
    body: UserCreate,
    *,
    created_by: int | None = None,
    actor_label: str | None = None,
) -> User:
    if await crud.get_by_email(db, body.email, include_deleted=True):
        raise ConflictError("A user with this email already exists")
    if body.username and await crud.get_by_username(db, body.username):
        raise ConflictError("This username is taken")
    validate_password(body.password, email=body.email, name=body.name)

    values = body.model_dump(exclude_unset=True, exclude_none=True)
    values["email"] = body.email.lower()
    values["password"] = hash_password(values.pop("password"))
    values["created_by"] = created_by
    values["last_password_change_at"] = datetime.now(UTC)
    # Admin-create runs inside a bound request, so this normally returns the
    # caller's own organization; the fallbacks only matter for a system caller.
    values["organization_id"] = (await resolve_user_organization(db)).organization_id
    user = await crud.create(db, values)
    await audit(
        db, Event.USER_CREATED, user=user, actor_id=created_by, actor_label=actor_label,
        context={"created_by": created_by},
    )

    # Mirror into Authentik (best-effort). Plaintext is only available here.
    result = await authentik_sync.sync_create(db, user, body.password)
    if result is SyncResult.FAILED:
        _enqueue_authentik("provision_user", user.id)
    return user


async def update_user(
    db: AsyncSession,
    user_id: int,
    body: UserUpdate,
    *,
    updated_by: int | None = None,
    actor_label: str | None = None,
    client: ClientInfo | None = None,
) -> User:
    user = await get_user(db, user_id)

    values = body.model_dump(exclude_unset=True)
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
    # Apply, capture a masked {field: {old,new}} diff *before* flushing (history
    # is reset by flush), then persist the change.
    crud.apply_values(user, values)
    diff = model_changes(user, exclude={"updated_by"})
    await db.flush()
    await db.refresh(user)

    if diff:
        await audit(
            db, Event.USER_UPDATED, user=user, actor_id=updated_by, actor_label=actor_label,
            client=client, changes=diff, context={"fields": sorted(diff.keys())},
        )

    # Mirror profile changes into Authentik only when a synced field changed.
    changed = AUTHENTIK_SYNCED_FIELDS & set(values.keys())
    if changed:
        result = await authentik_sync.sync_update_profile(db, user, changed)
        if result is SyncResult.FAILED:
            _enqueue_authentik("sync_profile", user.id, sorted(changed))
    return user


async def delete_user(
    db: AsyncSession,
    user_id: int,
    *,
    deleted_by: int | None = None,
    hard: bool = False,
    actor_label: str | None = None,
) -> None:
    user = await get_user(db, user_id, include_deleted=hard)
    if hard:
        authentik_pk = user.authentik_pk  # capture before the row is removed
        # Audit first: hard delete removes the subject row (audit is append-only).
        await audit(
            db, Event.USER_HARD_DELETED, user=user, actor_id=deleted_by, actor_label=actor_label,
            context={"authentik_pk": authentik_pk},
        )
        await crud.hard_delete(db, user)
        if authentik_pk:
            result = await authentik_sync.sync_delete(authentik_pk)
            if result is SyncResult.FAILED:
                _enqueue_authentik("delete_user", authentik_pk)
    else:
        await crud.soft_delete(db, user, deleted_by=deleted_by)
        await audit(db, Event.USER_DELETED, user=user, actor_id=deleted_by, actor_label=actor_label)
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
    await audit(db, Event.USER_RESTORED, user=user)

    # Reactivate the Authentik account that the soft delete disabled.
    result = await authentik_sync.sync_set_active(db, user, True)
    if result is SyncResult.FAILED:
        _enqueue_authentik("sync_status", user.id, True)
    return user


async def logout(db: AsyncSession, user: User, *, client: ClientInfo | None = None) -> None:
    """Close the session (client drops its tokens) and audit the event.

    Tokens are stateless JWTs; this marks the in-app presence flag and records
    ``auth.logout``. See the audit plan doc for server-side token revocation.
    """
    user.has_active_session = False
    await db.flush()
    await audit(db, Event.LOGOUT, user=user, client=client)


# ── Location telemetry ────────────────────────────────────────────────────────

async def record_location(
    db: AsyncSession, user: User, body: LocationUpdate, *, client: ClientInfo | None = None,
) -> Any:
    """Record one position fix: upsert the live row, append to the history.

    Both writes happen in the caller's transaction, so a fix is either fully
    recorded or not at all — dispatch reading `user_live_locations` can never
    see a position that has no corresponding ping.

    The `users` row is NOT touched (that isolation is the reason the telemetry
    tables exist), with one exception: `is_location_set` is the flag the apps
    read to decide whether to ask for a location, and it belongs to the user.
    """
    recorded_at = body.recorded_at or datetime.now(UTC)
    coordinates = crud.point(body.latitude, body.longitude)

    live_values: dict[str, Any] = {
        "coordinates": coordinates,
        "recorded_at": recorded_at,
        "received_at": datetime.now(UTC),
    }
    # Only what the device actually sent — see the ON CONFLICT set_ in crud.
    for field in (
        "place_id", "accuracy_m", "altitude_m", "altitude_accuracy_m", "heading_deg",
        "speed_mps", "location_source", "is_moving", "tracking_active",
        "background_tracking_enabled", "device_id", "device_type", "network_type",
    ):
        value = getattr(body, field)
        if value is not None:
            live_values[field] = value
    if client is not None and client.ip:
        live_values["ip_address"] = client.ip

    live = await crud.upsert_live_location(db, user=user, values=live_values)
    await crud.record_location_ping(db, user=user, values={
        "coordinates": coordinates,
        "recorded_at": recorded_at,
        "place_id": body.place_id,
        "accuracy_m": body.accuracy_m,
        "altitude_m": body.altitude_m,
        "heading_deg": body.heading_deg,
        "speed_mps": body.speed_mps,
        "location_source": body.location_source,
        "device_id": body.device_id,
    })

    if not user.is_location_set:
        user.is_location_set = True
    await db.flush()
    logger.info(
        "users.location_recorded",
        user_id=user.id, source=body.location_source, accuracy_m=body.accuracy_m,
    )
    return live


async def get_live_location(db: AsyncSession, user_id: int) -> Any:
    """The user's last known position, or ``None`` if they never reported one."""
    return await crud.get_live_location(db, user_id)


async def refresh_primary_place(db: AsyncSession, user_id: int) -> int | None:
    """Re-point ``users.primary_place_id`` at the user's primary live address.

    ``primary_place_id`` is a CACHE of the address book, kept so a user list can
    show a place without joining `geo`. This is the ONE function that writes it;
    the geo address service calls it whenever a user's links change, so the two
    can only disagree for the length of a transaction.
    """
    place_id = await db.scalar(text(
        "SELECT place_id FROM geo.place_links "
        "WHERE owner_type = 'user' AND owner_id = :user_id "
        "  AND is_primary AND valid_to IS NULL AND deleted_at IS NULL "
        "ORDER BY updated_at DESC LIMIT 1"
    ), {"user_id": user_id})
    user = await crud.get_by_id(db, user_id)
    if user is not None and user.primary_place_id != place_id:
        user.primary_place_id = place_id
        await db.flush()
    return place_id


# ── Profile & Localization (auto-unless-overridden) ───────────────────────────

async def get_or_create_profile(
    db: AsyncSession,
    user_id: int,
    initial_country: str | None = None,
    initial_timezone: str | None = None,
) -> UserProfile:
    """Retrieve existing UserProfile or initialize with detected or default localization.

    Defaults are only applied when the referenced country/timezone actually
    exists in the (global) reference tables, so a registration never fails on a
    foreign key just because the reference data has not been seeded.
    """
    stmt = select(UserProfile).where(UserProfile.user_id == user_id)
    profile = await db.scalar(stmt)
    if profile is None:
        country_iso2 = initial_country or "IN"
        if not await db.scalar(select(Country.iso2).where(Country.iso2 == country_iso2)):
            country_iso2 = None
        tz_name = initial_timezone or "Asia/Kolkata"
        if not await db.scalar(select(Timezone.iana_name).where(Timezone.iana_name == tz_name)):
            tz_name = None
        profile = UserProfile(
            user_id=user_id,
            country_iso2=country_iso2,
            timezone_name=tz_name,
            timezone_source=TimezoneSource.auto,
        )
        db.add(profile)
        await db.flush()
        await db.refresh(profile)
    return profile


async def set_user_country(db: AsyncSession, profile: UserProfile, country_iso2: str) -> UserProfile:
    """Update user country; auto-fills default timezone if timezone_source is 'auto'."""
    iso2 = country_iso2.strip().upper()
    country = await db.scalar(select(Country).where(Country.iso2 == iso2))
    if not country:
        raise NotFoundError(f"Country with ISO2 code '{iso2}' not found")

    profile.country_iso2 = iso2

    if profile.timezone_source == TimezoneSource.auto:
        default_tz = await db.scalar(
            select(CountryTimezone.timezone_name)
            .where(CountryTimezone.country_iso2 == iso2)
            .where(CountryTimezone.is_default.is_(True))
        )
        if default_tz:
            profile.timezone_name = default_tz

    user = await crud.get_by_id(db, profile.user_id)
    if user:
        user.country_code = country.iso2
        if profile.timezone_name:
            user.timezone = profile.timezone_name
        if country.currency_code:
            user.currency = country.currency_code

    await db.flush()
    return profile


async def set_user_timezone_manually(db: AsyncSession, profile: UserProfile, timezone_name: str) -> UserProfile:
    """Manually set user timezone, permanently locking timezone_source to 'manual'."""
    tz_name = timezone_name.strip()
    tz_exists = await db.scalar(select(Timezone.iana_name).where(Timezone.iana_name == tz_name))
    if not tz_exists:
        raise NotFoundError(f"Timezone '{tz_name}' not found in reference database")

    profile.timezone_name = tz_name
    profile.timezone_source = TimezoneSource.manual

    user = await crud.get_by_id(db, profile.user_id)
    if user:
        user.timezone = tz_name

    await db.flush()
    return profile


async def update_user_profile(
    db: AsyncSession, user: User, body: UserProfileUpdate
) -> UserProfile:
    """Update user profile country and/or timezone."""
    profile = await get_or_create_profile(db, user.id)
    if body.country:
        profile = await set_user_country(db, profile, body.country)
    if body.timezone:
        profile = await set_user_timezone_manually(db, profile, body.timezone)
    await db.commit()
    await db.refresh(profile)
    return profile


# ── Reference Data Caching (L1 In-Memory + L2 Redis DB 0) ────────────────────

_L1_CACHE: dict[str, tuple[float, Any]] = {}
_L1_TTL_SECONDS = 3600  # 1 hour in-process TTL


def _get_l1(key: str) -> Any | None:
    if key in _L1_CACHE:
        expires_at, val = _L1_CACHE[key]
        if time.monotonic() < expires_at:
            return val
        del _L1_CACHE[key]
    return None


def _set_l1(key: str, val: Any, ttl: float = _L1_TTL_SECONDS) -> None:
    _L1_CACHE[key] = (time.monotonic() + ttl, val)


def invalidate_l1_cache() -> None:
    _L1_CACHE.clear()


async def get_cached_countries(db: AsyncSession) -> list[dict]:
    """Retrieve list of active countries (L1 Memory -> L2 Redis -> DB)."""
    cache_key = "ref:countries:all"
    l1_val = _get_l1(cache_key)
    if l1_val is not None:
        return l1_val

    try:
        from app.database.redis import redis_client
        cached_redis = await redis_client.get(cache_key)
        if cached_redis:
            data = json.loads(cached_redis)
            _set_l1(cache_key, data)
            return data
    except Exception as e:
        logger.warning("redis_cache_get_failed", key=cache_key, error=str(e))

    stmt = select(Country).where(Country.is_active.is_(True)).order_by(Country.name)
    rows = (await db.scalars(stmt)).all()
    data = [
        {
            "iso2": c.iso2,
            "iso3": c.iso3,
            "numeric_code": c.numeric_code,
            "name": c.name,
            "official_name": c.official_name,
            "region": c.region,
            "subregion": c.subregion,
            "phone_code": c.phone_code,
            "currency_code": c.currency_code,
            "is_active": c.is_active,
        }
        for c in rows
    ]

    _set_l1(cache_key, data)
    try:
        from app.database.redis import redis_client
        await redis_client.set(cache_key, json.dumps(data), ex=86400)
    except Exception as e:
        logger.warning("redis_cache_set_failed", key=cache_key, error=str(e))

    return data


async def get_cached_country_timezones(db: AsyncSession, country_iso2: str) -> list[dict]:
    """Retrieve timezones for a given country (L1 Memory -> L2 Redis -> DB)."""
    iso2 = country_iso2.strip().upper()
    cache_key = f"ref:country_tz:{iso2}"

    l1_val = _get_l1(cache_key)
    if l1_val is not None:
        return l1_val

    try:
        from app.database.redis import redis_client
        cached_redis = await redis_client.get(cache_key)
        if cached_redis:
            data = json.loads(cached_redis)
            _set_l1(cache_key, data)
            return data
    except Exception as e:
        logger.warning("redis_cache_get_failed", key=cache_key, error=str(e))

    stmt = (
        select(CountryTimezone)
        .where(CountryTimezone.country_iso2 == iso2)
        .order_by(CountryTimezone.is_default.desc(), CountryTimezone.timezone_name)
    )
    rows = (await db.scalars(stmt)).all()
    data = [
        {"timezone_name": r.timezone_name, "is_default": r.is_default}
        for r in rows
    ]

    _set_l1(cache_key, data)
    try:
        from app.database.redis import redis_client
        await redis_client.set(cache_key, json.dumps(data), ex=86400)
    except Exception as e:
        logger.warning("redis_cache_set_failed", key=cache_key, error=str(e))

    return data


async def invalidate_reference_cache() -> None:
    """Clear both L1 in-memory and L2 Redis reference cache keys."""
    invalidate_l1_cache()
    try:
        from app.database.redis import redis_client
        keys = await redis_client.keys("ref:*")
        if keys:
            await redis_client.delete(*keys)
    except Exception as e:
        logger.warning("redis_cache_invalidation_failed", error=str(e))
