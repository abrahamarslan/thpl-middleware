"""HTTP endpoints for tags (mounted at /api/tags)."""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.tags import crud, schema, service
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.get("", response_model=ResponseModel[list[schema.TagOut]])
async def list_tags(_: CurrentUser, db: DBSession, type: str | None = Query(None)):
    return ResponseModel(data=[schema.TagOut.model_validate(t) for t in await crud.list_tags(db, type)])


@router.post("", response_model=ResponseModel[schema.TagOut], status_code=201)
async def create_tag(user: CurrentUser, db: DBSession, tag_in: schema.TagCreate):
    tag = await service.create_tag(db, tag_in, actor_id=user.id)
    return ResponseModel(data=schema.TagOut.model_validate(tag), msg="Tag created")


@router.post("/sync", response_model=ResponseModel[None])
async def sync_tags(user: CurrentUser, db: DBSession, sync_req: schema.SyncTagsRequest):
    """Replace the full tag set of any entity (idempotent)."""
    await service.sync_tags_for_entity(db, sync_req, actor_id=user.id)
    return ResponseModel(data=None, msg="Tags synced")


@router.patch("/{tag_id}", response_model=ResponseModel[schema.TagOut])
async def update_tag(user: CurrentUser, db: DBSession, tag_id: int, tag_in: schema.TagUpdate):
    tag = await service.update_tag(db, tag_id, tag_in, actor_id=user.id)
    return ResponseModel(data=schema.TagOut.model_validate(tag), msg="Tag updated")


@router.delete("/{tag_id}", response_model=ResponseModel[None])
async def delete_tag(user: CurrentUser, db: DBSession, tag_id: int):
    await service.delete_tag(db, tag_id, actor_id=user.id)
    return ResponseModel(data=None, msg="Tag deleted")
