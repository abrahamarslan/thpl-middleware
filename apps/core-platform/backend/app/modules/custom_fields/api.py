"""HTTP endpoints for the custom-fields engine (mounted at /api/custom-fields).

Static paths are declared before ``/{ref}``. Definitions and values are
addressed by their public uuid (or numeric id for definitions).
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.custom_fields import service
from app.modules.custom_fields.schema import (
    DataTypeOut,
    FieldDefinitionCreate,
    FieldDefinitionOut,
    FieldDefinitionSlimOut,
    FieldDefinitionUpdate,
    FieldValueOut,
    FieldValueSet,
    FieldValueSync,
)
from app.modules.rbac.deps import Perm, org_of
from app.modules.users.deps import CurrentUser

router = APIRouter()

_M = "custom_fields"


@router.get("/data-types", response_model=ResponseModel[list[DataTypeOut]])
async def list_data_types(_: CurrentUser, db: DBSession):
    rows = await service.list_data_types(db)
    return ResponseModel(data=[DataTypeOut.model_validate(r) for r in rows])


# ── field definitions ────────────────────────────────────────────────────────

@router.get("/definitions", response_model=ResponseModel[list[FieldDefinitionSlimOut]])
async def list_definitions(
    _: CurrentUser, db: DBSession,
    owner_type_code: str | None = Query(None, max_length=64),
    is_active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_definitions(
        db, owner_type_code=owner_type_code, is_active=is_active, page=page, page_size=page_size,
    )
    return ResponseModel(data=[FieldDefinitionSlimOut.model_validate(r) for r in rows])


@router.post("/definitions", response_model=ResponseModel[FieldDefinitionOut], status_code=201)
async def create_definition(user: Perm("extfields.definition:create"), db: DBSession, body: FieldDefinitionCreate):
    definition = await service.create_definition(db, body, actor_id=user.id)
    return ResponseModel.ok(data=FieldDefinitionOut.model_validate(definition), module=_M,
                            msg="Custom field created", name=definition.api_name)


@router.get("/definitions/{ref}", response_model=ResponseModel[FieldDefinitionOut])
async def get_definition(_: CurrentUser, db: DBSession, ref: str):
    definition = await service.get_definition(db, ref)
    return ResponseModel(data=FieldDefinitionOut.model_validate(definition))


@router.patch("/definitions/{ref}", response_model=ResponseModel[FieldDefinitionOut])
async def update_definition(user: Perm("extfields.definition:update", target=org_of("app.modules.custom_fields.model:FieldDefinition")), db: DBSession, ref: str, body: FieldDefinitionUpdate):
    definition = await service.update_definition(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=FieldDefinitionOut.model_validate(definition), module=_M,
                            msg="Custom field updated", name=definition.api_name)


@router.delete("/definitions/{ref}", response_model=ResponseModel[None])
async def delete_definition(admin: Perm("extfields.definition:delete", target=org_of("app.modules.custom_fields.model:FieldDefinition")), db: DBSession, ref: str,
                            reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_definition(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg="Custom field deleted", name=ref)


# ── field values ─────────────────────────────────────────────────────────────

@router.get("/values", response_model=ResponseModel[list[FieldValueOut]])
async def list_values(
    _: CurrentUser, db: DBSession,
    owner_type_code: str = Query(..., min_length=1, max_length=64),
    owner_id: int = Query(..., ge=1),
):
    rows = await service.list_values_for_owner(db, owner_type_code, owner_id)
    return ResponseModel(data=[FieldValueOut.model_validate(r) for r in rows])


@router.post("/values", response_model=ResponseModel[FieldValueOut])
async def set_value(user: Perm("extfields.value:update"), db: DBSession, body: FieldValueSet):
    value = await service.set_value(db, body, actor_id=user.id)
    return ResponseModel.ok(data=FieldValueOut.model_validate(value), module=_M, msg="Custom field value saved")


@router.post("/values/sync", response_model=ResponseModel[list[FieldValueOut]])
async def sync_values(user: Perm("extfields.value:update"), db: DBSession, body: FieldValueSync):
    rows = await service.sync_values(db, body, actor_id=user.id)
    return ResponseModel.ok(data=[FieldValueOut.model_validate(r) for r in rows], module=_M,
                            msg="Custom field values synced")


@router.post("/values/erase-pii", response_model=ResponseModel[dict])
async def erase_pii(
    admin: Perm("extfields.value:manage"), db: DBSession,
    owner_type_code: str = Query(..., min_length=1, max_length=64),
    owner_id: int = Query(..., ge=1),
    reason: str = Query(..., min_length=3, max_length=500),
):
    """DPDP erasure of every PII-classified value of one owner."""
    erased = await service.erase_pii_values_for_owner(
        db, owner_type_code, owner_id, reason=reason, actor_id=admin.id,
    )
    return ResponseModel.ok(data={"erased_values": erased}, module=_M, msg="PII values erased")


@router.delete("/values/{ref}", response_model=ResponseModel[None])
async def delete_value(admin: Perm("extfields.value:delete", target=org_of("app.modules.custom_fields.model:FieldValue")), db: DBSession, ref: str,
                       reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_value(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg="Custom field value deleted", name=ref)