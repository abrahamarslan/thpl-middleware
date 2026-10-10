"""HTTP endpoints of the price lists module (mounted at /api/price-lists). Read-only: Zoho masters them.

| Endpoint | What |
|---|---|
| ``GET /`` | Slim list — filters ``usage`` (sales/purchases), ``type``, ``status``, ``q``; with item counts |
| ``GET /{ref}`` | Fat detail with items and their brackets (``ref`` = id or uuid) |
| ``GET /{ref}/price`` | Quote one item: ``item_id`` (Zoho item id), ``quantity``, optional ``base_rate`` |

Organization scope is the request's (``X-Organization-Code``; THPL by default).
"""

from decimal import Decimal

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.price_lists import crud, service
from app.modules.price_lists.enums import PriceListStatus, PriceListType, PriceListUsage
from app.modules.price_lists.schema import PriceListOut, PriceListSlimOut, PriceQuoteOut
from app.modules.users.deps import CurrentUser

router = APIRouter()


def _currency_code(price_list) -> str | None:
    return price_list.currency.currency_code if price_list.currency is not None else None


@router.get("", response_model=ResponseModel[list[PriceListSlimOut]])
async def list_price_lists(
    _: CurrentUser, db: DBSession,
    usage: PriceListUsage | None = Query(None),
    type: PriceListType | None = Query(None),  # noqa: A002 — the API's vocabulary
    status: PriceListStatus | None = Query(None),
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
):
    rows = await crud.list_price_lists(
        db, usage=usage.value if usage else None, price_list_type=type.value if type else None,
        status=status.value if status else None, q=q, limit=page_size, offset=(page - 1) * page_size,
    )
    return ResponseModel(data=[
        PriceListSlimOut.model_validate({**PriceListSlimOut.model_validate(price_list).model_dump(),
                                         "currency_code": _currency_code(price_list), "item_count": count})
        for price_list, count in rows
    ])


@router.get("/{ref}", response_model=ResponseModel[PriceListOut])
async def get_price_list(_: CurrentUser, db: DBSession, ref: str):
    price_list = await service.get_price_list(db, ref, with_items=True)
    out = PriceListOut.model_validate(price_list)
    return ResponseModel(data=out.model_copy(update={"currency_code": _currency_code(price_list),
                                                     "item_count": len(out.items)}))


@router.get("/{ref}/price", response_model=ResponseModel[PriceQuoteOut])
async def quote_price(
    _: CurrentUser, db: DBSession, ref: str,
    item_id: str = Query(..., min_length=1, max_length=50, description="Zoho item_id"),
    quantity: Decimal = Query(Decimal(1), gt=0),
    base_rate: Decimal | None = Query(None, ge=0, description="The item's own rate (fallback / percentage base)"),
):
    result = await service.quote(db, ref, item_id=item_id, quantity=quantity, base_rate=base_rate)
    return ResponseModel(data=PriceQuoteOut.model_validate(result.as_dict()))
