"""Fleet-partner business logic — always inside the caller's tenant + organization."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.fleet_partners import crud
from app.modules.fleet_partners.enums import FleetPartnerStatus
from app.modules.fleet_partners.model import FleetPartner
from app.modules.fleet_partners.schema import FleetPartnerCreate, FleetPartnerUpdate
from app.modules.geo.scope import require_organization


class FleetPartnerRuleError(AppError):
    status_code = 422
    code = "fleet_partner_rule_violation"


def _check_version(partner: FleetPartner, seen: int) -> None:
    if partner.row_version != seen:
        raise ConflictError(
            f"Fleet partner '{partner.code}' changed since you loaded it "
            f"(version {seen} → {partner.row_version}); reload and retry",
            data={"current_row_version": partner.row_version},
        )


async def list_partners(db: AsyncSession, **filters) -> list[FleetPartner]:
    return await crud.list_partners(db, **filters)


async def get_partner(db: AsyncSession, ref: str | int) -> FleetPartner:
    partner = (
        await crud.get_by_id(db, int(ref)) if str(ref).isdigit() else await crud.get_by_code(db, str(ref))
    )
    if partner is None:
        raise NotFoundError(f"Fleet partner '{ref}' not found")
    return partner


async def create_partner(db: AsyncSession, body: FleetPartnerCreate, *, actor_id: int | None = None) -> FleetPartner:
    organization_id = await require_organization(db)
    if await crud.get_by_code(db, body.code):
        raise ConflictError(f"Fleet partner code '{body.code}' already exists in this organization")

    values = body.model_dump(exclude_none=True)
    values["entity_type"] = body.entity_type.value
    partner = FleetPartner(**values, organization_id=organization_id)
    db.add(partner)
    await db.flush()
    await record_activity(
        db, action="fleet_partner_created", actor_id=actor_id, subject_type="FleetPartner", subject_id=partner.id,
        changes={"after": {"code": partner.code, "name": partner.name, "entity_type": partner.entity_type}},
    )
    return partner


async def update_partner(
    db: AsyncSession, ref: str, body: FleetPartnerUpdate, *, actor_id: int | None = None,
) -> FleetPartner:
    partner = await get_partner(db, ref)
    _check_version(partner, body.row_version)
    changes = body.model_dump(exclude_unset=True, exclude={"row_version"})
    for field in ("entity_type", "status"):
        if field in changes and changes[field] is not None:
            changes[field] = changes[field].value
    for field, value in changes.items():
        setattr(partner, field, value)
    await db.flush()
    await record_activity(
        db, action="fleet_partner_updated", actor_id=actor_id, subject_type="FleetPartner",
        subject_id=partner.id, changes={"after": changes},
    )
    return partner


async def archive_partner(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> FleetPartner:
    partner = await get_partner(db, ref)
    partner.status = FleetPartnerStatus.ARCHIVED.value
    partner.deactivate(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="fleet_partner_archived", actor_id=actor_id, subject_type="FleetPartner",
        subject_id=partner.id, context={"reason": reason},
    )
    return partner


async def delete_partner(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    partner = await get_partner(db, ref)
    partner.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="fleet_partner_deleted", actor_id=actor_id, subject_type="FleetPartner",
        subject_id=partner.id, context={"reason": reason},
    )
