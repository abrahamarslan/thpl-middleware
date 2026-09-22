"""Vehicle data access — simple queries only."""

from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vehicles.model import DrivingLicense, Vehicle, VehicleComplianceDocument


def _base_query(include_deleted: bool = False) -> Select:
    query = select(Vehicle)
    if include_deleted:
        query = query.execution_options(include_deleted=True)
    return query


async def get_by_id(db: AsyncSession, vehicle_id: int, *, include_deleted: bool = False) -> Vehicle | None:
    return await db.scalar(_base_query(include_deleted).where(Vehicle.id == vehicle_id))


async def get_by_registration(db: AsyncSession, registration_number: str) -> Vehicle | None:
    return await db.scalar(_base_query().where(Vehicle.registration_number == registration_number))


async def list_vehicles(
    db: AsyncSession,
    *,
    vehicle_type: str | None = None,
    status: str | None = None,
    owner_user_id: int | None = None,
    fleet_partner_id: int | None = None,
    hub_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[Vehicle]:
    stmt = _base_query().order_by(Vehicle.registration_number)
    if vehicle_type:
        stmt = stmt.where(Vehicle.vehicle_type == vehicle_type)
    if status:
        stmt = stmt.where(Vehicle.status == status)
    if owner_user_id:
        stmt = stmt.where(Vehicle.owner_user_id == owner_user_id)
    if fleet_partner_id:
        stmt = stmt.where(Vehicle.fleet_partner_id == fleet_partner_id)
    if hub_id:
        stmt = stmt.where(Vehicle.hub_id == hub_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Vehicle.registration_number.ilike(like) | Vehicle.make.ilike(like)
                          | Vehicle.model.ilike(like))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list((await db.scalars(stmt)).all())


async def list_compliance(
    db: AsyncSession, vehicle_id: int, *, compliance_type: str | None = None,
) -> list[VehicleComplianceDocument]:
    stmt = (
        select(VehicleComplianceDocument)
        .where(VehicleComplianceDocument.vehicle_id == vehicle_id)
        .order_by(VehicleComplianceDocument.valid_upto.desc().nullslast())
    )
    if compliance_type:
        stmt = stmt.where(VehicleComplianceDocument.compliance_type == compliance_type)
    return list((await db.scalars(stmt)).all())


async def list_driving_licenses(db: AsyncSession, user_id: int) -> list[DrivingLicense]:
    return list((await db.scalars(
        select(DrivingLicense).where(DrivingLicense.user_id == user_id)
        .order_by(DrivingLicense.valid_upto.desc())
    )).all())
