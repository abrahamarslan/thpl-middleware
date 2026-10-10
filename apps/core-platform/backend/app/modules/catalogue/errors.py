"""The catalogue's own error codes (the global handlers render them into the response envelope).

Only the codes are module-specific; organization resolution is the platform's one implementation
(``app/database/scope.py``), wrapped so an API client can tell a catalogue rule from a geo one.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, ConflictError
from app.database import scope


class CatalogueRuleError(AppError):
    """A request that breaks a catalogue rule (422)."""

    status_code = 422
    code = "catalogue_rule_violation"


class CatalogueInUseError(ConflictError):
    """The row is referenced and cannot be deleted — deactivate it instead (409)."""

    code = "catalogue_in_use"


class ZohoOwnedFieldError(ConflictError):
    """A local edit to a field Zoho owns on a linked row (409) — change it in Zoho."""

    code = "zoho_owned_field"


async def require_organization(db: AsyncSession) -> int:
    try:
        return await scope.require_organization_id(db)
    except scope.OrganizationRequiredError as exc:
        raise CatalogueRuleError(exc.msg, data=exc.data) from exc


__all__ = ["CatalogueInUseError", "CatalogueRuleError", "ZohoOwnedFieldError", "require_organization"]
