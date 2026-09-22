"""HTTP endpoints for the ``core`` entity registry (mounted at /api/entities)."""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.entities import service
from app.modules.entities.schema import EntityAliasCreate, EntityAliasOut, EntityTypeOut
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.get("/types", response_model=ResponseModel[list[EntityTypeOut]])
async def list_entity_types(_: CurrentUser, db: DBSession):
    rows = await service.list_entity_types(db)
    return ResponseModel(data=[EntityTypeOut.model_validate(r) for r in rows])


@router.get("/aliases", response_model=ResponseModel[list[EntityAliasOut]])
async def list_aliases(
    _: CurrentUser, db: DBSession,
    entity_type: str | None = Query(None, max_length=64),
    entity_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_aliases(db, entity_type=entity_type, entity_id=entity_id,
                                      page=page, page_size=page_size)
    return ResponseModel(data=[EntityAliasOut.model_validate(r) for r in rows])


@router.post("/aliases", response_model=ResponseModel[EntityAliasOut], status_code=201)
async def create_alias(user: CurrentUser, db: DBSession, body: EntityAliasCreate):
    alias = await service.create_alias(db, body, actor_id=user.id)
    return ResponseModel.ok(data=EntityAliasOut.model_validate(alias), module="entities",
                            msg_key="entity_alias_created", msg="Entity alias created", name=alias.alias)


@router.delete("/aliases/{ref}", response_model=ResponseModel[None])
async def delete_alias(admin: TenantAdmin, db: DBSession, ref: str,
                       reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_alias(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module="entities", msg_key="entity_alias_deleted",
                            msg="Entity alias deleted", name=ref)
