"""Tenants business logic (platform scope).

Tenants are the isolation root, so this service works in SYSTEM scope
(``all_tenants``): a platform admin manages every tenant. Everything a tenant
OWNS is managed inside that tenant's scope by its own admins.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.database.tenancy import tenant_scope
from app.modules.activity.recorder import record_activity
from app.modules.tenants.enums import OrganizationType, TenantStatus
from app.modules.tenants.model import Tenant
from app.modules.tenants.schema import TenantCreate, TenantStatusChange, TenantUpdate

logger = structlog.get_logger("app.tenants")


async def list_tenants(db: AsyncSession, *, status: str | None = None) -> list[Tenant]:
    stmt = select(Tenant).order_by(Tenant.tenant_code)
    if status:
        stmt = stmt.where(Tenant.status == status)
    return list((await db.scalars(stmt)).all())


async def get_tenant(db: AsyncSession, ref: str | int) -> Tenant:
    """By id, uuid or tenant_code."""
    ref = str(ref)
    stmt = select(Tenant)
    if ref.isdigit():
        stmt = stmt.where(Tenant.id == int(ref))
    else:
        try:
            stmt = stmt.where(Tenant.uuid == uuid.UUID(ref))
        except ValueError:
            stmt = stmt.where(Tenant.tenant_code == ref)
    tenant = await db.scalar(stmt.limit(1))
    if tenant is None:
        raise NotFoundError(f"Tenant '{ref}' not found")
    return tenant


async def create_tenant(db: AsyncSession, body: TenantCreate, *, actor_id: int | None) -> Tenant:
    exists = await db.scalar(select(Tenant.id).where(Tenant.tenant_code == body.tenant_code))
    if exists:
        raise ConflictError(f"Tenant code '{body.tenant_code}' is already in use")
    admin_email = str(body.admin_email or body.primary_contact_email).lower()
    from app.modules.users import crud as users_crud

    if await users_crud.get_by_email(db, admin_email, include_deleted=True):
        # Email is globally unique (sign-in needs no tenant picker), so the administrator's must be free.
        raise ConflictError(f"A user with the email '{admin_email}' already exists; choose another admin_email")
    if body.admin_password is not None:
        # Refuse a weak password BEFORE anything is created, not after the tenant and organization exist.
        from app.modules.users.password_policy import validate_password

        validate_password(body.admin_password, email=admin_email, name=body.admin_name or "Administrator")

    values = body.model_dump(
        exclude={"root_organization_name", "root_organization_code", "admin_email", "admin_name", "admin_password"},
        exclude_none=True,
    )
    values["status"] = body.status.value
    tenant = Tenant(**values)
    db.add(tenant)
    await db.flush()

    # A tenant is never empty: it always gets its root organization (whose creation seeds the system roles)
    # and an initial administrator who can do anything in it — including creating further organizations.
    from app.modules.organizations import service as org_service
    from app.modules.organizations.schema import OrganizationCreate

    with tenant_scope(tenant.id):
        org = await org_service.create_organization(
            db,
            OrganizationCreate(
                org_code=body.root_organization_code or body.tenant_code,
                legal_name=body.root_organization_name or body.name,
                org_type=OrganizationType.LEGAL_ENTITY,
            ),
            actor_id=actor_id,
        )
        tenant.initial_admin = await _create_initial_admin(db, tenant, org, body, email=admin_email)
    await record_activity(
        db, action="tenant_created", actor_id=actor_id, subject_type="Tenant", subject_id=tenant.id,
        changes={"after": {"tenant_code": tenant.tenant_code, "status": tenant.status}},
    )
    logger.info("tenants.created", tenant_id=tenant.id, code=tenant.tenant_code)
    return tenant


def _temporary_password(email: str, name: str) -> str:
    """A strong password that satisfies the platform's own policy (checked, not assumed)."""
    from app.modules.users.password_policy import validate_password

    for _ in range(10):
        candidate = f"{secrets.token_urlsafe(12)}Aa1!"
        try:
            validate_password(candidate, email=email, name=name)
            return candidate
        except Exception:  # noqa: BLE001 — try another; the policy is stricter than any fixed recipe
            continue
    raise RuntimeError("could not generate a password satisfying the password policy")


async def _create_initial_admin(db: AsyncSession, tenant: Tenant, org: Any, body: TenantCreate, *, email: str) -> dict:
    """The tenant's first administrator: ``owner`` of the root organization + the tenant-wide owner grant."""
    from app.modules.rbac import service as rbac_service
    from app.modules.roles.model import Role
    from app.modules.users import service as users_service
    from app.modules.users.model import User
    from app.modules.users.security import hash_password

    owner = await db.scalar(select(Role).where(Role.organization_id == org.id, Role.code == "owner"))
    if owner is None:                                     # cannot happen: organization creation seeds it
        raise RuntimeError(f"organization {org.org_code} has no owner role")
    name = body.admin_name or "Administrator"
    generated = body.admin_password is None
    password = body.admin_password or _temporary_password(email, name)    # a supplied one was validated up front
    now = datetime.now(UTC)
    user = User(
        name=name, email=email, password=hash_password(password), role_id=owner.id, organization_id=org.id,
        tenant_id=tenant.id, user_type="admin", status="active", user_status="active", is_verified=True,
        email_verified_at=now, last_password_change_at=now, timezone=tenant.timezone, language="en",
    )
    db.add(user)
    await db.flush()
    tenant.primary_user_id = user.id
    await rbac_service.ensure_tenant_owner(db, user, owner)
    await record_activity(
        db, action="tenant_admin_created", actor_id=None, subject_type="Tenant", subject_id=tenant.id,
        changes={"after": {"admin_user_id": user.id, "email": email, "organization": org.org_code}},
    )
    # Mirror into Authentik best-effort, like every other user creation (plaintext is only in scope here).
    from app.modules.users import authentik_sync

    if await authentik_sync.sync_create(db, user, password) is authentik_sync.SyncResult.FAILED:
        users_service._enqueue_authentik("provision_user", user.id)   # noqa: SLF001
    # Flush now, still inside the caller's `with tenant_scope(tenant.id):` block: `sync_create` just
    # dirtied `user` (authentik_pk / authentik_sync_status), and a dirty row of THIS tenant flushed after
    # the scope reverts to the platform admin's OWN tenant trips the cross-tenant guard — it did, until
    # this line (a later `record_activity` autoflush was the one to trigger it, not obviously this call).
    await db.flush()
    return {
        "user_id": user.id, "email": email, "role": owner.code, "organization_code": org.org_code,
        "tenant_wide": True, "temporary_password": password if generated else None,
    }


async def update_tenant(db: AsyncSession, ref: str, body: TenantUpdate, *, actor_id: int | None) -> Tenant:
    tenant = await get_tenant(db, ref)
    _check_version(tenant.row_version, body.row_version)
    for field, value in body.model_dump(exclude_unset=True, exclude={"row_version"}).items():
        setattr(tenant, field, value)
    await db.flush()
    await record_activity(db, action="tenant_updated", actor_id=actor_id, subject_type="Tenant",
                          subject_id=tenant.id)
    return tenant


async def change_status(db: AsyncSession, ref: str, body: TenantStatusChange, *, actor_id: int | None) -> Tenant:
    tenant = await get_tenant(db, ref)
    before = tenant.status
    tenant.status = body.status.value
    await db.flush()
    _forget_status(tenant.id)
    await record_activity(
        db, action="tenant_status_changed", actor_id=actor_id, subject_type="Tenant", subject_id=tenant.id,
        changes={"before": {"status": before}, "after": {"status": tenant.status}},
        context={"reason": body.reason},
    )
    logger.warning("tenants.status_changed", tenant_id=tenant.id, before=before, after=tenant.status)
    return tenant


def _check_version(current: int, seen: int) -> None:
    if current != seen:
        raise ConflictError(
            f"The record changed since you loaded it (version {seen} → {current}); reload and retry",
            data={"current_row_version": current},
        )


# ── sign-in gate (used by get_current_user) ─────────────────────────────────

_status_cache: dict[int, tuple[float, str]] = {}
_STATUS_TTL = 30.0


def _forget_status(tenant_id: int) -> None:
    _status_cache.pop(tenant_id, None)


async def tenant_status(db: AsyncSession, tenant_id: int) -> str | None:
    """A tenant's status, cached 30 s per process (checked on every request)."""
    import time

    hit = _status_cache.get(tenant_id)
    if hit and time.monotonic() - hit[0] < _STATUS_TTL:
        return hit[1]
    status = await db.scalar(
        select(Tenant.status).where(Tenant.id == tenant_id).execution_options(include_deleted=True)
    )
    if status is not None:
        _status_cache[tenant_id] = (time.monotonic(), status)
    return status


def can_sign_in(status: str | None) -> bool:
    try:
        return status is not None and TenantStatus(status).can_sign_in
    except ValueError:
        return False
