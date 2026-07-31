"""Files module — async data access (no business logic)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.files.model import FileEntity
from app.modules.files.schema import FileListFilters


def _alive() -> Select:
    return select(FileEntity).where(FileEntity.deleted_at.is_(None))


async def create(db: AsyncSession, values: dict) -> FileEntity:
    row = FileEntity(**values)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_by_uuid(db: AsyncSession, file_id: uuid.UUID) -> FileEntity | None:
    return await db.scalar(_alive().where(FileEntity.file_id == file_id))


async def get_by_zoho_id(db: AsyncSession, zoho_id: str) -> FileEntity | None:
    return await db.scalar(_alive().where(FileEntity.zoho_id == zoho_id))


def _apply_filters(query: Select, f: FileListFilters) -> Select:
    if f.file_type:
        query = query.where(FileEntity.file_type == f.file_type)
    if f.processing_status:
        query = query.where(FileEntity.processing_status == f.processing_status)
    if f.vendor_name:
        query = query.where(FileEntity.vendor_name == f.vendor_name)
    if f.fileable_type:
        query = query.where(FileEntity.fileable_type == f.fileable_type)
    if f.fileable_id:
        query = query.where(FileEntity.fileable_id == f.fileable_id)
    if f.is_active is not None:
        query = query.where(FileEntity.is_active.is_(f.is_active))
    return query


async def list_files(db: AsyncSession, f: FileListFilters) -> tuple[list[FileEntity], int]:
    query = _apply_filters(_alive(), f)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = query.order_by(FileEntity.created_at.desc()).offset((f.page - 1) * f.page_size).limit(f.page_size)
    rows = (await db.scalars(query)).all()
    return list(rows), total


async def slim_list(db: AsyncSession, *, page: int = 1, page_size: int = 100) -> list[FileEntity]:
    query = _alive().order_by(FileEntity.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    return list((await db.scalars(query)).all())


async def update(db: AsyncSession, file: FileEntity, values: dict) -> FileEntity:
    for key, value in values.items():
        setattr(file, key, value)
    await db.flush()
    await db.refresh(file)
    return file


async def soft_delete(db: AsyncSession, file: FileEntity) -> FileEntity:
    file.deleted_at = datetime.now(UTC)
    file.is_active = False
    await db.flush()
    return file
