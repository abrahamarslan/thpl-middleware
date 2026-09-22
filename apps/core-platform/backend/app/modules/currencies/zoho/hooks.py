"""The irreducible bits of the currency adapter: scope, and the rate projection.

Everything expressible as a field rule lives in ``fields.py``. What is left is
genuinely procedural: stamping the provenance pair the canonical table requires,
and turning a decoded rate into a row of the effective-dated history.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_object_session

from app.database.tenancy import current_organization_id
from app.modules.currencies.enums import CurrencyOwnerType
from app.modules.currencies.model import Currency, ExchangeRate
from app.modules.currencies.scope import CurrencyRuleError
from app.modules.currencies.zoho.translator import CURRENCY_TRANSLATOR, RATE_SOURCE

logger = structlog.get_logger("app.currencies.zoho")


def stamp_scope(payload: dict, values: dict[str, Any]) -> dict[str, Any]:
    """Resolve who the synced row is held for.

    ``currency.currencies`` requires an organization and a provenance pair, and
    the sync has no user to ask. The organization comes from the run's context
    — set by the connection that scheduled the sync.

    If there is no organization in context we refuse rather than guess. Which
    organization a tenant-wide Zoho *settings* record belongs to is an open
    architectural decision (see the redesign plan §10.1); quietly inventing an
    answer here would bake it in as a side effect.
    """
    organization_id = current_organization_id()
    if organization_id is None:
        raise CurrencyRuleError(
            "cannot place a synced currency: no organization in context. Zoho's "
            "/settings/currencies is tenant-wide, but currency.currencies requires an "
            "organization — resolve the connection→organization mapping first "
            "(docs/implementation-plan/sync-crosswalk-redesign.md §10.1)."
        )
    return {
        **values,
        "owner_type": CurrencyOwnerType.ORGANIZATION.value,
        "owner_id": organization_id,
    }


async def project_exchange_rates(currency: Currency, payload: dict) -> None:
    """Write the payload's rate into the effective-dated history.

    ``Currency.exchange_rate`` is only a cache; ``currency.exchange_rates`` is
    the truth. A currency payload carries the rate inline, so every sync of a
    currency is also a (possible) rate observation.

    Rows without an effective date are skipped: ``exchange_rates.effective_date``
    is NOT NULL because a rate with no date cannot be placed on a timeline, and
    a rate we cannot date is worse than no rate at all.
    """
    db = async_object_session(currency)
    if db is None or currency.id is None:
        return

    rows = CURRENCY_TRANSLATOR.decode(payload).children.get("exchange_rates") or []
    for row in rows:
        effective_date = row.get("effective_date")
        if effective_date is None or row.get("rate") is None:
            logger.info("currencies.zoho.rate_skipped", currency_id=currency.id,
                        reason="undated" if effective_date is None else "no_rate")
            continue

        existing = await db.scalar(
            select(ExchangeRate).where(
                ExchangeRate.currency_id == currency.id,
                ExchangeRate.effective_date == effective_date,
                ExchangeRate.rate_source == RATE_SOURCE,
            ).limit(1)
        )
        if existing is None:
            db.add(ExchangeRate(
                currency_id=currency.id,
                rate=row["rate"],
                effective_date=effective_date,
                rate_source=RATE_SOURCE,
                external_source=RATE_SOURCE,
                owner_type=currency.owner_type,
                owner_id=currency.owner_id,
                organization_id=currency.organization_id,
            ))
        elif existing.rate != row["rate"]:
            # Zoho restated the rate for a date we already hold.
            existing.rate = row["rate"]

    await db.flush()


__all__ = ["project_exchange_rates", "stamp_scope"]
