"""Resource-level targets for teams routes — declared with ``Perm(code, target=…)``.

Each dependency loads the row named by the ``{ref}`` path parameter and returns the
:class:`Target` (organization + department/team) the permission is judged AT. That is what
lets a department head edit THEIR department (a department-scoped grant) and not the one next
door, and lets an administrator of branch A leave branch B's teams alone.
"""

from __future__ import annotations

from app.database.db import DBSession
from app.modules.rbac.engine import Target
from app.modules.teams import service


async def department_target(db: DBSession, ref: str) -> Target:
    dept = await service.get_department(db, ref)
    return Target(organization_id=dept.organization_id, department_id=dept.id)


async def job_title_target(db: DBSession, ref: str) -> Target:
    row = await service.get_job_title(db, ref)
    return Target(organization_id=row.organization_id, department_id=row.department_id)


async def team_type_target(db: DBSession, ref: str) -> Target:
    return Target(organization_id=(await service.get_team_type(db, ref)).organization_id)


async def team_role_target(db: DBSession, ref: str) -> Target:
    return Target(organization_id=(await service.get_team_role(db, ref)).organization_id)


async def team_ref_target(db: DBSession, ref: str) -> Target:
    return service.team_target(await service.get_team(db, ref))
