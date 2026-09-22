"""Vehicle API — mounted at /api/vehicles and /api/driving-licenses."""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser
from app.modules.vehicles import service
from app.modules.vehicles.schema import (
    DrivingLicenseCreate,
    DrivingLicenseOut,
    VehicleComplianceCreate,
    VehicleComplianceOut,
    VehicleCreate,
    VehicleOut,
    VehicleSlim,
    VehicleUpdate,
)

vehicles_router = APIRouter()
driving_licenses_router = APIRouter()
_M = "vehicles"


@vehicles_router.get("", response_model=ResponseModel[list[VehicleSlim]])
async def list_vehicles(
    _: CurrentUser,
    db: DBSession,
    vehicle_type: str | None = None,
    status: str | None = None,
    owner_user_id: int | None = None,
    fleet_partner_id: int | None = None,
    hub_id: int | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    rows = await service.list_vehicles(
        db, vehicle_type=vehicle_type, status=status, owner_user_id=owner_user_id,
        fleet_partner_id=fleet_partner_id, hub_id=hub_id, q=q, page=page, page_size=page_size,
    )
    return ResponseModel.ok(data=[VehicleSlim.model_validate(r) for r in rows], module=_M, msg_key="listed")


@vehicles_router.get("/{ref}", response_model=ResponseModel[VehicleOut])
async def get_vehicle(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel.ok(
        data=VehicleOut.model_validate(await service.get_vehicle(db, ref)), module=_M, msg_key="fetched"
    )


@vehicles_router.post("", response_model=ResponseModel[VehicleOut], status_code=201)
async def create_vehicle(user: CurrentUser, db: DBSession, body: VehicleCreate):
    vehicle = await service.create_vehicle(db, body, actor_id=user.id)
    return ResponseModel.ok(
        data=VehicleOut.model_validate(vehicle), module=_M, msg_key="created", code=vehicle.registration_number
    )


@vehicles_router.patch("/{ref}", response_model=ResponseModel[VehicleOut])
async def update_vehicle(user: CurrentUser, db: DBSession, ref: str, body: VehicleUpdate):
    vehicle = await service.update_vehicle(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(
        data=VehicleOut.model_validate(vehicle), module=_M, msg_key="updated", code=vehicle.registration_number
    )


@vehicles_router.post("/{ref}/archive", response_model=ResponseModel[VehicleOut])
async def archive_vehicle(admin: TenantAdmin, db: DBSession, ref: str,
                          reason: str = Query(..., min_length=3, max_length=500)):
    vehicle = await service.archive_vehicle(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(
        data=VehicleOut.model_validate(vehicle), module=_M, msg_key="archived", code=vehicle.registration_number
    )


@vehicles_router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_vehicle(admin: TenantAdmin, db: DBSession, ref: str,
                         reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_vehicle(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="deleted", code=ref)


@vehicles_router.get("/{ref}/compliance", response_model=ResponseModel[list[VehicleComplianceOut]])
async def list_compliance(_: CurrentUser, db: DBSession, ref: str, compliance_type: str | None = None):
    rows = await service.list_compliance(db, ref, compliance_type=compliance_type)
    return ResponseModel.ok(
        data=[VehicleComplianceOut.model_validate(r) for r in rows], module=_M, msg_key="compliance_listed"
    )


@vehicles_router.post("/{ref}/compliance", response_model=ResponseModel[VehicleComplianceOut], status_code=201)
async def add_compliance(user: CurrentUser, db: DBSession, ref: str, body: VehicleComplianceCreate):
    doc = await service.add_compliance(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(
        data=VehicleComplianceOut.model_validate(doc), module=_M, msg_key="compliance_added"
    )


@driving_licenses_router.get("/{user_id}", response_model=ResponseModel[list[DrivingLicenseOut]])
async def list_driving_licenses(_: CurrentUser, db: DBSession, user_id: int):
    rows = await service.list_driving_licenses(db, user_id)
    return ResponseModel.ok(
        data=[DrivingLicenseOut.model_validate(r) for r in rows], module=_M, msg_key="licenses_listed"
    )


@driving_licenses_router.post("", response_model=ResponseModel[DrivingLicenseOut], status_code=201)
async def add_driving_license(user: CurrentUser, db: DBSession, body: DrivingLicenseCreate):
    dl = await service.add_driving_license(db, body, actor_id=user.id)
    return ResponseModel.ok(data=DrivingLicenseOut.model_validate(dl), module=_M, msg_key="license_added")
