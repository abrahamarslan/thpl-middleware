"""Organizations API — mounted at /api/organizations (tenant-scoped).

Every route sees only the caller's tenant (app/database/tenancy.py). ``{ref}``
is the organization uuid (preferred), its ``org_code`` or its id.

| Route | Who | What |
|---|---|---|
| ``GET ""`` | member | flat list (``status``, ``org_type``, ``q``, ``roots_only``) |
| ``GET /tree`` | member | the whole tree, nested |
| ``GET /{ref}`` · ``/children`` · ``/subtree`` · ``/ancestors`` | member | one node and its surroundings |
| ``POST ""`` | tenant admin | create (``parent`` = parent uuid) |
| ``PATCH /{ref}`` | tenant admin | update profile (optimistic lock: ``row_version``) |
| ``POST /{ref}/move`` | tenant admin | re-parent (subtree follows) |
| ``POST /{ref}/status`` | tenant admin | active · suspended · archived (with reason) |
| ``DELETE /{ref}?reason=`` | tenant admin | soft delete a leaf |
| ``POST /sync`` | tenant admin | pull the Zoho organization(s) into the tree now |
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.organizations import service
from app.modules.organizations.schema import (
    OrganizationCreate,
    OrganizationMove,
    OrganizationNode,
    OrganizationOut,
    OrganizationSlim,
    OrganizationStatusChange,
    OrganizationUpdate,
)
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser

router = APIRouter()
_M = "organizations"


@router.get("", response_model=ResponseModel[list[OrganizationSlim]])
async def list_organizations(
    _: CurrentUser, db: DBSession,
    status: str | None = Query(None, pattern="^(active|suspended|archived)$"),
    org_type: str | None = Query(None, pattern="^(holding|legal_entity|branch|solo)$"),
    q: str | None = Query(None, max_length=100),
    roots_only: bool = Query(False),
):
    rows = await service.list_organizations(db, status=status, org_type=org_type, q=q, roots_only=roots_only)
    return ResponseModel.ok(data=[OrganizationSlim.model_validate(r) for r in rows])


@router.get("/tree", response_model=ResponseModel[list[OrganizationNode]])
async def tree(_: CurrentUser, db: DBSession, include_archived: bool = Query(False)):
    rows = await service.list_organizations(db)
    if not include_archived:
        rows = [r for r in rows if r.status != "archived"]
    return ResponseModel.ok(data=service.build_tree(rows))


@router.post("/sync", response_model=ResponseModel[dict], status_code=202)
async def sync_from_zoho(_: TenantAdmin, mode: str | None = Query(None, pattern="^(full|index)$")):
    return ResponseModel.ok(data={"task_id": service.trigger_zoho_sync(mode)}, module=_M, msg_key="sync_queued")


@router.get("/{ref}", response_model=ResponseModel[OrganizationOut])
async def get_organization(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel.ok(data=OrganizationOut.model_validate(await service.get_organization(db, ref)))


@router.get("/{ref}/children", response_model=ResponseModel[list[OrganizationSlim]])
async def get_children(_: CurrentUser, db: DBSession, ref: str):
    org = await service.get_organization(db, ref)
    return ResponseModel.ok(data=[OrganizationSlim.model_validate(r) for r in await service.children(db, org)])


@router.get("/{ref}/subtree", response_model=ResponseModel[list[OrganizationNode]])
async def get_subtree(_: CurrentUser, db: DBSession, ref: str):
    org = await service.get_organization(db, ref)
    return ResponseModel.ok(data=service.build_tree(await service.subtree(db, org)))


@router.get("/{ref}/ancestors", response_model=ResponseModel[list[OrganizationSlim]])
async def get_ancestors(_: CurrentUser, db: DBSession, ref: str):
    org = await service.get_organization(db, ref)
    return ResponseModel.ok(data=[OrganizationSlim.model_validate(r) for r in await service.ancestors(db, org)])


@router.post("", response_model=ResponseModel[OrganizationOut], status_code=201)
async def create_organization(admin: TenantAdmin, db: DBSession, body: OrganizationCreate):
    org = await service.create_organization(db, body, actor_id=admin.id)
    return ResponseModel.ok(data=OrganizationOut.model_validate(org), module=_M, msg_key="created", code=org.org_code)


@router.patch("/{ref}", response_model=ResponseModel[OrganizationOut])
async def update_organization(admin: TenantAdmin, db: DBSession, ref: str, body: OrganizationUpdate):
    org = await service.update_organization(db, ref, body, actor_id=admin.id)
    return ResponseModel.ok(data=OrganizationOut.model_validate(org), module=_M, msg_key="updated", code=org.org_code)


@router.post("/{ref}/move", response_model=ResponseModel[OrganizationOut])
async def move_organization(admin: TenantAdmin, db: DBSession, ref: str, body: OrganizationMove):
    org = await service.move_organization(db, ref, body, actor_id=admin.id)
    return ResponseModel.ok(data=OrganizationOut.model_validate(org), module=_M, msg_key="moved", code=org.org_code)


@router.post("/{ref}/status", response_model=ResponseModel[OrganizationOut])
async def change_status(admin: TenantAdmin, db: DBSession, ref: str, body: OrganizationStatusChange):
    org = await service.change_status(db, ref, body, actor_id=admin.id)
    return ResponseModel.ok(data=OrganizationOut.model_validate(org), module=_M, msg_key="status_changed",
                            code=org.org_code, status=org.status)


@router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_organization(admin: TenantAdmin, db: DBSession, ref: str,
                              reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_organization(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="deleted", code=ref)
