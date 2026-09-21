"""Currency module business logic — the canonical master and its rate history.

| Rule | Enforced by |
|---|---|
| a row always belongs to one organization of the tenant | ``OrgEntityMixin`` (DB) + ``require_organization`` |
| one live currency per (tenant, code) | partial unique ``uq_currencies_tenant_code`` |
| one base / one default per (tenant, organization) | partial uniques + ``clear_other_*`` |
| one rate per currency per business date | partial unique ``uq_exchange_rates_currency_date`` |
| a currency in use is archived, never deleted | ``delete_currency`` counts live rates |
| concurrent edits don't overwrite each other | ``row_version`` |

``Currency.exchange_rate`` is only a cache; ``exchange_rates`` is the truth.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.currencies import crud
from app.modules.currencies.enums import (
    CurrencyOwnerType,
    CurrencyStatus,
    ExchangeRateStatus,
)
from app.modules.currencies.model import Currency, ExchangeRate
from app.modules.currencies.scope import CurrencyRuleError, require_organization
from app.modules.currencies.schema import (
    CurrencyCreate,
    CurrencyUpdate,
    CurrencyVerify,
    ExchangeRateIn,
)

logger = structlog.get_logger("app.currencies")

#: Enum-valued columns that must be written as plain strings.
_ENUM_FIELDS = ("kind", "symbol_placement", "rounding_method", "rate_update_frequency")


def _check_version(row: Any, seen: int, label: str) -> None:
    if row.row_version != seen:
        raise ConflictError(
            f"{label} changed since you loaded it (version {seen} → {row.row_version}); reload and retry",
            data={"current_row_version": row.row_version},
        )


def _stringify(values: dict) -> dict:
    return {k: (v.value if hasattr(v, "value") else v) for k, v in values.items()}


# ── currencies ──────────────────────────────────────────────────────────────

async def list_currencies(
    db: AsyncSession, *, kind: str | None = None, status: str | None = None,
    is_active: bool | None = None, base_only: bool = False, page: int = 1, page_size: int = 100,
) -> list[Currency]:
    return await crud.list_currencies(
        db, kind=kind, status=status, is_active=is_active, base_only=base_only, page=page, page_size=page_size,
    )


async def get_currency(db: AsyncSession, ref: str | uuid_lib.UUID) -> Currency:
    currency = await crud.get_currency_by_ref(db, str(ref))
    if currency is None:
        raise NotFoundError(f"Currency '{ref}' not found")
    return currency


async def create_currency(
    db: AsyncSession, body: CurrencyCreate, *, actor_id: int | None = None,
) -> Currency:
    organization_id = await require_organization(db)

    if body.currency_code:
        code = body.currency_code.upper()
        if await crud.get_currency_by_code(db, code) is not None:
            raise ConflictError(f"Currency '{code}' already exists for this tenant")

    values = _stringify(body.model_dump())
    if values.get("currency_code"):
        values["currency_code"] = values["currency_code"].upper()
    currency = Currency(
        **values,
        organization_id=organization_id,
        owner_type=CurrencyOwnerType.ORGANIZATION.value,
        owner_id=organization_id,
    )
    if body.is_base_currency:
        await crud.clear_other_base(db, currency)
    if body.is_default_currency:
        await crud.clear_other_default(db, currency)

    db.add(currency)
    await db.flush()
    await record_activity(
        db, action="currency_created", actor_id=actor_id, subject_type="Currency", subject_id=str(currency.uuid),
        changes={"after": {"code": currency.currency_code, "name": currency.currency_name}},
    )
    return currency


async def update_currency(
    db: AsyncSession, ref: str, body: CurrencyUpdate, *, actor_id: int | None = None,
) -> Currency:
    currency = await get_currency(db, ref)
    _check_version(currency, body.row_version, f"Currency '{currency.currency_code or currency.uuid}'")
    changes = _stringify(body.model_dump(exclude_unset=True, exclude={"row_version"}))

    before = {k: getattr(currency, k, None) for k in changes}
    for field, value in changes.items():
        setattr(currency, field, value)
    if changes.get("is_base_currency"):
        await crud.clear_other_base(db, currency)
    if changes.get("is_default_currency"):
        await crud.clear_other_default(db, currency)

    await db.flush()
    await record_activity(
        db, action="currency_updated", actor_id=actor_id, subject_type="Currency", subject_id=str(currency.uuid),
        changes={"before": {k: str(v) for k, v in before.items()},
                 "after": {k: str(v) for k, v in changes.items()}},
    )
    return currency


async def verify_currency(
    db: AsyncSession, ref: str, body: CurrencyVerify, *, actor_id: int | None = None,
) -> Currency:
    currency = await get_currency(db, ref)
    currency.mark_verified(
        method=body.verification_method, status=body.verification_status.value,
        data=body.verification_data, by=actor_id,
    )
    await db.flush()
    await record_activity(
        db, action="currency_verified", actor_id=actor_id, subject_type="Currency", subject_id=str(currency.uuid),
        context={"method": body.verification_method, "status": body.verification_status.value},
    )
    return currency


async def deactivate_currency(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> Currency:
    currency = await get_currency(db, ref)
    currency.is_active = False
    currency.deactivate(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="currency_deactivated", actor_id=actor_id, subject_type="Currency", subject_id=str(currency.uuid),
        context={"reason": reason},
    )
    return currency


async def reactivate_currency(db: AsyncSession, ref: str, *, actor_id: int | None = None) -> Currency:
    currency = await get_currency(db, ref)
    currency.is_active = True
    currency.reactivate()
    await db.flush()
    return currency


async def archive_currency(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> Currency:
    """Archive rather than delete: a currency referenced by a paid document
    must stay readable for as long as the document does."""
    currency = await get_currency(db, ref)
    currency.status = CurrencyStatus.ARCHIVED.value
    currency.is_base_currency = False
    currency.is_default_currency = False
    currency.is_active = False
    currency.deactivate(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="currency_archived", actor_id=actor_id, subject_type="Currency", subject_id=str(currency.uuid),
        context={"reason": reason},
    )
    return currency


async def delete_currency(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    currency = await get_currency(db, ref)
    in_use = await crud.live_rate_count(db, currency)
    if in_use:
        raise CurrencyRuleError(
            f"{in_use} exchange rate(s) still belong to this currency; archive it instead.",
            data={"rates": in_use},
        )
    currency.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="currency_deleted", actor_id=actor_id, subject_type="Currency", subject_id=str(currency.uuid),
        context={"reason": reason},
    )


# ── exchange rates ──────────────────────────────────────────────────────────

async def list_exchange_rates(db: AsyncSession, ref: str) -> list[ExchangeRate]:
    currency = await get_currency(db, ref)
    return await crud.list_exchange_rates(db, currency.id)


async def add_exchange_rate(
    db: AsyncSession, ref: str, body: ExchangeRateIn, *, actor_id: int | None = None,
) -> ExchangeRate:
    """Record a rate. The truth is this table; the currency's cache is refreshed
    only when the new rate is the newest one."""
    currency = await get_currency(db, ref)
    organization_id = await require_organization(db)

    # One rate per currency per business date: re-posting the same date updates
    # the existing row rather than colliding with the partial unique index.
    existing = await crud.get_rate_for_date(db, currency.id, body.effective_date)
    if existing is not None:
        existing.rate = body.rate
        existing.rate_source = body.rate_source
        existing.rate_type = body.rate_type
        existing.sync_metadata = body.sync_metadata
        existing.is_active = body.is_active
        existing.status = ExchangeRateStatus.ACTIVE.value
        rate, superseded = existing, 0
    else:
        # A newer rate supersedes the older active ones for the same currency.
        superseded = 0
        for older in await crud.active_rates_for(db, currency.id):
            if older.effective_date < body.effective_date:
                older.status = ExchangeRateStatus.SUPERSEDED.value
                superseded += 1

        rate = await crud.create_exchange_rate(db, {
            **body.model_dump(exclude={"is_active"}),
            "currency_id": currency.id,
            "organization_id": organization_id,
            "owner_type": CurrencyOwnerType.ORGANIZATION.value,
            "owner_id": organization_id,
            "status": ExchangeRateStatus.ACTIVE.value,
            "is_active": body.is_active,
        })

    is_newest = currency.effective_date is None or body.effective_date >= currency.effective_date
    if is_newest and body.is_active:
        currency.exchange_rate = body.rate
        currency.effective_date = body.effective_date
        currency.exchange_rate_as_of = dt.datetime.combine(body.effective_date, dt.time.min, tzinfo=dt.UTC)
        currency.exchange_rate_last_updated = dt.datetime.now(dt.UTC)
        currency.exchange_rate_source = body.rate_source

    await db.flush()
    await record_activity(
        db, action="exchange_rate_added", actor_id=actor_id, subject_type="Currency",
        subject_id=str(currency.uuid),
        changes={"after": {"rate": str(body.rate), "effective_date": body.effective_date.isoformat(),
                           "superseded": superseded}},
    )
    logger.info("currency.rate.added", currency_id=currency.id, rate_id=rate.id,
                effective_date=str(body.effective_date), superseded=superseded)
    return rate


async def current_rate(
    db: AsyncSession, ref: str, *, as_of: dt.date | None = None,
) -> ExchangeRate | None:
    currency = await get_currency(db, ref)
    return await crud.latest_rate_as_of(db, currency.id, as_of)