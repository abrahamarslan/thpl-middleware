"""Data access for tags (crud layer — no business logic)."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tags.model import Tag, Taggable
from app.modules.tags.schema import TagCreate, TagUpdate


async def get_tag(db: AsyncSession, tag_id: int) -> Tag | None:
    return await db.get(Tag, tag_id)


async def get_tags(db: AsyncSession, tag_ids: list[int]) -> list[Tag]:
    if not tag_ids:
        return []
    return list((await db.scalars(select(Tag).where(Tag.id.in_(tag_ids)))).all())


async def list_tags(db: AsyncSession, tag_type: str | None = None) -> list[Tag]:
    stmt = select(Tag).order_by(Tag.order_column.asc(), Tag.id.asc())
    if tag_type:
        stmt = stmt.where(Tag.type == tag_type)
    return list((await db.scalars(stmt)).all())


async def create_tag(db: AsyncSession, tag_in: TagCreate) -> Tag:
    tag = Tag(**tag_in.model_dump())
    db.add(tag)
    await db.flush()
    return tag


async def update_tag(db: AsyncSession, tag: Tag, tag_in: TagUpdate) -> Tag:
    for field, value in tag_in.model_dump(exclude_unset=True).items():
        setattr(tag, field, value)
    await db.flush()
    return tag


async def delete_tag(db: AsyncSession, tag: Tag) -> None:
    await db.delete(tag)  # pivot rows cascade at the DB level
    await db.flush()


async def sync_entity_tags(
    db: AsyncSession, taggable_id: str, taggable_type: str, tag_ids: list[int]
) -> None:
    """Replace the entity's tag set: clear then bulk-insert (idempotent)."""
    await db.execute(
        delete(Taggable).where(
            Taggable.taggable_id == taggable_id,
            Taggable.taggable_type == taggable_type,
        )
    )
    if tag_ids:
        db.add_all(
            Taggable(tag_id=tid, taggable_id=taggable_id, taggable_type=taggable_type)
            for tid in dict.fromkeys(tag_ids)  # de-dupe, preserve order
        )
    await db.flush()
