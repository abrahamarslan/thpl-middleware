"""HTTP API for the canonical currency master (schema ``currency``).

Mounted at ``/api/currencies``. The read-only Zoho mirror is a different thing
at ``/api/zoho/currencies``. ``{ref}`` accepts the uuid (preferred), the ISO
code (``INR``) or the numeric id.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.currencies import service
from app.modules.currencies.schema import (
    CurrencyCreate,
    CurrencyOut,
    CurrencySlim,
    CurrencyUpdate,
    CurrencyVerify,
    ExchangeRateIn,
    ExchangeRateOut,
)
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser

router = APIRouter()

_M = "currency"


@router.get("", response_model=ResponseModel[list[CurrencySlim]])
async def list_currencies(
    _: CurrentUser, db: DBSession,
    kind: str | None = Query(None, max_length=20),
    status: str | None = Query(None, max_length=20),
    is_active: bool | None = Query(None),
    base_only: bool = Query(False, description="Only the base/accounting currencies"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_currencies(
        db, kind=kind, status=status, is_active=is_active, base_only=base_only, page=page, page_size=page_size,
    )
    return ResponseModel(data=[CurrencySlim.model_validate(r) for r in rows])


@router.post("", response_model=ResponseModel[CurrencyOut], status_code=201)
async def create_currency(user: CurrentUser, db: DBSession, body: CurrencyCreate):
    currency = await service.create_currency(db, body, actor_id=user.id)
    return ResponseModel.ok(data=CurrencyOut.model_validate(currency), module=_M, msg_key="currency_created",
                            name=currency.currency_code or str(currency.uuid))


@router.get("/{ref}", response_model=ResponseModel[CurrencyOut])
async def get_currency(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=CurrencyOut.model_validate(await service.get_currency(db, ref)))


@router.patch("/{ref}", response_model=ResponseModel[CurrencyOut])
async def update_currency(user: CurrentUser, db: DBSession, ref: str, body: CurrencyUpdate):
    currency = await service.update_currency(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=CurrencyOut.model_validate(currency), module=_M, msg_key="currency_updated",
                            name=currency.currency_code or str(currency.uuid))


@router.post("/{ref}/verify", response_model=ResponseModel[CurrencyOut])
async def verify_currency(admin: TenantAdmin, db: DBSession, ref: str, body: CurrencyVerify):
    currency = await service.verify_currency(db, ref, body, actor_id=admin.id)
    return ResponseModel.ok(data=CurrencyOut.model_validate(currency), module=_M, msg_key="currency_verified",
                            name=currency.currency_code or str(currency.uuid))


@router.post("/{ref}/deactivate", response_model=ResponseModel[CurrencyOut])
async def deactivate_currency(admin: TenantAdmin, db: DBSession, ref: str,
                              reason: str = Query(..., min_length=3, max_length=500)):
    currency = await service.deactivate_currency(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=CurrencyOut.model_validate(currency), module=_M, msg_key="currency_deactivated",
                            name=currency.currency_code or str(currency.uuid))


@router.post("/{ref}/reactivate", response_model=ResponseModel[CurrencyOut])
async def reactivate_currency(admin: TenantAdmin, db: DBSession, ref: str):
    currency = await service.reactivate_currency(db, ref, actor_id=admin.id)
    return ResponseModel.ok(data=CurrencyOut.model_validate(currency), module=_M, msg_key="currency_reactivated",
                            name=currency.currency_code or str(currency.uuid))


@router.post("/{ref}/archive", response_model=ResponseModel[CurrencyOut])
async def archive_currency(admin: TenantAdmin, db: DBSession, ref: str,
                           reason: str = Query(..., min_length=3, max_length=500)):
    currency = await service.archive_currency(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=CurrencyOut.model_validate(currency), module=_M, msg_key="currency_archived",
                            name=currency.currency_code or str(currency.uuid))


@router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_currency(admin: TenantAdmin, db: DBSession, ref: str,
                          reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_currency(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="currency_deleted", name=ref)


# ── exchange rates ──────────────────────────────────────────────────────────

@router.get("/{ref}/rates", response_model=ResponseModel[list[ExchangeRateOut]])
async def list_exchange_rates(_: CurrentUser, db: DBSession, ref: str):
    rates = await service.list_exchange_rates(db, ref)
    return ResponseModel(data=[ExchangeRateOut.model_validate(r) for r in rates])


@router.post("/{ref}/rates", response_model=ResponseModel[ExchangeRateOut], status_code=201)
async def add_exchange_rate(user: CurrentUser, db: DBSession, ref: str, body: ExchangeRateIn):
    rate = await service.add_exchange_rate(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=ExchangeRateOut.model_validate(rate), module=_M, msg_key="exchange_rate_added",
                            name=str(rate.effective_date))


@router.get("/{ref}/rate", response_model=ResponseModel[ExchangeRateOut | None])
async def current_rate(
    _: CurrentUser, db: DBSession, ref: str,
    as_of: dt.date | None = Query(None, description="The newest rate effective on or before this date"),
):
    rate = await service.current_rate(db, ref, as_of=as_of)
    return ResponseModel(data=ExchangeRateOut.model_validate(rate) if rate else None)