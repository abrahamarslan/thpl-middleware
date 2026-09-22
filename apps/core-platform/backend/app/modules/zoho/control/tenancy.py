"""Which tenant / organization the Zoho engine works for.

One Zoho connection per deployment (today): it belongs to the tenant
``ZOHO_TENANT_CODE`` (empty = the default tenant). Every sync run executes in
that tenant's scope with actor ``system:zoho-sync``.

**The organization is resolved, never left NULL.** In order:

1. the organization node whose ``zoho_id`` is ``ZOHO_ORGANIZATION_ID`` — the
   company's own row once the seeder has stamped it, or the node the
   organizations sync created;
2. the deployment's configured default (``DEFAULT_ORGANIZATION_CODE`` in that
   tenant), via ``app/database/scope.py``;
3. the tenant's only organization.

This closes redesign open decision #1 ("organization for Zoho *settings*
records"). Previously an unresolved node left ``organization_id`` NULL and the
run failed one record at a time with *"cannot place a synced currency: no
organization in context"* — because the canonical masters are org-scoped
(``organization_id`` NOT NULL) even though Zoho's ``/settings/*`` endpoints are
tenant-wide. Resolving to the configured default is the honest answer: a
deployment has one company, and that company is where its Zoho data belongs.

Raw SQL on purpose: the Zoho platform never imports a feature module
(.importlinter).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings
from app.database.tenancy import resolve_tenant_id, system_actor, tenant_scope

logger = structlog.get_logger("app.zoho.scope")


async def zoho_tenant(db: AsyncSession) -> tuple[int, int | None]:
    tenant_id = await resolve_tenant_id(db, settings.ZOHO_TENANT_CODE or None)
    organization_id = None
    if settings.ZOHO_ORGANIZATION_ID:
        organization_id = await db.scalar(
            text("SELECT id FROM org_management.organizations "
                 "WHERE tenant_id = :t AND zoho_id = :z AND deleted_at IS NULL LIMIT 1"),
            {"t": tenant_id, "z": settings.ZOHO_ORGANIZATION_ID},
        )
    if organization_id is None:
        # Before the first organizations sync there is no zoho_id node yet, and
        # the org-scoped masters cannot wait for it. Fall back to the same
        # default every other unattributed write uses.
        from app.database import scope

        fallback = await scope.configured_default(db) or await scope.sole_organization(db, tenant_id)
        if fallback is not None and fallback.tenant_id == tenant_id:
            organization_id = fallback.organization_id
            logger.info("zoho.scope.default_organization", tenant_id=tenant_id,
                        organization_id=organization_id, org_code=fallback.org_code,
                        zoho_organization_id=settings.ZOHO_ORGANIZATION_ID or None)
    return tenant_id, organization_id


@asynccontextmanager
async def zoho_scope(db: AsyncSession, component: str = "zoho-sync") -> AsyncIterator[tuple[int, int | None]]:
    tenant_id, organization_id = await zoho_tenant(db)
    with tenant_scope(tenant_id, organization_id, system_actor(component)):
        yield tenant_id, organization_id
