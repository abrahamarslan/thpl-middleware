"""Tags module (integration: real Postgres) — CRUD, sync pivot, eager loads."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.modules.documents.model import Document
from app.modules.tags import crud, schema, service
from app.modules.tags.model import Tag, Taggable


async def _tag(db, name="Urgent", type_=None) -> Tag:
    return await crud.create_tag(
        db, schema.TagCreate(name={"en": name}, slug={"en": name.lower()}, type=type_)
    )


async def test_create_and_list_by_type(db):
    await _tag(db, "Urgent", "badges")
    await _tag(db, "VIP", "badges")
    await _tag(db, "Chennai", "regions")

    badges = await crud.list_tags(db, "badges")
    assert {t.name["en"] for t in badges} == {"Urgent", "VIP"}
    assert len(await crud.list_tags(db)) == 3


async def test_sync_is_idempotent_replace(db):
    t1, t2, t3 = [await _tag(db, n) for n in ("A", "B", "C")]

    await crud.sync_entity_tags(db, "42", "Product", [t1.id, t2.id])
    await crud.sync_entity_tags(db, "42", "Product", [t2.id, t3.id, t3.id])  # dupes de-duped

    pivot = (await db.scalars(select(Taggable).where(Taggable.taggable_id == "42"))).all()
    assert {p.tag_id for p in pivot} == {t2.id, t3.id}


async def test_sync_validates_tag_ids(db):
    from app.common.exception.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await service.sync_tags_for_entity(
            db, schema.SyncTagsRequest(taggable_id="1", taggable_type="X", tag_ids=[99999])
        )


async def test_has_tags_mixin_eager_loads_across_uuid_pk(db):
    """Document has a UUID PK — the cast(id, String) join must still work."""
    doc = Document(file_name="a.pdf", file_type="pdf", file_size=10)
    db.add(doc)
    await db.flush()

    tag = await _tag(db, "Reviewed")
    await crud.sync_entity_tags(db, str(doc.id), "Document", [tag.id])

    loaded = await db.scalar(
        select(Document).where(Document.id == doc.id).options(selectinload(Document.tags))
    )
    assert [t.name["en"] for t in loaded.tags] == ["Reviewed"]


async def test_deleting_tag_cascades_pivot_rows(db):
    tag = await _tag(db, "Ephemeral")
    await crud.sync_entity_tags(db, "7", "Product", [tag.id])
    await crud.delete_tag(db, tag)

    assert (await db.scalars(select(Taggable).where(Taggable.tag_id == tag.id))).all() == []
