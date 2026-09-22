"""Which organization a new ``currency`` row belongs to.

``currency`` tables have ``organization_id`` NOT NULL, so a caller with no
organization bound would hit a raw IntegrityError. Resolve it here and fail
with something a person can act on — the same contract as ``geo.scope``.

Kept local (not imported from ``geo``) so this module stays independent of the
location hub; both are leaf helpers over the tenancy runtime.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError
from app.database import scope


class CurrencyRuleError(AppError):
    status_code = 422
    code = "currency_rule_violation"


async def require_organization(db: AsyncSession) -> int:
    """The organization new ``currency`` rows belong to.

    The resolution order lives in ``app/database/scope.py`` — one implementation
    shared by every module, because three copies of it drifted into three
    different answers. Only the error *code* is this module's own, so the API
    keeps answering ``currency_rule_violation``.
    """
    try:
        return await scope.require_organization_id(db)
    except scope.OrganizationRequiredError as exc:
        raise CurrencyRuleError(exc.msg, data=exc.data) from exc


__all__ = ["CurrencyRuleError", "require_organization"]