"""Generic search endpoint (mounted at /api/search).

    GET /api/search/zoho_organizations?q=acme&filter=address_country:India

Meilisearch ranks; Postgres hydrates (fresh rows, soft-delete filtered,
relevance order preserved) — see builder.py. Only indexes registered in
registry.py are searchable; filter fields are validated against the
entity's declared filterable attributes, so a typo'd or undeclared field
is a 400 here instead of an opaque Meilisearch error.
"""

from fastapi import APIRouter, Query

from app.common.exception.errors import AppError, NotFoundError
from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.search.builder import ScoutBuilder
from app.modules.search.registry import SEARCHABLE_ENTITIES
from app.modules.search.schema import SearchResponse
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.get("/indexes", response_model=ResponseModel[list[str]])
async def list_indexes(_: CurrentUser):
    """The searchable indexes this deployment exposes."""
    return ResponseModel(data=sorted(SEARCHABLE_ENTITIES))


@router.get("/{index_name}", response_model=ResponseModel[SearchResponse])
async def search(
    _: CurrentUser,
    db: DBSession,
    index_name: str,
    q: str = Query("", max_length=200, description="Full-text query (empty = browse)"),
    filter: list[str] = Query(  # noqa: A002 - mirrors Meilisearch's parameter name
        default=[],
        description="Repeatable `field:value` pairs, ANDed. Field must be "
        "declared filterable for the index.",
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    entity = SEARCHABLE_ENTITIES.get(index_name)
    if entity is None:
        raise NotFoundError(f"'{index_name}' is not a searchable index")

    builder = ScoutBuilder(entity.resolve_model(), q).limit(limit).offset(offset)
    for pair in filter:
        field, sep, value = pair.partition(":")
        if not sep or not value:
            raise AppError(f"Malformed filter '{pair}' — expected field:value")
        if field not in entity.filterable:
            raise AppError(
                f"'{field}' is not filterable on '{index_name}' "
                f"(allowed: {', '.join(entity.filterable)})"
            )
        # Coerce booleans so `is_org_active:true` filters correctly.
        coerced: object = {"true": True, "false": False}.get(value.lower(), value)
        builder.where(field, coerced)

    rows = await builder.get(db)
    out_schema = entity.resolve_schema()
    return ResponseModel(
        data=SearchResponse(
            index=index_name,
            query=q,
            limit=limit,
            offset=offset,
            count=len(rows),
            hits=[out_schema.model_validate(r).model_dump(mode="json") for r in rows],
        )
    )
