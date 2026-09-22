"""HTTP endpoints for the brand master (mounted at /api/brands).

``{ref}`` accepts the public uuid (preferred) or the numeric id. Static paths
are declared before ``/{ref}``.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.brands import service
from app.modules.brands.enums import BrandKind, BrandStatus
from app.modules.brands.schema import (
    BrandCreate,
    BrandManufacturerLinkCreate,
    BrandManufacturerLinkOut,
    BrandOut,
    BrandSlimOut,
    BrandUpdate,
)
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser

router = APIRouter()

_M = "brands"


@router.get("", response_model=ResponseModel[list[BrandSlimOut]])
async def list_brands(
    _: CurrentUser, db: DBSession,
    q: str | None = Query(None, max_length=200, description="Case-insensitive substring on the name"),
    status: BrandStatus | None = Query(None),
    kind: BrandKind | None = Query(None),
    parent_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_brands(
        db, q=q, status=status.value if status else None, kind=kind.value if kind else None,
        parent_id=parent_id, page=page, page_size=page_size,
    )
    return ResponseModel(data=[BrandSlimOut.model_validate(r) for r in rows])


@router.post("", response_model=ResponseModel[BrandOut], status_code=201)
async def create_brand(user: CurrentUser, db: DBSession, body: BrandCreate):
    brand = await service.create_brand(db, body, actor_id=user.id)
    return ResponseModel.ok(data=BrandOut.model_validate(brand), module=_M, msg_key="brand_created",
                            msg="Brand created", name=brand.name)


@router.get("/{ref}", response_model=ResponseModel[BrandOut])
async def get_brand(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=BrandOut.model_validate(await service.get_brand(db, ref)))


@router.patch("/{ref}", response_model=ResponseModel[BrandOut])
async def update_brand(user: CurrentUser, db: DBSession, ref: str, body: BrandUpdate):
    brand = await service.update_brand(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=BrandOut.model_validate(brand), module=_M, msg_key="brand_updated",
                            msg="Brand updated", name=brand.name)


@router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_brand(admin: TenantAdmin, db: DBSession, ref: str,
                       reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_brand(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="brand_deleted", msg="Brand deleted", name=ref)


# ── brand ↔ manufacturer ─────────────────────────────────────────────────────

@router.get("/{ref}/manufacturers", response_model=ResponseModel[list[BrandManufacturerLinkOut]])
async def list_brand_manufacturers(_: CurrentUser, db: DBSession, ref: str):
    links = await service.list_links(db, ref)
    return ResponseModel(data=[BrandManufacturerLinkOut.model_validate(link) for link in links])


@router.post("/{ref}/manufacturers", response_model=ResponseModel[BrandManufacturerLinkOut], status_code=201)
async def link_brand_manufacturer(user: CurrentUser, db: DBSession, ref: str,
                                  body: BrandManufacturerLinkCreate):
    link = await service.link_manufacturer(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=BrandManufacturerLinkOut.model_validate(link), module=_M,
                            msg_key="brand_manufacturer_linked", msg="Manufacturer linked",
                            name=str(link.uuid))


@router.delete("/{ref}/manufacturers/{link_ref}", response_model=ResponseModel[None])
async def unlink_brand_manufacturer(admin: TenantAdmin, db: DBSession, ref: str, link_ref: str,
                                    reason: str = Query(..., min_length=3, max_length=500)):
    await service.unlink_manufacturer(db, ref, link_ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="brand_manufacturer_unlinked",
                            msg="Manufacturer unlinked", name=link_ref)
