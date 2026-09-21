"""Data access for the canonical currency module (crud layer — no business logic).

Currencies are addressed by their public ``uuid`` (or the ISO code); the
BigInteger ``id`` never leaves the database layer.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.currencies.model import Currency, ExchangeRate


# ── currencies ──────────────────────────────────────────────────────────────

async def list_currencies(
    db: AsyncSession, *, kind: str | None = None, status: str | None = None,
    is_active: bool | None = None, base_only: bool = False,
    page: int = 1, page_size: int = 100,
) -> list[Currency]:
    stmt = (
        select(Currency)
        .order_by(Currency.is_base_currency.desc().nulls_last(), Currency.currency_code.nulls_last(), Currency.id)
    )
    if kind:
        stmt = stmt.where(Currency.kind == kind)
    if status:
        stmt = stmt.where(Currency.status == status)
    if is_active is not None:
        stmt = stmt.where(Currency.is_active.is_(is_active))
    if base_only:
        stmt = stmt.where(Currency.is_base_currency.is_(True))
    return list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())


async def get_currency(db: AsyncSession, currency_uuid: uuid_lib.UUID) -> Currency | None:
    return await db.scalar(select(Currency).where(Currency.uuid == currency_uuid).limit(1))


async def get_currency_by_code(db: AsyncSession, code: str) -> Currency | None:
    return await db.scalar(select(Currency).where(Currency.currency_code == code.upper()).limit(1))


async def get_currency_by_ref(db: AsyncSession, ref: str) -> Currency | None:
    """uuid (preferred), numeric id, or ISO code."""
    try:
        parsed = uuid_lib.UUID(str(ref))
    except ValueError:
        conditions = [Currency.currency_code == str(ref).upper()]
        if str(ref).isdigit():
            conditions.append(Currency.id == int(ref))
        return await db.scalar(select(Currency).where(or_(*conditions)).limit(1))
    return await get_currency(db, parsed)


async def create_currency(db: AsyncSession, values: dict) -> Currency:
    currency = Currency(**values)
    db.add(currency)
    await db.flush()
    return currency


async def clear_other_base(db: AsyncSession, keep: Currency) -> None:
    """One base currency per (tenant, organization) — clear the old one rather
    than letting the partial unique index reject the write.

    Filtered on the globally-unique ``organization_id`` (not ``tenant_id``)
    because this runs before the new row is flushed, when the tenancy stamping
    has not filled ``tenant_id`` yet.
    """
    stmt = select(Currency).where(
        Currency.organization_id == keep.organization_id,
        Currency.is_base_currency.is_(True),
    )
    if keep.id is not None:
        stmt = stmt.where(Currency.id != keep.id)
    for other in (await db.scalars(stmt)).all():
        other.is_base_currency = False


async def clear_other_default(db: AsyncSession, keep: Currency) -> None:
    stmt = select(Currency).where(
        Currency.organization_id == keep.organization_id,
        Currency.is_default_currency.is_(True),
    )
    if keep.id is not None:
        stmt = stmt.where(Currency.id != keep.id)
    for other in (await db.scalars(stmt)).all():
        other.is_default_currency = False


async def live_rate_count(db: AsyncSession, currency: Currency) -> int:
    from sqlalchemy import func

    return int(await db.scalar(
        select(func.count()).select_from(ExchangeRate).where(ExchangeRate.currency_id == currency.id)
    ) or 0)


# ── exchange rates ──────────────────────────────────────────────────────────

async def list_exchange_rates(db: AsyncSession, currency_id: int) -> list[ExchangeRate]:
    stmt = (
        select(ExchangeRate)
        .where(ExchangeRate.currency_id == currency_id)
        .order_by(ExchangeRate.effective_date.desc(), ExchangeRate.id.desc())
    )
    return list((await db.scalars(stmt)).all())


async def get_exchange_rate(db: AsyncSession, currency_id: int, rate_uuid: uuid_lib.UUID) -> ExchangeRate | None:
    return await db.scalar(
        select(ExchangeRate).where(ExchangeRate.currency_id == currency_id, ExchangeRate.uuid == rate_uuid)
    )


async def get_rate_for_date(db: AsyncSession, currency_id: int, effective_date: dt.date) -> ExchangeRate | None:
    """One rate per currency per business date (live rows)."""
    return await db.scalar(
        select(ExchangeRate)
        .where(ExchangeRate.currency_id == currency_id, ExchangeRate.effective_date == effective_date)
        .limit(1)
    )


async def create_exchange_rate(db: AsyncSession, values: dict) -> ExchangeRate:
    rate = ExchangeRate(**values)
    db.add(rate)
    await db.flush()
    return rate


async def active_rates_for(db: AsyncSession, currency_id: int, *, excluding_id: int | None = None) -> list[ExchangeRate]:
    stmt = select(ExchangeRate).where(
        ExchangeRate.currency_id == currency_id,
        ExchangeRate.status == "active",
    )
    if excluding_id is not None:
        stmt = stmt.where(ExchangeRate.id != excluding_id)
    return list((await db.scalars(stmt)).all())


async def latest_rate_as_of(
    db: AsyncSession, currency_id: int, as_of: dt.date | None = None,
) -> ExchangeRate | None:
    """The newest active rate with ``effective_date <= as_of`` (or the newest ever)."""
    stmt = (
        select(ExchangeRate)
        .where(
            ExchangeRate.currency_id == currency_id,
            ExchangeRate.status.in_(("active", "superseded")),
        )
        .order_by(ExchangeRate.effective_date.desc(), ExchangeRate.id.desc())
        .limit(1)
    )
    if as_of is not None:
        stmt = stmt.where(ExchangeRate.effective_date <= as_of)
    return await db.scalar(stmt)