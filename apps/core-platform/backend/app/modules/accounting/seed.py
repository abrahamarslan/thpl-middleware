"""``scripts/seed.py --only accounting.defaults`` — an organization's default accounts, where unambiguous.

Run after the first chart-of-accounts sync. Assigns an organization default ONLY when the
chart makes it unambiguous — exactly one live, active account of the defining type:

    receivable       the single ``accounts_receivable`` account
    payable          the single ``accounts_payable`` account
    inventory_asset  the single ``stock`` account

Everything else (sales, purchase, retained earnings, round-off …) is reported as unassigned
for an admin to set (``PUT /api/accounting/assignments/organization/{id}``): picking an
account by its NAME is exactly the guess the resolution engine refuses to make.

Idempotent; never overwrites an existing assignment (local or Zoho-fed).
"""

from __future__ import annotations

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.conf import settings
from app.database.tenancy import tenant_scope
from app.modules.accounting import crud
from app.modules.accounting.assignment import AccountAssignment
from app.modules.accounting.model import Account
from app.modules.accounting.seed_data import ORGANIZATION_PURPOSES

logger = structlog.get_logger("app.accounting.seed")

#: purpose → the account type whose single live account is the unambiguous default.
_UNAMBIGUOUS = {"receivable": "accounts_receivable", "payable": "accounts_payable", "inventory_asset": "stock"}


async def seed_organization_defaults(db: AsyncSession, organization_id: int) -> dict[str, list[str]]:
    """Returns ``{"assigned": [...], "kept": [...], "unassigned": [...]}`` (purpose codes)."""
    report: dict[str, list[str]] = {"assigned": [], "kept": [], "unassigned": []}
    existing = {row.purpose_code for row in await crud.list_for_owner(db, "organization", organization_id)
                if row.currency_id is None and row.organization_id == organization_id}
    for purpose in ORGANIZATION_PURPOSES:
        if purpose in existing:
            report["kept"].append(purpose)
            continue
        account_type = _UNAMBIGUOUS.get(purpose)
        candidates = [] if account_type is None else list((await db.scalars(
            select(Account.id).where(Account.organization_id == organization_id,
                                     Account.account_type == account_type, Account.status == "active")
        )).all())
        if len(candidates) != 1:
            report["unassigned"].append(purpose)
            continue
        db.add(AccountAssignment(organization_id=organization_id, owner_type_code="organization",
                                 owner_id=organization_id, purpose_code=purpose, account_id=candidates[0]))
        await db.flush()
        report["assigned"].append(purpose)
    logger.info("accounting.seed.organization_defaults", organization_id=organization_id, **report)
    return report


async def run_seed_accounting(database_url: str | None = None, *, tenant_code: str | None = None,
                              organization_code: str | None = None) -> dict:
    """Standalone entry point for ``scripts/seed.py`` — the company organization (THPL by default)."""
    from app.modules.tenants.seed import _async_url

    tenant_code = tenant_code or settings.COMPANY_TENANT_CODE
    organization_code = organization_code or settings.COMPANY_ORGANIZATION_CODE
    engine = create_async_engine(_async_url(database_url or settings.DATABASE_URL), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            row = (await db.execute(text(
                "SELECT t.id, o.id FROM org_management.tenants t "
                "JOIN org_management.organizations o ON o.tenant_id = t.id AND o.deleted_at IS NULL "
                "WHERE t.tenant_code = :t AND o.org_code = :o"), {"t": tenant_code, "o": organization_code})).first()
            if row is None:
                raise RuntimeError(f"organization {tenant_code}/{organization_code} not found — run the company "
                                   "seeder first")
            with tenant_scope(row[0], row[1]):
                report = await seed_organization_defaults(db, row[1])
            await db.commit()
    finally:
        await engine.dispose()
    return {"tenant_id": row[0], "organization_id": row[1], **report}


__all__ = ["run_seed_accounting", "seed_organization_defaults"]
