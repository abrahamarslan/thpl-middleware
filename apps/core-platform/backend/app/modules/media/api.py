"""HTTP endpoints for media (mounted at /api/media).

Generic surface: domain modules may also call media.service directly from
their own endpoints (preferred when the owner must be validated).
"""

import json

from fastapi import APIRouter, File, Form, Query, UploadFile

from app.common.exception.errors import AppError
from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.media import service
from app.modules.media.schema import MediaOut
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.post("/upload", response_model=ResponseModel[MediaOut], status_code=201)
async def upload_media(
    user: CurrentUser,
    db: DBSession,
    file: UploadFile = File(...),
    model_type: str = Form(...),
    model_id: str = Form(...),
    collection: str = Form("default"),
    conversions: str | None = Form(None, description='JSON, e.g. {"thumb": [150, 150]}'),
):
    parsed_conversions: dict[str, tuple[int, int]] | None = None
    if conversions:
        try:
            raw = json.loads(conversions)
            parsed_conversions = {k: (int(v[0]), int(v[1])) for k, v in raw.items()}
        except (ValueError, TypeError, IndexError) as e:
            raise AppError(f"Invalid conversions JSON: {e}") from e

    media = await service.attach_media(
        db, model_type=model_type, model_id=model_id, file=file,
        collection=collection, conversions=parsed_conversions, actor_id=user.id,
    )
    return ResponseModel(data=MediaOut.model_validate(media), msg="Media uploaded; conversions queued")


@router.get("/for-entity", response_model=ResponseModel[list[MediaOut]])
async def list_entity_media(
    _: CurrentUser,
    db: DBSession,
    model_type: str = Query(...),
    model_id: str = Query(...),
    collection: str | None = Query(None),
):
    media = await service.list_media_for_entity(db, model_type, model_id, collection)
    return ResponseModel(data=[MediaOut.model_validate(m) for m in media])


@router.delete("/{media_id}", response_model=ResponseModel[None])
async def delete_media(user: CurrentUser, db: DBSession, media_id: int):
    await service.delete_media(db, media_id, actor_id=user.id)
    return ResponseModel(data=None, msg="Media soft-deleted")
