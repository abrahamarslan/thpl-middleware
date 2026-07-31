"""Data access for documents (crud layer — no business logic)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.documents.model import Document


async def create_document(db: AsyncSession, values: dict) -> Document:
    document = Document(**values)
    db.add(document)
    await db.flush()
    return document


async def get_document(db: AsyncSession, document_id: UUID) -> Document | None:
    stmt = (
        select(Document)
        .where(Document.id == document_id)
        .options(selectinload(Document.tags))
        .limit(1)
    )
    return await db.scalar(stmt)


async def list_documents_for_entity(
    db: AsyncSession, entity_type: str, entity_id: str
) -> list[Document]:
    stmt = (
        select(Document)
        .where(
            Document.documentable_type == entity_type,
            Document.documentable_id == entity_id,
        )
        .options(selectinload(Document.tags))
        .order_by(Document.display_order.asc(), Document.created_at.desc())
    )
    return list((await db.scalars(stmt)).all())


async def attach_documents_to_entity(
    db: AsyncSession,
    entity_type: str,
    entity_id: str,
    document_ids: list[UUID],
    *,
    metadata_by_id: dict[UUID, dict] | None = None,
) -> list[Document]:
    """Point existing documents at an owner (e.g. attach uploads to an Email).

    Optional per-document metadata (e.g. {"is_inline": True, "content_id":
    "cid:logo"}) is merged into Document.metadata_.
    """
    if not document_ids:
        return []
    docs = list((await db.scalars(select(Document).where(Document.id.in_(document_ids)))).all())
    for doc in docs:
        doc.documentable_type = entity_type
        doc.documentable_id = entity_id
        extra = (metadata_by_id or {}).get(doc.id)
        if extra:
            doc.metadata_ = {**(doc.metadata_ or {}), **extra}
    await db.flush()
    return docs
