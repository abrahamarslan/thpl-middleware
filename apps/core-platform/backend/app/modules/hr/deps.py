"""Resource-level targets for employment routes (``Perm(code, target=…)``).

An employment record is judged AT its organization and department, so a department-scoped grant
covers the people in that department and nobody else.
"""

from __future__ import annotations

from app.database.db import DBSession
from app.modules.hr import service
from app.modules.rbac.engine import Target


async def employment_target(db: DBSession, record_id: int) -> Target:
    row = await service.get_employment(db, record_id)
    return Target(organization_id=row.organization_id, department_id=row.department_id)
