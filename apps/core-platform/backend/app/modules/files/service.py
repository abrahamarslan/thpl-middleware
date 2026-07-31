"""Files module — business logic.

Records audit activity (file.created / file.status_updated / file.deleted) via
the activity recorder so every change to a document is traceable.
"""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.files import crud
from app.modules.files.model import FileEntity
from app.modules.files.schema import FileCreate, FileListFilters, FileStatusUpdate

logger = structlog.get_logger("app.files")


async def create_file(db: AsyncSession, body: FileCreate, *, actor_id: int | None = None,
                      actor_label: str | None = None) -> FileEntity:
    if body.zoho_id and await crud.get_by_zoho_id(db, body.zoho_id):
        raise ConflictError(f"A file with zoho_id '{body.zoho_id}' already exists")

    values = body.model_dump()
    values["uploaded_by"] = actor_label
    file = await crud.create(db, values)
    logger.info("file_created", file_id=str(file.file_id), file_name=file.file_name, size=file.file_size)

    await record_activity(
        db, action="file.created", actor_id=actor_id, actor_label=actor_label,
        subject_type="file", subject_id=file.file_id, tenant_id=file.tenant_id,
        description=f"Uploaded {file.file_name}",
        context={"file_type": file.file_type, "size": file.file_size, "s3_key": file.s3_key},
    )
    return file


async def get_file(db: AsyncSession, file_id: uuid.UUID) -> FileEntity:
    file = await crud.get_by_uuid(db, file_id)
    if file is None:
        raise NotFoundError(f"File {file_id} not found")
    return file


async def list_files(db: AsyncSession, filters: FileListFilters) -> tuple[list[FileEntity], int]:
    return await crud.list_files(db, filters)


async def slim_list(db: AsyncSession, *, page: int = 1, page_size: int = 100) -> list[FileEntity]:
    return await crud.slim_list(db, page=page, page_size=page_size)


async def update_status(db: AsyncSession, file_id: uuid.UUID, body: FileStatusUpdate, *,
                        actor_id: int | None = None, actor_label: str | None = None) -> FileEntity:
    file = await get_file(db, file_id)
    values = body.model_dump(exclude_unset=True)
    if not values:
        return file
    before = {k: getattr(file, k) for k in values}
    file = await crud.update(db, file, values)

    await record_activity(
        db, action="file.status_updated", actor_id=actor_id, actor_label=actor_label,
        subject_type="file", subject_id=file.file_id, tenant_id=file.tenant_id,
        changes={k: {"old": before[k], "new": values[k]} for k in values},
    )
    return file


async def delete_file(db: AsyncSession, file_id: uuid.UUID, *, actor_id: int | None = None,
                      actor_label: str | None = None) -> None:
    file = await get_file(db, file_id)
    await crud.soft_delete(db, file)
    logger.info("file_deleted", file_id=str(file.file_id))
    await record_activity(
        db, action="file.deleted", actor_id=actor_id, actor_label=actor_label,
        subject_type="file", subject_id=file.file_id, tenant_id=file.tenant_id,
        description=f"Deleted {file.file_name}",
    )
