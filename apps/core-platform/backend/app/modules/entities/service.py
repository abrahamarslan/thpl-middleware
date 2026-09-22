"""Entity-registry business logic.

The catalogue is read-only through the API; aliases are written here. The
target's existence is proved by ``core.check_entity_alias()`` (a deferrable
constraint trigger) at COMMIT, so this service only has to reject an
unregistered type early with a clean 422 instead of a raw FK violation.
"""

from __future__ import annotations

import uuid as uuid_lib

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.entities import crud
from app.modules.entities.model import EntityAlias, EntityType
from app.modules.entities.schema import EntityAliasCreate

logger = structlog.get_logger("app.entities")


class EntityRuleError(AppError):
    status_code = 422
    code = "entity_rule_violation"


def _stringify(values: dict) -> dict:
    return {k: (v.value if hasattr(v, "value") else v) for k, v in values.items()}


async def list_entity_types(db: AsyncSession) -> list[EntityType]:
    return await crud.list_entity_types(db)


async def list_aliases(
    db: AsyncSession, *, entity_type: str | None = None, entity_id: int | None = None,
    page: int = 1, page_size: int = 100,
) -> list[EntityAlias]:
    return await crud.list_aliases(db, entity_type=entity_type, entity_id=entity_id,
                                   page=page, page_size=page_size)


async def create_alias(
    db: AsyncSession, body: EntityAliasCreate, *, actor_id: int | None = None,
) -> EntityAlias:
    if await crud.get_entity_type(db, body.entity_type) is None:
        raise EntityRuleError(
            f"'{body.entity_type}' is not a registered entity type",
            data={"hint": "GET /api/entities/types lists the registered codes"},
        )
    alias = await crud.create_alias(db, {
        **_stringify(body.model_dump()),
        "alias": body.alias.strip(),
    })
    await record_activity(
        db, action="entity_alias_created", actor_id=actor_id,
        subject_type="EntityAlias", subject_id=str(alias.uuid),
        changes={"after": {"entity_type": alias.entity_type, "entity_id": alias.entity_id,
                           "alias": alias.alias}},
    )
    logger.info("entity_alias.created", entity_type=alias.entity_type, entity_id=alias.entity_id)
    return alias


async def delete_alias(
    db: AsyncSession, alias_ref: str, *, reason: str, actor_id: int | None = None,
) -> None:
    try:
        alias_uuid = uuid_lib.UUID(alias_ref)
    except ValueError:
        raise NotFoundError(f"Alias '{alias_ref}' not found") from None
    alias = await crud.get_alias(db, alias_uuid)
    if alias is None:
        raise NotFoundError(f"Alias '{alias_ref}' not found")
    alias.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="entity_alias_deleted", actor_id=actor_id,
        subject_type="EntityAlias", subject_id=str(alias.uuid), context={"reason": reason},
    )
