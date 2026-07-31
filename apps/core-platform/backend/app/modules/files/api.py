"""Files module — HTTP endpoints (thin; delegates to service)."""

import uuid

from fastapi import APIRouter, Query

from app.common.response.schema import PageModel, ResponseModel
from app.database.db import DBSession
from app.modules.files import service
from app.modules.files.schema import (
    FileCreate,
    FileListFilters,
    FileOut,
    FileSlimOut,
    FileStatusUpdate,
)
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.post("", response_model=ResponseModel[FileOut], status_code=201)
async def create_file(db: DBSession, current: CurrentUser, body: FileCreate):
    file = await service.create_file(db, body, actor_id=current.id, actor_label=current.email)
    return ResponseModel(data=FileOut.model_validate(file))


@router.get("", response_model=ResponseModel[PageModel[FileOut]])
async def list_files(db: DBSession, _: CurrentUser, filters: FileListFilters = Query()):
    rows, total = await service.list_files(db, filters)
    return ResponseModel(
        data=PageModel(
            items=[FileOut.model_validate(r) for r in rows],
            page=filters.page,
            page_size=filters.page_size,
            total=total,
            has_more=filters.page * filters.page_size < total,
        )
    )


@router.get("/slim", response_model=ResponseModel[list[FileSlimOut]])
async def slim_list(db: DBSession, _: CurrentUser, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500)):
    rows = await service.slim_list(db, page=page, page_size=page_size)
    return ResponseModel(data=[FileSlimOut.model_validate(r) for r in rows])


@router.get("/{file_id}", response_model=ResponseModel[FileOut])
async def get_file(db: DBSession, _: CurrentUser, file_id: uuid.UUID):
    file = await service.get_file(db, file_id)
    return ResponseModel(data=FileOut.model_validate(file))


@router.patch("/{file_id}/status", response_model=ResponseModel[FileOut])
async def update_status(db: DBSession, current: CurrentUser, file_id: uuid.UUID, body: FileStatusUpdate):
    file = await service.update_status(db, file_id, body, actor_id=current.id, actor_label=current.email)
    return ResponseModel(data=FileOut.model_validate(file))


@router.delete("/{file_id}", response_model=ResponseModel[dict])
async def delete_file(db: DBSession, current: CurrentUser, file_id: uuid.UUID):
    await service.delete_file(db, file_id, actor_id=current.id, actor_label=current.email)
    return ResponseModel(data={"deleted": True})
