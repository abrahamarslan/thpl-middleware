"""Tenants business logic (platform scope).

Tenants are the isolation root, so this service works in SYSTEM scope
(``all_tenants``): a platform admin manages every tenant. Everything a tenant
OWNS is managed inside that tenant's scope by its own admins.
"""

from __future__ import annotations

import uuid

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
    values = body.model_dump(exclude={"root_organization_name", "root_organization_code"}, exclude_none=True)
    values["status"] = body.status.value
    tenant = Tenant(**values)
    db.add(tenant)
    await db.flush()

    if body.root_organization_name:
        from app.modules.organizations import service as org_service
        from app.modules.organizations.schema import OrganizationCreate

        with tenant_scope(tenant.id):
            await org_service.create_organization(
                db,
                OrganizationCreate(
                    org_code=body.root_organization_code or body.tenant_code,
                    legal_name=body.root_organization_name,
                    org_type=OrganizationType.LEGAL_ENTITY,
                ),
                actor_id=actor_id,
            )
    await record_activity(
        db, action="tenant_created", actor_id=actor_id, subject_type="Tenant", subject_id=tenant.id,
        changes={"after": {"tenant_code": tenant.tenant_code, "status": tenant.status}},
    )
    logger.info("tenants.created", tenant_id=tenant.id, code=tenant.tenant_code)
    return tenant


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
