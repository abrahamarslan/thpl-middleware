"""HTTP endpoints for the manufacturer master (mounted at /api/manufacturers).

``{ref}`` accepts the public uuid (preferred) or the numeric id.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.manufacturers import service
from app.modules.manufacturers.enums import ManufacturerStatus
from app.modules.manufacturers.schema import (
    ManufacturerCreate,
    ManufacturerIdentifierCreate,
    ManufacturerIdentifierOut,
    ManufacturerOut,
    ManufacturerSlimOut,
    ManufacturerUpdate,
)
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser

router = APIRouter()

_M = "manufacturers"


@router.get("", response_model=ResponseModel[list[ManufacturerSlimOut]])
async def list_manufacturers(
    _: CurrentUser, db: DBSession,
    q: str | None = Query(None, max_length=200, description="Case-insensitive substring on the name"),
    status: ManufacturerStatus | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_manufacturers(
        db, q=q, status=status.value if status else None, page=page, page_size=page_size,
    )
    return ResponseModel(data=[ManufacturerSlimOut.model_validate(r) for r in rows])


@router.post("", response_model=ResponseModel[ManufacturerOut], status_code=201)
async def create_manufacturer(user: CurrentUser, db: DBSession, body: ManufacturerCreate):
    manufacturer = await service.create_manufacturer(db, body, actor_id=user.id)
    return ResponseModel.ok(data=ManufacturerOut.model_validate(manufacturer), module=_M,
                            msg_key="manufacturer_created", msg="Manufacturer created",
                            name=manufacturer.name)


@router.get("/{ref}", response_model=ResponseModel[ManufacturerOut])
async def get_manufacturer(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=ManufacturerOut.model_validate(await service.get_manufacturer(db, ref)))


@router.patch("/{ref}", response_model=ResponseModel[ManufacturerOut])
async def update_manufacturer(user: CurrentUser, db: DBSession, ref: str, body: ManufacturerUpdate):
    manufacturer = await service.update_manufacturer(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=ManufacturerOut.model_validate(manufacturer), module=_M,
                            msg_key="manufacturer_updated", msg="Manufacturer updated",
                            name=manufacturer.name)


@router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_manufacturer(admin: TenantAdmin, db: DBSession, ref: str,
                              reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_manufacturer(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="manufacturer_deleted",
                            msg="Manufacturer deleted", name=ref)


# ── identifiers ──────────────────────────────────────────────────────────────

@router.get("/{ref}/identifiers", response_model=ResponseModel[list[ManufacturerIdentifierOut]])
async def list_identifiers(_: CurrentUser, db: DBSession, ref: str):
    rows = await service.list_identifiers(db, ref)
    return ResponseModel(data=[ManufacturerIdentifierOut.model_validate(r) for r in rows])


@router.post("/{ref}/identifiers", response_model=ResponseModel[ManufacturerIdentifierOut], status_code=201)
async def add_identifier(user: CurrentUser, db: DBSession, ref: str, body: ManufacturerIdentifierCreate):
    identifier = await service.add_identifier(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=ManufacturerIdentifierOut.model_validate(identifier), module=_M,
                            msg_key="manufacturer_identifier_added", msg="Identifier added",
                            name=str(identifier.uuid))


@router.delete("/{ref}/identifiers/{identifier_ref}", response_model=ResponseModel[None])
async def remove_identifier(admin: TenantAdmin, db: DBSession, ref: str, identifier_ref: str,
                            reason: str = Query(..., min_length=3, max_length=500)):
    await service.remove_identifier(db, ref, identifier_ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="manufacturer_identifier_removed",
                            msg="Identifier removed", name=identifier_ref)
