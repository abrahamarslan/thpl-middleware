"""Vehicle business logic — tenant + organization scoped."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.geo.scope import require_organization
from app.modules.vehicles import crud
from app.modules.vehicles.enums import VehicleStatus
from app.modules.vehicles.model import DrivingLicense, Vehicle, VehicleComplianceDocument
from app.modules.vehicles.schema import (
    DrivingLicenseCreate,
    VehicleComplianceCreate,
    VehicleCreate,
    VehicleUpdate,
)


class VehicleRuleError(AppError):
    status_code = 422
    code = "vehicle_rule_violation"


def _check_version(vehicle: Vehicle, seen: int) -> None:
    if vehicle.row_version != seen:
        raise ConflictError(
            f"Vehicle '{vehicle.registration_number}' changed since you loaded it "
            f"(version {seen} → {vehicle.row_version}); reload and retry",
            data={"current_row_version": vehicle.row_version},
        )


async def list_vehicles(db: AsyncSession, **filters) -> list[Vehicle]:
    return await crud.list_vehicles(db, **filters)


async def get_vehicle(db: AsyncSession, ref: str | int) -> Vehicle:
    vehicle = (
        await crud.get_by_id(db, int(ref)) if str(ref).isdigit()
        else await crud.get_by_registration(db, str(ref))
    )
    if vehicle is None:
        raise NotFoundError(f"Vehicle '{ref}' not found")
    return vehicle


async def create_vehicle(db: AsyncSession, body: VehicleCreate, *, actor_id: int | None = None) -> Vehicle:
    organization_id = await require_organization(db)
    if await crud.get_by_registration(db, body.registration_number):
        raise ConflictError(f"Vehicle '{body.registration_number}' already exists")

    values = body.model_dump(exclude_none=True)
    values["vehicle_type"] = body.vehicle_type.value
    values["ownership_type"] = body.ownership_type.value
    if body.fuel_type is not None:
        values["fuel_type"] = body.fuel_type.value
    vehicle = Vehicle(**values, organization_id=organization_id)
    db.add(vehicle)
    await db.flush()
    await record_activity(
        db, action="vehicle_created", actor_id=actor_id, subject_type="Vehicle", subject_id=vehicle.id,
        changes={"after": {"registration_number": vehicle.registration_number, "type": vehicle.vehicle_type}},
    )
    return vehicle


async def update_vehicle(
    db: AsyncSession, ref: str, body: VehicleUpdate, *, actor_id: int | None = None,
) -> Vehicle:
    vehicle = await get_vehicle(db, ref)
    _check_version(vehicle, body.row_version)
    changes = body.model_dump(exclude_unset=True, exclude={"row_version"})
    if "registration_number" in changes and changes["registration_number"]:
        existing = await crud.get_by_registration(db, changes["registration_number"])
        if existing and existing.id != vehicle.id:
            raise ConflictError(f"Vehicle '{changes['registration_number']}' already exists")
    for field in ("vehicle_type", "ownership_type", "fuel_type", "status"):
        if field in changes and changes[field] is not None:
            changes[field] = changes[field].value
    for field, value in changes.items():
        setattr(vehicle, field, value)
    await db.flush()
    await record_activity(
        db, action="vehicle_updated", actor_id=actor_id, subject_type="Vehicle", subject_id=vehicle.id,
        changes={"after": changes},
    )
    return vehicle


async def archive_vehicle(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> Vehicle:
    vehicle = await get_vehicle(db, ref)
    vehicle.status = VehicleStatus.DEREGISTERED.value
    vehicle.deactivate(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="vehicle_archived", actor_id=actor_id, subject_type="Vehicle", subject_id=vehicle.id,
        context={"reason": reason},
    )
    return vehicle


async def delete_vehicle(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    vehicle = await get_vehicle(db, ref)
    vehicle.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="vehicle_deleted", actor_id=actor_id, subject_type="Vehicle", subject_id=vehicle.id,
        context={"reason": reason},
    )


# ── compliance documents ─────────────────────────────────────────────────────

async def list_compliance(db: AsyncSession, ref: str, *, compliance_type: str | None = None):
    vehicle = await get_vehicle(db, ref)
    return await crud.list_compliance(db, vehicle.id, compliance_type=compliance_type)


async def add_compliance(
    db: AsyncSession, ref: str, body: VehicleComplianceCreate, *, actor_id: int | None = None,
) -> VehicleComplianceDocument:
    vehicle = await get_vehicle(db, ref)
    if body.valid_from and body.valid_upto and body.valid_upto < body.valid_from:
        raise VehicleRuleError("valid_upto cannot be before valid_from")
    doc = VehicleComplianceDocument(
        organization_id=vehicle.organization_id,
        vehicle_id=vehicle.id,
        compliance_type=body.compliance_type.value,
        document_id=body.document_id,
        certificate_number=body.certificate_number,
        insurer_name=body.insurer_name,
        insurance_type=body.insurance_type.value if body.insurance_type else None,
        permit_type=body.permit_type.value if body.permit_type else None,
        permit_region=body.permit_region,
        issued_date=body.issued_date,
        valid_from=body.valid_from,
        valid_upto=body.valid_upto,
        status=body.status.value,
        renewed_from_id=body.renewed_from_id,
    )
    db.add(doc)
    await db.flush()
    await record_activity(
        db, action="vehicle_compliance_added", actor_id=actor_id, subject_type="Vehicle",
        subject_id=vehicle.id, changes={"after": {"type": doc.compliance_type, "status": doc.status}},
    )
    return doc


# ── driving licenses ─────────────────────────────────────────────────────────

async def list_driving_licenses(db: AsyncSession, user_id: int):
    return await crud.list_driving_licenses(db, user_id)


async def add_driving_license(
    db: AsyncSession, body: DrivingLicenseCreate, *, actor_id: int | None = None,
) -> DrivingLicense:
    organization_id = await require_organization(db)
    if body.valid_from and body.valid_upto < body.valid_from:
        raise VehicleRuleError("valid_upto cannot be before valid_from")
    # Close the current version (a new DL is a new row, not an overwrite).
    current = await db.scalar(
        select(DrivingLicense).where(
            DrivingLicense.user_id == body.user_id, DrivingLicense.is_current.is_(True),
        )
    )
    if current is not None:
        current.is_current = False
    dl = DrivingLicense(
        organization_id=organization_id,
        user_id=body.user_id,
        document_id=body.document_id,
        dl_number_masked=body.dl_number_masked,
        dl_number_encrypted=body.dl_number_encrypted,
        dl_classes=body.dl_classes,
        issuing_rto=body.issuing_rto,
        issue_date=body.issue_date,
        valid_from=body.valid_from,
        valid_upto=body.valid_upto,
        is_commercial_license=body.is_commercial_license,
        badge_number=body.badge_number,
        badge_issuing_authority=body.badge_issuing_authority,
        badge_valid_upto=body.badge_valid_upto,
        verified_via_parivahan=body.verified_via_parivahan,
        parivahan_reference_id=body.parivahan_reference_id,
        is_current=True,
    )
    db.add(dl)
    await db.flush()
    await record_activity(
        db, action="driving_license_added", actor_id=actor_id, subject_type="DrivingLicense",
        subject_id=dl.id, changes={"after": {"user_id": dl.user_id, "valid_upto": str(dl.valid_upto)}},
    )
    return dl
