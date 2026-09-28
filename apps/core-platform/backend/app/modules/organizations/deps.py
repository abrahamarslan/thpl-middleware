"""Resource-level targets for organization routes (``Perm(code, target=…)``).

* acting on an organization is judged AT that organization (an administrator of one branch cannot
  rename, move or archive another);
* CREATING one is judged at its PARENT — and a new ROOT organization is a tenant-level act that only a
  tenant-wide grant covers ("anything in the tenant, including creating new organizations").
"""

from __future__ import annotations

from fastapi import Request

from app.database.db import DBSession
from app.modules.organizations import service
from app.modules.rbac.engine import Target


async def organization_target(db: DBSession, ref: str) -> Target:
    org = await service.get_organization(db, ref)
    return Target(organization_id=org.id)


async def organization_move_target(request: Request, db: DBSession, ref: str) -> list[Target]:
    """Moving needs authority over the node AND over where it lands."""
    node = await organization_target(db, ref)
    return [node, await organization_create_target(request, db)]


async def organization_create_target(request: Request, db: DBSession) -> Target:
    """The parent named in the request body (``parent``: uuid or code), else the tenant itself."""
    try:
        body = await request.json()
    except ValueError:
        body = {}
    parent = body.get("parent") if isinstance(body, dict) else None
    if not parent:
        return Target(tenant_level=True)
    org = await service.get_organization(db, parent)
    return Target(organization_id=org.id)
