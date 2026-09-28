"""Resource-level targets for role routes — declared with ``Perm(..., target=role_target)``.

A role belongs to one organization, so acting on it is judged AT that organization: an
administrator of branch A cannot edit branch B's roles, while one at the holding above
both can.
"""

from __future__ import annotations

from app.database.db import DBSession
from app.modules.rbac.engine import Target
from app.modules.roles import service


async def role_target(db: DBSession, ref: str) -> Target:
    role = await service.get_role(db, ref)
    return Target(organization_id=role.organization_id)
