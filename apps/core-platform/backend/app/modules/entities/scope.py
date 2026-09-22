"""Which organization a new ``core`` master-data row belongs to.

``core.brands`` / ``core.manufacturers`` (and their children) have
``organization_id`` NOT NULL, so a caller with no organization bound would hit a
raw IntegrityError. Resolve it here and fail with something a person can act on
— the same contract as ``currencies.scope`` / ``geo.scope``. Kept local (not
imported from those modules) so the shared ``core`` tables stay independent
leaf helpers over the tenancy runtime.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError
from app.database.tenancy import current_organization_id, current_tenant_id


class CoreRuleError(AppError):
    status_code = 422
    code = "core_rule_violation"


async def require_organization(db: AsyncSession) -> int:
    """The organization new rows belong to.

    The request's organization (``X-Organization-Id`` or the user's own); else
    the tenant's single organization; else a 422 naming the header.
    """
    organization_id = current_organization_id()
    if organization_id is not None:
        return organization_id

    # Raw SQL: the core module must not import the organizations model.
    tenant_id = current_tenant_id()
    sql = ("SELECT id, org_code FROM org_management.organizations "
           "WHERE deleted_at IS NULL AND status <> 'archived' ")
    params: dict[str, Any] = {}
    if tenant_id is not None:
        sql += "AND tenant_id = :tenant_id "
        params["tenant_id"] = tenant_id
    roots = (await db.execute(text(sql + "ORDER BY depth, id LIMIT 2"), params)).all()

    if not roots:
        raise CoreRuleError(
            "This tenant has no organization yet; create one (POST /api/organizations) "
            "before adding brands or manufacturers."
        )
    if len(roots) > 1:
        raise CoreRuleError(
            "Several organizations exist — choose one with the 'X-Organization-Id' header "
            "before adding brands or manufacturers.",
            data={"hint": "GET /api/organizations lists them"},
        )
    return int(roots[0][0])


__all__ = ["CoreRuleError", "require_organization"]
