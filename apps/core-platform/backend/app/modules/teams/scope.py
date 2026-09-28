"""Which organization a new ``teams`` row belongs to, and this module's error code.

``organization_id`` is NOT NULL on every teams table, so a caller with no organization bound
would hit a raw IntegrityError. The resolution order lives in ``app/database/scope.py`` — one
implementation shared by every module; only the error CODE is this module's own.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError
from app.database import scope


class TeamsRuleError(AppError):
    status_code = 422
    code = "teams_rule_violation"


async def require_organization(db: AsyncSession) -> int:
    try:
        return await scope.require_organization_id(db)
    except scope.OrganizationRequiredError as exc:
        raise TeamsRuleError(exc.msg, data=exc.data) from exc


__all__ = ["TeamsRuleError", "require_organization"]
