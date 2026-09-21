"""Which organization a new ``geo`` row belongs to.

Its own module because both ``geo.service`` and ``geo.geocoding.service`` need
it and neither should import the other: the geocoding service writes places
and provenance rows, the place service asks the router for a distance. A
shared leaf breaks the cycle that would otherwise form.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError
from app.database.tenancy import current_organization_id, current_tenant_id


class GeoRuleError(AppError):
    status_code = 422
    code = "geo_rule_violation"


async def require_organization(db: AsyncSession) -> int:
    """The organization new rows belong to.

    ``geo`` tables have ``organization_id`` NOT NULL, so a caller with no
    organization bound would hit a raw IntegrityError. Resolve it here and
    fail with something a person can act on. A tenant with exactly one
    organization needs no ceremony; beyond that the caller picks one with the
    ``X-Organization-Id`` header.
    """
    organization_id = current_organization_id()
    if organization_id is not None:
        return organization_id

    # Raw SQL: the location hub must not import the organizations model
    # (.importlinter — the tenancy core sits below every feature).
    tenant_id = current_tenant_id()
    sql = ("SELECT id, org_code FROM org_management.organizations "
           "WHERE deleted_at IS NULL AND status <> 'archived' ")
    params: dict[str, Any] = {}
    if tenant_id is not None:
        sql += "AND tenant_id = :tenant_id "
        params["tenant_id"] = tenant_id
    roots = (await db.execute(text(sql + "ORDER BY depth, id LIMIT 2"), params)).all()

    if not roots:
        raise GeoRuleError(
            "This tenant has no organization yet; create one (POST /api/organizations) "
            "before adding places or addresses."
        )
    if len(roots) > 1:
        raise GeoRuleError(
            "Several organizations exist — choose one with the 'X-Organization-Id' header "
            "before adding places or addresses.",
            data={"hint": "GET /api/organizations lists them"},
        )
    return int(roots[0][0])


__all__ = ["GeoRuleError", "require_organization"]
