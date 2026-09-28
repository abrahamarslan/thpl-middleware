"""HTTP endpoints for taxonomies, categories and assignments.

Three routers, mounted separately (the ``geo`` multi-router precedent):

| Prefix | What |
|---|---|
| ``/api/taxonomies`` | trees + their entity-type whitelist |
| ``/api/categories`` | tree nodes (Slim list, Fat detail) |
| ``/api/categorizables`` | polymorphic assignments |

``{ref}`` is the public uuid (preferred), the numeric id, or — for taxonomies
and categories — the slug. Writes need an organization; it is resolved from
``X-Organization-Id`` / ``X-Organization-Code`` or the tenant default.
"""

import datetime as dt

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.categories import service
from app.modules.categories.enums import TaxonomyStatus
from app.modules.categories.schema import (
    CategoryCreate,
    CategoryMove,
    CategoryOut,
    CategorySlimOut,
    CategoryUpdate,
    CategorizableCreate,
    CategorizableOut,
    CategorizableSyncRequest,
    TaxonomyCreate,
    TaxonomyEntityTypeOut,
    TaxonomyEntityTypesReplace,
    TaxonomyOut,
    TaxonomySlimOut,
    TaxonomyUpdate,
)
from app.modules.rbac.deps import Perm, org_of
from app.modules.users.deps import CurrentUser

taxonomies_router = APIRouter()
categories_router = APIRouter()
categorizables_router = APIRouter()

_M = "categories"


# ── taxonomies ────────────────────────────────────────────────────────────────

@taxonomies_router.get("", response_model=ResponseModel[list[TaxonomySlimOut]])
async def list_taxonomies(
    _: CurrentUser, db: DBSession,
    q: str | None = Query(None, max_length=200),
    status: TaxonomyStatus | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_taxonomies(
        db, q=q, status=status.value if status else None, page=page, page_size=page_size,
    )
    return ResponseModel(data=[TaxonomySlimOut.model_validate(r) for r in rows])


@taxonomies_router.post("", response_model=ResponseModel[TaxonomyOut], status_code=201)
async def create_taxonomy(user: Perm("core.taxonomy:create"), db: DBSession, body: TaxonomyCreate):
    row = await service.create_taxonomy(db, body, actor_id=user.id)
    return ResponseModel.ok(data=TaxonomyOut.model_validate(row), module=_M,
                            msg_key="taxonomy_created", msg="Taxonomy created", name=row.slug)


@taxonomies_router.get("/{ref}", response_model=ResponseModel[TaxonomyOut])
async def get_taxonomy(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=TaxonomyOut.model_validate(await service.get_taxonomy(db, ref)))


@taxonomies_router.patch("/{ref}", response_model=ResponseModel[TaxonomyOut])
async def update_taxonomy(user: Perm("core.taxonomy:update", target=org_of("app.modules.categories.model:Taxonomy", "slug")), db: DBSession, ref: str, body: TaxonomyUpdate):
    row = await service.update_taxonomy(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=TaxonomyOut.model_validate(row), module=_M,
                            msg_key="taxonomy_updated", msg="Taxonomy updated", name=row.slug)


@taxonomies_router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_taxonomy(admin: Perm("core.taxonomy:delete", target=org_of("app.modules.categories.model:Taxonomy", "slug")), db: DBSession, ref: str,
                          reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_taxonomy(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="taxonomy_deleted",
                            msg="Taxonomy deleted", name=ref)


@taxonomies_router.get("/{ref}/entity-types", response_model=ResponseModel[list[TaxonomyEntityTypeOut]])
async def list_taxonomy_entity_types(_: CurrentUser, db: DBSession, ref: str):
    rows = await service.list_taxonomy_entity_types(db, ref)
    return ResponseModel(data=[TaxonomyEntityTypeOut.model_validate(r) for r in rows])


@taxonomies_router.put("/{ref}/entity-types", response_model=ResponseModel[list[TaxonomyEntityTypeOut]])
async def replace_taxonomy_entity_types(user: Perm("core.taxonomy:update", target=org_of("app.modules.categories.model:Taxonomy", "slug")), db: DBSession, ref: str,
                                        body: TaxonomyEntityTypesReplace):
    rows = await service.replace_taxonomy_entity_types(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=[TaxonomyEntityTypeOut.model_validate(r) for r in rows], module=_M,
                            msg_key="taxonomy_entity_types_replaced", msg="Whitelist updated", name=ref)


# ── categories ────────────────────────────────────────────────────────────────

@categories_router.get("", response_model=ResponseModel[list[CategorySlimOut]])
async def list_categories(
    _: CurrentUser, db: DBSession,
    taxonomy_id: int | None = Query(None, ge=1),
    parent_id: int | None = Query(None, ge=1),
    is_active: bool | None = Query(None),
    q: str | None = Query(None, max_length=200),
    view: str | None = Query(None, pattern="^(tree|flat)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
):
    rows = await service.list_categories(
        db, taxonomy_id=taxonomy_id, parent_id=parent_id, is_active=is_active,
        q=q, view=view, page=page, page_size=page_size,
    )
    return ResponseModel(data=[CategorySlimOut.model_validate(r) for r in rows])


@categories_router.post("", response_model=ResponseModel[CategoryOut], status_code=201)
async def create_category(user: Perm("core.category:create"), db: DBSession, body: CategoryCreate):
    row = await service.create_category(db, body, actor_id=user.id)
    return ResponseModel.ok(data=CategoryOut.model_validate(row), module=_M,
                            msg_key="category_created", msg="Category created", name=row.name)


@categories_router.get("/{ref}", response_model=ResponseModel[CategoryOut])
async def get_category(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=CategoryOut.model_validate(await service.get_category(db, ref)))


@categories_router.patch("/{ref}", response_model=ResponseModel[CategoryOut])
async def update_category(user: Perm("core.category:update", target=org_of("app.modules.categories.model:Category", "slug")), db: DBSession, ref: str, body: CategoryUpdate):
    row = await service.update_category(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=CategoryOut.model_validate(row), module=_M,
                            msg_key="category_updated", msg="Category updated", name=row.name)


@categories_router.post("/{ref}/move", response_model=ResponseModel[CategoryOut])
async def move_category(user: Perm("core.category:update", target=org_of("app.modules.categories.model:Category", "slug")), db: DBSession, ref: str, body: CategoryMove):
    row = await service.move_category(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=CategoryOut.model_validate(row), module=_M,
                            msg_key="category_moved", msg="Category moved", name=row.name)


@categories_router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_category(admin: Perm("core.category:delete", target=org_of("app.modules.categories.model:Category", "slug")), db: DBSession, ref: str,
                          reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_category(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="category_deleted",
                            msg="Category deleted", name=ref)


# ── categorizables ────────────────────────────────────────────────────────────

@categorizables_router.get("", response_model=ResponseModel[list[CategorizableOut]])
async def list_categorizables(
    _: CurrentUser, db: DBSession,
    category_id: int | None = Query(None, ge=1),
    categorizable_type: str | None = Query(None, max_length=64),
    categorizable_id: int | None = Query(None, ge=1),
    taxonomy_id: int | None = Query(None, ge=1),
    valid_at: dt.datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
):
    rows = await service.list_categorizables(
        db, category_id=category_id, categorizable_type=categorizable_type,
        categorizable_id=categorizable_id, taxonomy_id=taxonomy_id,
        valid_at=valid_at, page=page, page_size=page_size,
    )
    return ResponseModel(data=[CategorizableOut.model_validate(r) for r in rows])


@categorizables_router.post("/sync", response_model=ResponseModel[list[CategorizableOut]])
async def sync_categorizables(user: Perm("core.categorizable:assign"), db: DBSession, body: CategorizableSyncRequest):
    rows = await service.sync_categorizables(db, body, actor_id=user.id)
    return ResponseModel.ok(data=[CategorizableOut.model_validate(r) for r in rows], module=_M,
                            msg_key="categories_synced", msg="Assignments synced",
                            name=f"{body.categorizable_type}:{body.categorizable_id}")


@categorizables_router.post("", response_model=ResponseModel[CategorizableOut], status_code=201)
async def assign_category(user: Perm("core.categorizable:assign"), db: DBSession, body: CategorizableCreate):
    row = await service.assign_category(db, body, actor_id=user.id)
    return ResponseModel.ok(data=CategorizableOut.model_validate(row), module=_M,
                            msg_key="category_assigned", msg="Category assigned", name=str(row.uuid))


@categorizables_router.delete("/{ref}", response_model=ResponseModel[None])
async def unassign_categorizable(admin: Perm("core.categorizable:assign", target=org_of("app.modules.categories.model:Categorizable")), db: DBSession, ref: str,
                                 reason: str = Query(..., min_length=3, max_length=500)):
    await service.unassign_categorizable(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="category_unassigned",
                            msg="Assignment removed", name=ref)


# Status vocabulary is imported for the module's own swagger enum surface.
__all__ = ["categories_router", "categorizables_router", "taxonomies_router"]
