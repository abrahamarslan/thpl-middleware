"""Hub business logic — always inside the caller's tenant and organization."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.geo.scope import require_organization
from app.modules.hubs import crud
from app.modules.hubs.enums import HubStatus
from app.modules.hubs.model import Hub
from app.modules.hubs.schema import HubCreate, HubUpdate


class HubRuleError(AppError):
    status_code = 422
    code = "hub_rule_violation"


def _check_version(hub: Hub, seen: int) -> None:
    if hub.row_version != seen:
        raise ConflictError(
            f"Hub '{hub.code}' changed since you loaded it (version {seen} → {hub.row_version}); reload and retry",
            data={"current_row_version": hub.row_version},
        )


async def list_hubs(db: AsyncSession, **filters) -> list[Hub]:
    return await crud.list_hubs(db, **filters)


async def get_hub(db: AsyncSession, ref: str | int) -> Hub:
    hub = await crud.get_by_id(db, int(ref)) if str(ref).isdigit() else await crud.get_by_code(db, str(ref))
    if hub is None:
        raise NotFoundError(f"Hub '{ref}' not found")
    return hub


async def create_hub(db: AsyncSession, body: HubCreate, *, actor_id: int | None = None) -> Hub:
    organization_id = await require_organization(db)
    if await crud.get_by_code(db, body.code):
        raise ConflictError(f"Hub code '{body.code}' already exists in this organization")
    if body.parent_hub_id is not None:
        await get_hub(db, body.parent_hub_id)

    values = body.model_dump(exclude_none=True)
    values["hub_type"] = body.hub_type.value
    hub = Hub(**values, organization_id=organization_id)
    db.add(hub)
    await db.flush()
    await record_activity(
        db, action="hub_created", actor_id=actor_id, subject_type="Hub", subject_id=hub.id,
        changes={"after": {"code": hub.code, "name": hub.name, "type": hub.hub_type}},
    )
    return hub


async def update_hub(db: AsyncSession, ref: str, body: HubUpdate, *, actor_id: int | None = None) -> Hub:
    hub = await get_hub(db, ref)
    _check_version(hub, body.row_version)
    changes = body.model_dump(exclude_unset=True, exclude={"row_version"})
    if "parent_hub_id" in changes and changes["parent_hub_id"] is not None:
        if changes["parent_hub_id"] == hub.id:
            raise HubRuleError("A hub cannot be its own parent")
        await get_hub(db, changes["parent_hub_id"])
    for field in ("hub_type", "status"):
        if field in changes and changes[field] is not None:
            changes[field] = changes[field].value
    for field, value in changes.items():
        setattr(hub, field, value)
    await db.flush()
    await record_activity(
        db, action="hub_updated", actor_id=actor_id, subject_type="Hub", subject_id=hub.id,
        changes={"after": changes},
    )
    return hub


async def archive_hub(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> Hub:
    hub = await get_hub(db, ref)
    hub.status = HubStatus.ARCHIVED.value
    hub.deactivate(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="hub_archived", actor_id=actor_id, subject_type="Hub", subject_id=hub.id,
        context={"reason": reason},
    )
    return hub


async def delete_hub(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    hub = await get_hub(db, ref)
    children = await db.scalar(select(Hub.id).where(Hub.parent_hub_id == hub.id).limit(1))
    if children is not None:
        raise HubRuleError(f"Hub '{hub.code}' still has child hubs; move or archive them first")
    hub.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="hub_deleted", actor_id=actor_id, subject_type="Hub", subject_id=hub.id,
        context={"reason": reason},
    )
