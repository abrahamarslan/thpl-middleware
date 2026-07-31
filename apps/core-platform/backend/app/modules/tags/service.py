"""Tags business logic (service layer)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.tags import crud, schema
from app.modules.tags.model import Tag


async def create_tag(db: AsyncSession, tag_in: schema.TagCreate, *, actor_id: int | None = None) -> Tag:
    tag = await crud.create_tag(db, tag_in)
    await record_activity(
        db, action="tag_created", actor_id=actor_id,
        subject_type="Tag", subject_id=tag.id,
        changes={"after": tag_in.model_dump()},
    )
    return tag


async def update_tag(db: AsyncSession, tag_id: int, tag_in: schema.TagUpdate, *, actor_id: int | None = None) -> Tag:
    tag = await crud.get_tag(db, tag_id)
    if tag is None:
        raise NotFoundError(f"Tag {tag_id} not found")
    tag = await crud.update_tag(db, tag, tag_in)
    await record_activity(
        db, action="tag_updated", actor_id=actor_id,
        subject_type="Tag", subject_id=tag.id,
        changes={"after": tag_in.model_dump(exclude_unset=True)},
    )
    return tag


async def delete_tag(db: AsyncSession, tag_id: int, *, actor_id: int | None = None) -> None:
    tag = await crud.get_tag(db, tag_id)
    if tag is None:
        raise NotFoundError(f"Tag {tag_id} not found")
    await crud.delete_tag(db, tag)
    await record_activity(
        db, action="tag_deleted", actor_id=actor_id, subject_type="Tag", subject_id=tag_id,
    )


async def sync_tags_for_entity(
    db: AsyncSession, sync_req: schema.SyncTagsRequest, *, actor_id: int | None = None
) -> None:
    # Validate every id in ONE query before touching the pivot.
    found = {t.id for t in await crud.get_tags(db, sync_req.tag_ids)}
    missing = set(sync_req.tag_ids) - found
    if missing:
        raise NotFoundError(f"Tags not found: {sorted(missing)}")

    await crud.sync_entity_tags(db, sync_req.taggable_id, sync_req.taggable_type, sync_req.tag_ids)
    await record_activity(
        db, action="tags_synced", actor_id=actor_id,
        subject_type=sync_req.taggable_type, subject_id=sync_req.taggable_id,
        changes={"synced_tag_ids": sync_req.tag_ids},
    )
