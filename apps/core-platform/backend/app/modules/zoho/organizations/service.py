"""Organizations business logic — local reads, outbox writes, sync triggers.

Read path: ALWAYS the local mirror (fast, offline-tolerant, zero Zoho rate
budget). Write path: the transactional outbox —

    create: local row first (zoho_id NULL, sync_status queued) -> outbox
            task POSTs to Zoho -> back-fills the generated zoho_id
    update: local update -> outbox PUT
    delete: local soft-delete -> outbox DELETE

so local apps get an immediate, consistent answer while Zoho converges in
the background.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.activity.recorder import model_changes, record_activity
from app.modules.zoho.organizations import crud
from app.modules.zoho.organizations.model import ZohoOrganization
from app.modules.zoho.organizations.schema import OrganizationCreate, OrganizationUpdate
from app.modules.zoho.sync.mixins import SyncStatus
from app.modules.zoho.sync.outbox import queue_outbound

logger = structlog.get_logger("app.zoho.organizations")

MODULE = "organizations"


async def list_organizations(
    db: AsyncSession, *, active_only: bool = False, page: int = 1, page_size: int = 50
) -> list[ZohoOrganization]:
    return await crud.list_all(db, active_only=active_only, page=page, page_size=page_size)


async def get_organization(db: AsyncSession, ref: str) -> ZohoOrganization:
    row = await crud.get_by_ref(db, ref)
    if row is None:
        raise NotFoundError(f"Organization '{ref}' not found")
    return row


async def create_organization(
    db: AsyncSession, payload: OrganizationCreate, *, actor_id: int | None = None
) -> ZohoOrganization:
    values = payload.model_dump(exclude_unset=True)
    values["sync_status"] = SyncStatus.QUEUED.value
    row = await crud.create(db, values)
    row.append_sync_log("local_create", actor_id=actor_id)

    await queue_outbound(db, MODULE, row.id, "create")
    await record_activity(
        db, action="organization_created", actor_id=actor_id,
        subject_type="ZohoOrganization", subject_id=row.id,
        changes={"after": values},
    )
    return row


async def update_organization(
    db: AsyncSession, ref: str, payload: OrganizationUpdate, *, actor_id: int | None = None
) -> ZohoOrganization:
    row = await get_organization(db, ref)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(row, field, value)
    changes = model_changes(row)
    row.sync_status = SyncStatus.QUEUED.value
    row.append_sync_log("local_update", actor_id=actor_id, fields=sorted(updates))
    await db.flush()

    await queue_outbound(db, MODULE, row.id, "update")
    await record_activity(
        db, action="organization_updated", actor_id=actor_id,
        subject_type="ZohoOrganization", subject_id=row.id, changes=changes,
    )
    return row


async def delete_organization(db: AsyncSession, ref: str, *, actor_id: int | None = None) -> None:
    row = await get_organization(db, ref)
    row.soft_delete()
    row.sync_status = SyncStatus.QUEUED.value
    row.append_sync_log("local_delete", actor_id=actor_id)
    await db.flush()

    await queue_outbound(db, MODULE, row.id, "delete")
    await record_activity(
        db, action="organization_deleted", actor_id=actor_id,
        subject_type="ZohoOrganization", subject_id=row.id,
    )


def trigger_sync(mode: str | None = None) -> str:
    """Enqueue an inbound sync run; returns the Celery task id."""
    from app.tasks.zoho_sync import sync_module

    result = sync_module.delay(MODULE, mode)
    logger.info("organizations_sync_triggered", mode=mode or "configured", task_id=result.id)
    return result.id
