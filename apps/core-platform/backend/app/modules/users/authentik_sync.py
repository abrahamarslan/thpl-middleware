"""Authentik synchronisation orchestration (app -> Authentik).

Bridges the user service layer to the Authentik admin client. One coroutine per
lifecycle event. These functions are **best-effort and never raise**: a failure
is logged, recorded on the user row (``authentik_sync_status`` / ``_error``),
and reported via the returned :class:`SyncResult` so the caller can enqueue a
Celery retry. A failed Authentik sync must never roll back the local write — the
local users table is the source of truth.

Field mapping (local ``User`` -> Authentik)
-------------------------------------------
  username       -> username   (Authentik requires a unique username)
  first/last_name-> name        (Authentik has a single ``name`` field)
  email          -> email
  phone          -> attributes.phone
  is_deactivated -> is_active   (inverted)

Password note (Option A login model)
------------------------------------
First-party login verifies against local bcrypt, NOT Authentik. So an Authentik
password that fails to sync (``password_drift``) never blocks app login — it only
affects native Authentik / other-SSO logins, recoverable via a password reset.
Plaintext passwords exist only in the request scope, so password sync cannot be
retried by Celery; on failure we flag drift and move on.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from enum import Enum

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.security.authentik_client import (
    AuthentikAdminClient,
    AuthentikError,
    authentik_admin_client,
)
from app.core.conf import settings
from app.modules.users.model import User

logger = structlog.get_logger("app.users.authentik_sync")


class SyncResult(str, Enum):
    OK = "ok"            # synced successfully
    SKIPPED = "skipped"  # sync disabled, or nothing to do (no authentik_pk yet)
    FAILED = "failed"    # call failed — caller should enqueue a retry


# Local field names that, when changed, require a profile push to Authentik.
AUTHENTIK_SYNCED_FIELDS: frozenset[str] = frozenset(
    {"username", "first_name", "last_name", "name", "email", "phone", "is_deactivated", "is_banned"}
)


# ── Field mapping helpers ─────────────────────────────────────────────────────

def _authentik_username(user: User) -> str:
    # Authentik requires a unique, non-empty username. email is unique in our DB.
    return user.username or user.email


def _authentik_name(user: User) -> str:
    full = " ".join(p for p in (user.first_name, user.last_name) if p).strip()
    return full or user.name or user.username or user.email


def _authentik_attributes(user: User) -> dict:
    attrs: dict = {"local_user_id": user.id}
    if user.phone:
        attrs["phone"] = user.phone
    return attrs


def _is_active(user: User) -> bool:
    if user.is_deactivated or user.deleted_at is not None:
        return False
    if user.is_banned:
        # An expired temporary ban is no longer in force.
        if user.banned_until is not None and datetime.now(UTC) >= user.banned_until:
            return True
        return False
    return True


def _mark(user: User, status: str, error: str | None = None) -> None:
    user.authentik_sync_status = status
    user.authentik_sync_error = (error or None) and error[:500]
    if status == "synced":
        user.authentik_synced_at = datetime.now(UTC)
        user.authentik_sync_error = None


def link_existing(user: User, authentik_user: dict) -> None:
    """Link a local user to an already-existing Authentik user (backfill path)."""
    user.authentik_pk = str(authentik_user["pk"])
    if authentik_user.get("uuid") and not user.external_id:
        user.external_id = str(authentik_user["uuid"])
    _mark(user, "synced")


def _profile_patch(user: User, changed_fields: set[str]) -> dict:
    """Build the Authentik PATCH body from the set of changed local fields."""
    patch: dict = {}
    if {"username"} & changed_fields:
        patch["username"] = _authentik_username(user)
    if {"first_name", "last_name", "name"} & changed_fields:
        patch["name"] = _authentik_name(user)
    if "email" in changed_fields:
        patch["email"] = user.email
    if "phone" in changed_fields:
        patch["attributes"] = _authentik_attributes(user)
    if "is_deactivated" in changed_fields or "is_banned" in changed_fields:
        patch["is_active"] = _is_active(user)
    return patch


# ── Lifecycle operations ──────────────────────────────────────────────────────

async def sync_create(
    db: AsyncSession,
    user: User,
    plain_password: str | None,
    *,
    client: AuthentikAdminClient | None = None,
) -> SyncResult:
    """Provision the user in Authentik and store the returned pk/uuid locally.

    ``plain_password`` may be None (Celery fallback path): a random unusable
    password is set and the row is flagged ``password_drift`` so the user must
    reset to gain native-Authentik access (local app login is unaffected).
    """
    if not settings.AUTHENTIK_SYNC_ENABLED:
        _mark(user, "skipped")
        return SyncResult.SKIPPED

    ak = client or authentik_admin_client
    try:
        created = await ak.create_user(
            username=_authentik_username(user),
            name=_authentik_name(user),
            email=user.email,
            is_active=_is_active(user),
            attributes=_authentik_attributes(user),
        )
        user.authentik_pk = str(created["pk"])
        # Keep the reverse OIDC link consistent: when the Authentik OIDC provider's
        # subject mode is "Based on the User's UUID", the inbound `sub` equals this.
        if created.get("uuid") and not user.external_id:
            user.external_id = str(created["uuid"])
    except Exception as e:  # noqa: BLE001 — never raise into the request
        logger.error("authentik_create_failed", user_id=user.id, error=str(e))
        _mark(user, "failed", str(e))
        return SyncResult.FAILED

    # User now exists in Authentik; password is a separate (recoverable) concern.
    password = plain_password or secrets.token_urlsafe(32)
    try:
        await ak.set_password(user.authentik_pk, password)
    except Exception as e:  # noqa: BLE001
        logger.error("authentik_set_password_failed", user_id=user.id, error=str(e))
        _mark(user, "password_drift", str(e))
        return SyncResult.OK if plain_password is None else SyncResult.FAILED

    _mark(user, "password_drift" if plain_password is None else "synced")
    logger.info("authentik_user_synced", user_id=user.id, authentik_pk=user.authentik_pk)
    return SyncResult.OK


async def sync_update_profile(
    db: AsyncSession,
    user: User,
    changed_fields: set[str],
    *,
    client: AuthentikAdminClient | None = None,
) -> SyncResult:
    if not settings.AUTHENTIK_SYNC_ENABLED:
        return SyncResult.SKIPPED
    if not user.authentik_pk:
        # Not yet provisioned — backfill/registration owns creation.
        logger.warning("authentik_update_skipped_no_pk", user_id=user.id)
        return SyncResult.SKIPPED

    patch = _profile_patch(user, set(changed_fields))
    if not patch:
        return SyncResult.SKIPPED

    ak = client or authentik_admin_client
    try:
        await ak.update_user(user.authentik_pk, **patch)
    except Exception as e:  # noqa: BLE001
        logger.error("authentik_update_failed", user_id=user.id, error=str(e))
        _mark(user, "failed", str(e))
        return SyncResult.FAILED

    _mark(user, "synced")
    logger.info("authentik_profile_synced", user_id=user.id, fields=sorted(patch))
    return SyncResult.OK


async def sync_set_password(
    db: AsyncSession,
    user: User,
    new_plain_password: str,
    *,
    client: AuthentikAdminClient | None = None,
) -> SyncResult:
    if not settings.AUTHENTIK_SYNC_ENABLED:
        return SyncResult.SKIPPED
    if not user.authentik_pk:
        logger.warning("authentik_password_skipped_no_pk", user_id=user.id)
        return SyncResult.SKIPPED

    ak = client or authentik_admin_client
    try:
        await ak.set_password(user.authentik_pk, new_plain_password)
    except Exception as e:  # noqa: BLE001
        logger.error("authentik_password_failed", user_id=user.id, error=str(e))
        _mark(user, "password_drift", str(e))
        return SyncResult.FAILED

    _mark(user, "synced")
    logger.info("authentik_password_synced", user_id=user.id)
    return SyncResult.OK


async def sync_set_active(
    db: AsyncSession,
    user: User,
    is_active: bool,
    *,
    client: AuthentikAdminClient | None = None,
) -> SyncResult:
    if not settings.AUTHENTIK_SYNC_ENABLED:
        return SyncResult.SKIPPED
    if not user.authentik_pk:
        logger.warning("authentik_active_skipped_no_pk", user_id=user.id)
        return SyncResult.SKIPPED

    ak = client or authentik_admin_client
    try:
        await ak.set_active(user.authentik_pk, is_active)
    except Exception as e:  # noqa: BLE001
        logger.error("authentik_set_active_failed", user_id=user.id, error=str(e))
        _mark(user, "failed", str(e))
        return SyncResult.FAILED

    _mark(user, "synced")
    logger.info("authentik_active_synced", user_id=user.id, is_active=is_active)
    return SyncResult.OK


async def sync_delete(
    authentik_pk: str,
    *,
    client: AuthentikAdminClient | None = None,
) -> SyncResult:
    """Hard-delete in Authentik. Caller passes the pk captured before the local
    row was removed. Idempotent (404 is treated as success)."""
    if not settings.AUTHENTIK_SYNC_ENABLED or not authentik_pk:
        return SyncResult.SKIPPED

    ak = client or authentik_admin_client
    try:
        await ak.delete_user(authentik_pk)
    except Exception as e:  # noqa: BLE001
        logger.error("authentik_delete_failed", authentik_pk=authentik_pk, error=str(e))
        return SyncResult.FAILED

    logger.info("authentik_user_deleted", authentik_pk=authentik_pk)
    return SyncResult.OK
