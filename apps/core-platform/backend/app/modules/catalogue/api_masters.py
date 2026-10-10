"""HTTP endpoints of the catalogue masters (mounted at /api/catalogue).

| Resource | Endpoints |
|---|---|
| GST UQC (global) | ``GET /uqc-codes`` |
| Units | ``GET POST /units`` · ``GET PATCH DELETE /units/{ref}`` |
| Packaging types | ``GET POST /packaging-types`` · ``GET PATCH DELETE /packaging-types/{ref}`` |
| Sales channels | ``GET POST /sales-channels`` · ``GET PATCH DELETE /sales-channels/{ref}`` |
| Item groups | ``GET POST /item-groups`` (``?tree=true`` for the nested tree) · ``GET PATCH DELETE /item-groups/{ref}`` |
| Attributes | ``GET POST /attributes`` · ``GET PATCH DELETE /attributes/{ref}`` · ``POST /attributes/{ref}/options`` · ``PATCH DELETE /attributes/{ref}/options/{option_ref}`` |

``{ref}`` is the public uuid (preferred) or the numeric id. Reads need a signed-in user; writes need the
``catalogue.<resource>:<action>`` permission, judged at the organization of the row. Rows are read in the
request's organization (``X-Organization-Code``). Deletes are soft and need a ``reason``.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import PageModel, ResponseModel
from app.database.db import DBSession
from app.modules.catalogue.enums import ChannelKind, MasterStatus, UnitClass
from app.modules.catalogue.schema.masters import (
    AttributeCreate,
    AttributeOptionCreate,
    AttributeOptionOut,
    AttributeOptionUpdate,
    AttributeOut,
    AttributeSlimOut,
    AttributeUpdate,
    ItemGroupCreate,
    ItemGroupNode,
    ItemGroupOut,
    ItemGroupSlimOut,
    ItemGroupUpdate,
    PackagingTypeCreate,
    PackagingTypeOut,
    PackagingTypeSlimOut,
    PackagingTypeUpdate,
    SalesChannelCreate,
    SalesChannelOut,
    SalesChannelSlimOut,
    SalesChannelUpdate,
    UnitCreate,
    UnitOut,
    UnitSlimOut,
    UnitUpdate,
    UqcCodeOut,
)
from app.modules.catalogue.service import masters as service
from app.modules.rbac.deps import Perm, org_of
from app.modules.users.deps import CurrentUser

router = APIRouter()

_M = "catalogue"
_MODEL = "app.modules.catalogue.model"
_REASON = Query(..., min_length=3, max_length=500, description="Why it is deleted (kept on the row)")


def _page(rows, total, out, page, page_size):
    return PageModel(items=[out.model_validate(r) for r in rows], total=total, page=page, page_size=page_size,
                     has_more=page * page_size < total)


def _ok(data, key: str, msg: str, **kw):
    return ResponseModel.ok(data=data, module=_M, msg_key=key, msg=msg, **kw)


# ── GST UQC ──────────────────────────────────────────────────────────────────

@router.get("/uqc-codes", response_model=ResponseModel[list[UqcCodeOut]])
async def list_uqc_codes(_: CurrentUser, db: DBSession, include_inactive: bool = Query(False)):
    rows = await service.list_uqc_codes(db, include_inactive=include_inactive)
    return ResponseModel(data=[UqcCodeOut.model_validate(r) for r in rows])


# ── units ────────────────────────────────────────────────────────────────────

@router.get("/units", response_model=ResponseModel[PageModel[UnitSlimOut]])
async def list_units(
    _: CurrentUser, db: DBSession,
    q: str | None = Query(None, max_length=100), unit_class: UnitClass | None = Query(None),
    status: MasterStatus | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
):
    rows, total = await service.list_units(
        db, q=q, unit_class=unit_class.value if unit_class else None, status=status.value if status else None,
        limit=page_size, offset=(page - 1) * page_size)
    return ResponseModel(data=_page(rows, total, UnitSlimOut, page, page_size))


@router.post("/units", response_model=ResponseModel[UnitOut], status_code=201)
async def create_unit(user: Perm("catalogue.unit:create"), db: DBSession, body: UnitCreate):
    unit = await service.create_unit(db, body, actor_id=user.id)
    return _ok(UnitOut.model_validate(unit), "unit_created", "Unit created", name=unit.code)


@router.get("/units/{ref}", response_model=ResponseModel[UnitOut])
async def get_unit(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=UnitOut.model_validate(await service.get_unit(db, ref)))


@router.patch("/units/{ref}", response_model=ResponseModel[UnitOut])
async def update_unit(user: Perm("catalogue.unit:update", target=org_of(f"{_MODEL}:Unit")),
                      db: DBSession, ref: str, body: UnitUpdate):
    unit = await service.update_unit(db, ref, body, actor_id=user.id)
    return _ok(UnitOut.model_validate(unit), "unit_updated", "Unit updated", name=unit.code)


@router.delete("/units/{ref}", response_model=ResponseModel[None])
async def delete_unit(user: Perm("catalogue.unit:delete", target=org_of(f"{_MODEL}:Unit")),
                      db: DBSession, ref: str, reason: str = _REASON):
    await service.delete_unit(db, ref, reason=reason, actor_id=user.id)
    return _ok(None, "unit_deleted", "Unit deleted", name=ref)


# ── packaging types ──────────────────────────────────────────────────────────

@router.get("/packaging-types", response_model=ResponseModel[PageModel[PackagingTypeSlimOut]])
async def list_packaging_types(
    _: CurrentUser, db: DBSession,
    q: str | None = Query(None, max_length=100), status: MasterStatus | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
):
    rows, total = await service.list_packaging_types(
        db, q=q, status=status.value if status else None, limit=page_size, offset=(page - 1) * page_size)
    return ResponseModel(data=_page(rows, total, PackagingTypeSlimOut, page, page_size))


@router.post("/packaging-types", response_model=ResponseModel[PackagingTypeOut], status_code=201)
async def create_packaging_type(user: Perm("catalogue.packaging_type:create"), db: DBSession,
                                body: PackagingTypeCreate):
    row = await service.create_packaging_type(db, body, actor_id=user.id)
    return _ok(PackagingTypeOut.model_validate(row), "packaging_type_created", "Packaging type created", name=row.code)


@router.get("/packaging-types/{ref}", response_model=ResponseModel[PackagingTypeOut])
async def get_packaging_type(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=PackagingTypeOut.model_validate(await service.get_packaging_type(db, ref)))


@router.patch("/packaging-types/{ref}", response_model=ResponseModel[PackagingTypeOut])
async def update_packaging_type(
    user: Perm("catalogue.packaging_type:update", target=org_of(f"{_MODEL}:PackagingType")),
    db: DBSession, ref: str, body: PackagingTypeUpdate,
):
    row = await service.update_packaging_type(db, ref, body, actor_id=user.id)
    return _ok(PackagingTypeOut.model_validate(row), "packaging_type_updated", "Packaging type updated", name=row.code)


@router.delete("/packaging-types/{ref}", response_model=ResponseModel[None])
async def delete_packaging_type(
    user: Perm("catalogue.packaging_type:delete", target=org_of(f"{_MODEL}:PackagingType")),
    db: DBSession, ref: str, reason: str = _REASON,
):
    await service.delete_packaging_type(db, ref, reason=reason, actor_id=user.id)
    return _ok(None, "packaging_type_deleted", "Packaging type deleted", name=ref)


# ── sales channels ───────────────────────────────────────────────────────────

@router.get("/sales-channels", response_model=ResponseModel[PageModel[SalesChannelSlimOut]])
async def list_sales_channels(
    _: CurrentUser, db: DBSession,
    q: str | None = Query(None, max_length=100), status: MasterStatus | None = Query(None),
    channel_kind: ChannelKind | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
):
    rows, total = await service.list_sales_channels(
        db, q=q, status=status.value if status else None,
        channel_kind=channel_kind.value if channel_kind else None, limit=page_size, offset=(page - 1) * page_size)
    return ResponseModel(data=_page(rows, total, SalesChannelSlimOut, page, page_size))


@router.post("/sales-channels", response_model=ResponseModel[SalesChannelOut], status_code=201)
async def create_sales_channel(user: Perm("catalogue.sales_channel:create"), db: DBSession, body: SalesChannelCreate):
    row = await service.create_sales_channel(db, body, actor_id=user.id)
    return _ok(SalesChannelOut.model_validate(row), "sales_channel_created", "Sales channel created", name=row.code)


@router.get("/sales-channels/{ref}", response_model=ResponseModel[SalesChannelOut])
async def get_sales_channel(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=SalesChannelOut.model_validate(await service.get_sales_channel(db, ref)))


@router.patch("/sales-channels/{ref}", response_model=ResponseModel[SalesChannelOut])
async def update_sales_channel(
    user: Perm("catalogue.sales_channel:update", target=org_of(f"{_MODEL}:SalesChannel")),
    db: DBSession, ref: str, body: SalesChannelUpdate,
):
    row = await service.update_sales_channel(db, ref, body, actor_id=user.id)
    return _ok(SalesChannelOut.model_validate(row), "sales_channel_updated", "Sales channel updated", name=row.code)


@router.delete("/sales-channels/{ref}", response_model=ResponseModel[None])
async def delete_sales_channel(
    user: Perm("catalogue.sales_channel:delete", target=org_of(f"{_MODEL}:SalesChannel")),
    db: DBSession, ref: str, reason: str = _REASON,
):
    await service.delete_sales_channel(db, ref, reason=reason, actor_id=user.id)
    return _ok(None, "sales_channel_deleted", "Sales channel deleted", name=ref)


# ── item groups ──────────────────────────────────────────────────────────────

@router.get("/item-groups", response_model=ResponseModel[PageModel[ItemGroupSlimOut] | list[ItemGroupNode]])
async def list_item_groups(
    _: CurrentUser, db: DBSession,
    tree: bool = Query(False, description="Return the whole nested tree instead of a page"),
    q: str | None = Query(None, max_length=100), status: MasterStatus | None = Query(None),
    parent_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
):
    if tree:
        return ResponseModel(data=await service.item_group_tree(db))
    rows, total = await service.list_item_groups(
        db, q=q, status=status.value if status else None, parent_id=parent_id,
        limit=page_size, offset=(page - 1) * page_size)
    return ResponseModel(data=_page(rows, total, ItemGroupSlimOut, page, page_size))


@router.post("/item-groups", response_model=ResponseModel[ItemGroupOut], status_code=201)
async def create_item_group(user: Perm("catalogue.item_group:create"), db: DBSession, body: ItemGroupCreate):
    row = await service.create_item_group(db, body, actor_id=user.id)
    return _ok(ItemGroupOut.model_validate(row), "item_group_created", "Item group created", name=row.code)


@router.get("/item-groups/{ref}", response_model=ResponseModel[ItemGroupOut])
async def get_item_group(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=ItemGroupOut.model_validate(await service.get_item_group(db, ref)))


@router.patch("/item-groups/{ref}", response_model=ResponseModel[ItemGroupOut])
async def update_item_group(
    user: Perm("catalogue.item_group:update", target=org_of(f"{_MODEL}:ItemGroup")),
    db: DBSession, ref: str, body: ItemGroupUpdate,
):
    row = await service.update_item_group(db, ref, body, actor_id=user.id)
    return _ok(ItemGroupOut.model_validate(row), "item_group_updated", "Item group updated", name=row.code)


@router.delete("/item-groups/{ref}", response_model=ResponseModel[None])
async def delete_item_group(
    user: Perm("catalogue.item_group:delete", target=org_of(f"{_MODEL}:ItemGroup")),
    db: DBSession, ref: str, reason: str = _REASON,
):
    await service.delete_item_group(db, ref, reason=reason, actor_id=user.id)
    return _ok(None, "item_group_deleted", "Item group deleted", name=ref)


# ── attributes ───────────────────────────────────────────────────────────────

async def _attribute_out(db, attribute) -> AttributeOut:
    options = await service.attribute_options(db, attribute)
    out = AttributeOut.model_validate(attribute, from_attributes=True)
    return out.model_copy(update={"options": [AttributeOptionOut.model_validate(o) for o in options]})


@router.get("/attributes", response_model=ResponseModel[PageModel[AttributeSlimOut]])
async def list_attributes(
    _: CurrentUser, db: DBSession,
    q: str | None = Query(None, max_length=100), status: MasterStatus | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
):
    rows, total = await service.list_attributes(
        db, q=q, status=status.value if status else None, limit=page_size, offset=(page - 1) * page_size)
    return ResponseModel(data=_page(rows, total, AttributeSlimOut, page, page_size))


@router.post("/attributes", response_model=ResponseModel[AttributeOut], status_code=201)
async def create_attribute(user: Perm("catalogue.attribute:create"), db: DBSession, body: AttributeCreate):
    row = await service.create_attribute(db, body, actor_id=user.id)
    return _ok(await _attribute_out(db, row), "attribute_created", "Attribute created", name=row.code)


@router.get("/attributes/{ref}", response_model=ResponseModel[AttributeOut])
async def get_attribute(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=await _attribute_out(db, await service.get_attribute(db, ref)))


@router.patch("/attributes/{ref}", response_model=ResponseModel[AttributeOut])
async def update_attribute(
    user: Perm("catalogue.attribute:update", target=org_of(f"{_MODEL}:Attribute")),
    db: DBSession, ref: str, body: AttributeUpdate,
):
    row = await service.update_attribute(db, ref, body, actor_id=user.id)
    return _ok(await _attribute_out(db, row), "attribute_updated", "Attribute updated", name=row.code)


@router.delete("/attributes/{ref}", response_model=ResponseModel[None])
async def delete_attribute(
    user: Perm("catalogue.attribute:delete", target=org_of(f"{_MODEL}:Attribute")),
    db: DBSession, ref: str, reason: str = _REASON,
):
    await service.delete_attribute(db, ref, reason=reason, actor_id=user.id)
    return _ok(None, "attribute_deleted", "Attribute deleted", name=ref)


@router.post("/attributes/{ref}/options", response_model=ResponseModel[AttributeOptionOut], status_code=201)
async def add_attribute_option(
    user: Perm("catalogue.attribute:update", target=org_of(f"{_MODEL}:Attribute")),
    db: DBSession, ref: str, body: AttributeOptionCreate,
):
    option = await service.add_option(db, ref, body, actor_id=user.id)
    return _ok(AttributeOptionOut.model_validate(option), "attribute_option_added", "Option added", name=option.value)


@router.patch("/attributes/{ref}/options/{option_ref}", response_model=ResponseModel[AttributeOptionOut])
async def update_attribute_option(
    user: Perm("catalogue.attribute:update", target=org_of(f"{_MODEL}:Attribute")),
    db: DBSession, ref: str, option_ref: str, body: AttributeOptionUpdate,
):
    option = await service.update_option(db, ref, option_ref, body, actor_id=user.id)
    return _ok(AttributeOptionOut.model_validate(option), "attribute_option_updated", "Option updated",
               name=option.value)


@router.delete("/attributes/{ref}/options/{option_ref}", response_model=ResponseModel[None])
async def delete_attribute_option(
    user: Perm("catalogue.attribute:update", target=org_of(f"{_MODEL}:Attribute")),
    db: DBSession, ref: str, option_ref: str, reason: str = _REASON,
):
    await service.delete_option(db, ref, option_ref, reason=reason, actor_id=user.id)
    return _ok(None, "attribute_option_deleted", "Option deleted", name=option_ref)
