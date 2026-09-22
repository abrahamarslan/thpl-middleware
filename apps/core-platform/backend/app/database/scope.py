"""Which tenant and organization a piece of work belongs to.

``tenancy.py`` owns the *ambient* scope — the context variables a bound request
carries and the session events that filter and stamp every row from them. This
module owns the step before that: turning what a caller actually supplied into
a concrete ``(tenant_id, organization_id)``.

There is one resolution order, and every entry point uses it:

1. **An explicit organization code** — ``X-Organization-Code: THPL``. Readable,
   stable across environments, and the only form a human types. For an
   authenticated request the code is resolved *within the caller's own tenant*,
   so a code cannot be used to reach across tenants (see ``for_tenant``).
2. **An explicit organization uuid** — ``X-Organization-Id``. The original
   form; kept because it is already in use and because a uuid is what a UI
   holds after listing organizations.
3. **The ambient scope** — what ``tenancy.bind_user`` already bound for this
   request. A signed-in user writing to their own organization names nothing.
4. **The tenant's only organization**, when it has exactly one. A tenant that
   has never branched needs no ceremony either, and refusing it would be
   pedantry.
5. **The configured default** — ``DEFAULT_ORGANIZATION_CODE`` inside
   ``DEFAULT_TENANT_CODE``. This is what makes a single-company deployment work
   with no per-request ceremony: set both to ``THPL`` and every unattributed
   write — registration, a Celery task, a Zoho sync run — lands on the
   company's own organization.
6. **Nothing resolved → refuse.** ``OrganizationRequiredError`` (422,
   ``organization_required``) names both headers and the setting. This is a
   deliberate error and not a silent NULL: ``organization_id`` is NOT NULL on
   every operational table, so the alternative is an IntegrityError from
   somewhere deep in a flush, which tells the caller nothing.

Steps 3–5 are ordered narrowest-first on purpose. A bound request must never
fall through to the deployment default, because that would silently move a
caller's write into another tenant's organization.

Raw SQL throughout, on purpose: this sits below every feature module
(``.importlinter``), so it cannot import the ``Organization`` model that the
features themselves depend on.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, ForbiddenError
from app.core.conf import settings
from app.database.tenancy import current_organization_id, current_tenant_id, resolve_tenant_id

logger = structlog.get_logger("app.database.scope")


class OrganizationRequiredError(AppError):
    """No organization could be resolved for a write that requires one."""

    status_code = 422
    code = "organization_required"


@dataclass(frozen=True, slots=True)
class Scope:
    """A resolved place to read and write: one tenant, one of its organizations.

    ``org_code`` is present when the scope came from a lookup and ``None`` when
    it came from the already-bound request context — reading it back would be a
    query for a value nothing needs.
    """

    tenant_id: int
    organization_id: int
    org_code: str | None = None


_SELECT = (
    "SELECT o.id, o.org_code, o.tenant_id FROM org_management.organizations o "
    "WHERE o.deleted_at IS NULL AND o.status <> 'archived' "
)


async def _one(db: AsyncSession, where: str, params: dict) -> Scope | None:
    row = (await db.execute(text(_SELECT + where + " LIMIT 1"), params)).first()
    return Scope(tenant_id=int(row[2]), organization_id=int(row[0]), org_code=row[1]) if row else None


async def by_code(db: AsyncSession, org_code: str, *, tenant_id: int | None = None) -> Scope | None:
    """Resolve an organization code. Case-insensitive — codes are typed by hand.

    ``tenant_id`` confines the lookup to one tenant. Pass it for every
    authenticated request: without it a caller could name another tenant's code
    and write into it, which is the whole isolation model gone.
    """
    where = "AND upper(o.org_code) = upper(:code) "
    params: dict = {"code": org_code.strip()}
    if tenant_id is not None:
        where += "AND o.tenant_id = :tenant_id "
        params["tenant_id"] = tenant_id
    return await _one(db, where + "ORDER BY o.depth, o.id", params)


async def by_uuid(db: AsyncSession, org_uuid: str, *, tenant_id: int | None = None) -> Scope | None:
    where = "AND o.uuid = CAST(:org_uuid AS uuid) "
    params: dict = {"org_uuid": str(org_uuid)}
    if tenant_id is not None:
        where += "AND o.tenant_id = :tenant_id "
        params["tenant_id"] = tenant_id
    return await _one(db, where, params)


async def configured_default(db: AsyncSession) -> Scope | None:
    """The deployment's own organization: where an unattributed write belongs.

    ``DEFAULT_ORGANIZATION_CODE`` within ``DEFAULT_TENANT_CODE`` when both are
    set and the row exists. Otherwise the default tenant's **only**
    organization — a deployment that has never branched has exactly one
    candidate and refusing it would be pedantry, and it is what makes a freshly
    migrated database (whose tenant has one organization but not yet the seeded
    code) work before ``scripts/seed.py`` has ever run.

    Never a *guess*: with several organizations and no configured code there is
    no honest answer, and the caller is asked to name one.
    """
    tenant_id = await resolve_tenant_id(db)
    code = (settings.DEFAULT_ORGANIZATION_CODE or "").strip()
    if code:
        found = await by_code(db, code, tenant_id=tenant_id)
        if found is not None:
            return found
        # Configured and absent is a misconfiguration, not a reason to fail the
        # write outright — but it must be visible, because the fallback below
        # will quietly do something reasonable and different.
        logger.warning(
            "scope.default_organization_missing", org_code=code, tenant_id=tenant_id,
            setting="DEFAULT_ORGANIZATION_CODE",
            action="falling back to the tenant's only organization, if it has one",
        )
    return await sole_organization(db, tenant_id)


async def sole_organization(db: AsyncSession, tenant_id: int) -> Scope | None:
    """The tenant's only organization, or ``None`` when it has 0 or 2+."""
    rows = (await db.execute(
        text(_SELECT + "AND o.tenant_id = :tenant_id ORDER BY o.depth, o.id LIMIT 2"),
        {"tenant_id": tenant_id},
    )).all()
    if len(rows) != 1:
        return None
    return Scope(tenant_id=int(rows[0][2]), organization_id=int(rows[0][0]), org_code=rows[0][1])


def current() -> Scope | None:
    """The scope this request is already bound to, if any (``tenancy.bind_user``)."""
    tenant_id, organization_id = current_tenant_id(), current_organization_id()
    if tenant_id is None or organization_id is None:
        return None
    return Scope(tenant_id=tenant_id, organization_id=organization_id)


async def resolve(
    db: AsyncSession,
    *,
    org_code: str | None = None,
    org_uuid: str | None = None,
    for_tenant: int | None = None,
) -> Scope | None:
    """The resolution order in the module docstring. ``None`` = nothing resolved.

    ``for_tenant`` confines an explicitly named organization to one tenant.
    Authenticated callers always pass their own tenant; unauthenticated ones
    (registration, a public sign-up) pass ``None``, because for them the code
    is what *chooses* the tenant.
    """
    if org_code:
        found = await by_code(db, org_code, tenant_id=for_tenant)
        if found is None:
            raise ForbiddenError(
                f"No organization with code '{org_code.strip()}'"
                + (" in your organization's account" if for_tenant is not None else ""),
                data={"org_code": org_code.strip()},
            )
        return found

    if org_uuid:
        found = await by_uuid(db, org_uuid, tenant_id=for_tenant)
        if found is None:
            raise ForbiddenError(
                "X-Organization-Id is not an organization you can use",
                data={"organization_uuid": str(org_uuid)},
            )
        return found

    bound = current()
    if bound is not None:
        return bound

    tenant_id = for_tenant if for_tenant is not None else current_tenant_id()
    if tenant_id is not None:
        # A caller already inside a tenant stays in it: falling through to the
        # deployment default would silently move the write to another tenant.
        return await sole_organization(db, tenant_id)

    return await configured_default(db)


async def require(
    db: AsyncSession,
    *,
    org_code: str | None = None,
    org_uuid: str | None = None,
    for_tenant: int | None = None,
) -> Scope:
    """``resolve``, but a miss is an error a caller can act on."""
    found = await resolve(db, org_code=org_code, org_uuid=org_uuid, for_tenant=for_tenant)
    if found is not None:
        return found
    raise OrganizationRequiredError(_MISSING, data=_MISSING_DATA)


async def require_organization_id(db: AsyncSession) -> int:
    """The organization the current unit of work writes to.

    What ``geo``, ``currencies`` and the sync engine call: same order, and only
    the id, because that is all a caller writing a row needs.
    """
    return (await require(db)).organization_id


_MISSING = (
    "No organization for this request. Send 'X-Organization-Code' (e.g. THPL) or "
    "'X-Organization-Id', or set DEFAULT_ORGANIZATION_CODE so unattributed writes "
    "have a home."
)
_MISSING_DATA = {
    "headers": ["X-Organization-Code", "X-Organization-Id"],
    "setting": "DEFAULT_ORGANIZATION_CODE",
    "hint": "GET /api/organizations lists the organizations you can use",
}


__all__ = [
    "OrganizationRequiredError",
    "Scope",
    "by_code",
    "by_uuid",
    "configured_default",
    "current",
    "require",
    "require_organization_id",
    "resolve",
    "sole_organization",
]
