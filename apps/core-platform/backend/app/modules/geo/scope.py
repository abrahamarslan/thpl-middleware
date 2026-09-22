"""Which organization a new ``geo`` row belongs to.

Its own module because both ``geo.service`` and ``geo.geocoding.service`` need
it and neither should import the other: the geocoding service writes places
and provenance rows, the place service asks the router for a distance. A
shared leaf breaks the cycle that would otherwise form.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError
from app.database import scope


class GeoRuleError(AppError):
    status_code = 422
    code = "geo_rule_violation"


async def require_organization(db: AsyncSession) -> int:
    """The organization new ``geo`` rows belong to.

    ``geo`` tables have ``organization_id`` NOT NULL, so a caller with no
    organization bound would hit a raw IntegrityError. The resolution order
    lives in ``app/database/scope.py`` — one implementation for every module,
    because three copies of it drifted into three different answers. Only the
    error *code* is this module's own, so an API client can still tell a geo
    rule violation from anything else.
    """
    try:
        return await scope.require_organization_id(db)
    except scope.OrganizationRequiredError as exc:
        raise GeoRuleError(exc.msg, data=exc.data) from exc


__all__ = ["GeoRuleError", "require_organization"]
