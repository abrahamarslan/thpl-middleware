"""Which organization a new ``currency`` row belongs to.

``currency`` tables have ``organization_id`` NOT NULL, so a caller with no
organization bound would hit a raw IntegrityError. Resolve it here and fail
with something a person can act on — the same contract as ``geo.scope``.

Kept local (not imported from ``geo``) so this module stays independent of the
location hub; both are leaf helpers over the tenancy runtime.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError
from app.database.tenancy import current_organization_id, current_tenant_id


class CurrencyRuleError(AppError):
    status_code = 422
    code = "currency_rule_violation"


async def require_organization(db: AsyncSession) -> int:
    """The organization new rows belong to.

    The request's organization (``X-Organization-Id`` or the user's own); else
    the tenant's single organization; else a 422 naming the header — not a
    constraint violation.
    """
    organization_id = current_organization_id()
    if organization_id is not None:
        return organization_id

    # Raw SQL: the currency module must not import the organizations model.
    tenant_id = current_tenant_id()
    sql = ("SELECT id, org_code FROM org_management.organizations "
           "WHERE deleted_at IS NULL AND status <> 'archived' ")
    params: dict[str, Any] = {}
    if tenant_id is not None:
        sql += "AND tenant_id = :tenant_id "
        params["tenant_id"] = tenant_id
    roots = (await db.execute(text(sql + "ORDER BY depth, id LIMIT 2"), params)).all()

    if not roots:
        raise CurrencyRuleError(
            "This tenant has no organization yet; create one (POST /api/organizations) "
            "before adding currencies."
        )
    if len(roots) > 1:
        raise CurrencyRuleError(
            "Several organizations exist — choose one with the 'X-Organization-Id' header "
            "before adding currencies.",
            data={"hint": "GET /api/organizations lists them"},
        )
    return int(roots[0][0])


__all__ = ["CurrencyRuleError", "require_organization"]