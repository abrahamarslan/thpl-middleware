"""Fleet-partner API — mounted at /api/fleet-partners."""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.fleet_partners import service
from app.modules.fleet_partners.schema import (
    FleetPartnerCreate,
    FleetPartnerOut,
    FleetPartnerSlim,
    FleetPartnerUpdate,
)
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser

router = APIRouter()
_M = "fleet_partners"


@router.get("", response_model=ResponseModel[list[FleetPartnerSlim]])
async def list_partners(
    _: CurrentUser,
    db: DBSession,
    entity_type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    rows = await service.list_partners(
        db, entity_type=entity_type, status=status, q=q, page=page, page_size=page_size
    )
    return ResponseModel.ok(data=[FleetPartnerSlim.model_validate(r) for r in rows], module=_M, msg_key="listed")


@router.get("/{ref}", response_model=ResponseModel[FleetPartnerOut])
async def get_partner(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel.ok(
        data=FleetPartnerOut.model_validate(await service.get_partner(db, ref)), module=_M, msg_key="fetched"
    )


@router.post("", response_model=ResponseModel[FleetPartnerOut], status_code=201)
async def create_partner(user: CurrentUser, db: DBSession, body: FleetPartnerCreate):
    partner = await service.create_partner(db, body, actor_id=user.id)
    return ResponseModel.ok(
        data=FleetPartnerOut.model_validate(partner), module=_M, msg_key="created", code=partner.code
    )


@router.patch("/{ref}", response_model=ResponseModel[FleetPartnerOut])
async def update_partner(user: CurrentUser, db: DBSession, ref: str, body: FleetPartnerUpdate):
    partner = await service.update_partner(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(
        data=FleetPartnerOut.model_validate(partner), module=_M, msg_key="updated", code=partner.code
    )


@router.post("/{ref}/archive", response_model=ResponseModel[FleetPartnerOut])
async def archive_partner(admin: TenantAdmin, db: DBSession, ref: str,
                          reason: str = Query(..., min_length=3, max_length=500)):
    partner = await service.archive_partner(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(
        data=FleetPartnerOut.model_validate(partner), module=_M, msg_key="archived", code=partner.code
    )


@router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_partner(admin: TenantAdmin, db: DBSession, ref: str,
                         reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_partner(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="deleted", code=ref)
