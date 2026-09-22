"""Which organization a new ``core`` master-data row belongs to.

``core.brands`` / ``core.manufacturers`` (and their children) have
``organization_id`` NOT NULL, so a caller with no organization bound would hit a
raw IntegrityError. The resolution order lives in ``app/database/scope.py`` —
one implementation shared by every module. Only the error *code* is this
module's own, so an API client can still tell a core rule violation from a geo
or currency one.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError
from app.database import scope


class CoreRuleError(AppError):
    status_code = 422
    code = "core_rule_violation"


async def require_organization(db: AsyncSession) -> int:
    try:
        return await scope.require_organization_id(db)
    except scope.OrganizationRequiredError as exc:
        raise CoreRuleError(exc.msg, data=exc.data) from exc


__all__ = ["CoreRuleError", "require_organization"]
