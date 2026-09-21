"""Which tenant / organization the Zoho engine works for.

One Zoho connection per deployment (today): it belongs to the tenant
``ZOHO_TENANT_CODE`` (empty = the default tenant). Every sync run executes in
that tenant's scope with actor ``system:zoho-sync``, and mirror rows are
attached to the organization node whose ``zoho_id`` is
``ZOHO_ORGANIZATION_ID`` (created by the organizations module's own sync; until
then mirror rows are tenant-wide).

Raw SQL on purpose: the Zoho platform never imports a feature module
(.importlinter).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings
from app.database.tenancy import resolve_tenant_id, system_actor, tenant_scope


async def zoho_tenant(db: AsyncSession) -> tuple[int, int | None]:
    tenant_id = await resolve_tenant_id(db, settings.ZOHO_TENANT_CODE or None)
    organization_id = None
    if settings.ZOHO_ORGANIZATION_ID:
        organization_id = await db.scalar(
            text("SELECT id FROM org_management.organizations "
                 "WHERE tenant_id = :t AND zoho_id = :z AND deleted_at IS NULL LIMIT 1"),
            {"t": tenant_id, "z": settings.ZOHO_ORGANIZATION_ID},
        )
    return tenant_id, organization_id


@asynccontextmanager
async def zoho_scope(db: AsyncSession, component: str = "zoho-sync") -> AsyncIterator[tuple[int, int | None]]:
    tenant_id, organization_id = await zoho_tenant(db)
    with tenant_scope(tenant_id, organization_id, system_actor(component)):
        yield tenant_id, organization_id
