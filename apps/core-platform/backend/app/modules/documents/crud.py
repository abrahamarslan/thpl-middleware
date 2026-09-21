"""Data access for documents (crud layer — no business logic).

Documents are addressed by their public ``uuid``; the BigInteger ``id`` never
leaves the database layer. Reads that follow a write pass ``refresh=True`` so
the viewonly ``files`` / ``links`` collections reflect what was just written.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.documents.enums import DocumentLinkRole
from app.modules.documents.model import (
    Document,
    DocumentFile,
    DocumentLink,
    DocumentType,
    DocumentVerificationLog,
)


# ── catalog ─────────────────────────────────────────────────────────────────

async def list_document_types(
    db: AsyncSession, *, category: str | None = None, include_deactivated: bool = False,
) -> list[DocumentType]:
    stmt = select(DocumentType).order_by(DocumentType.sort_order, DocumentType.code)
    if category:
        stmt = stmt.where(DocumentType.category == category)
    if not include_deactivated:
        stmt = stmt.where(DocumentType.deactivation_date.is_(None))
    return list((await db.scalars(stmt)).all())


async def get_document_type_by_code(db: AsyncSession, code: str) -> DocumentType | None:
    return await db.scalar(select(DocumentType).where(DocumentType.code == code))


# ── documents ───────────────────────────────────────────────────────────────

async def create_document(db: AsyncSession, values: dict) -> Document:
    document = Document(**values)
    db.add(document)
    await db.flush()
    return document


async def get_document(db: AsyncSession, document_uuid: UUID, *, refresh: bool = False) -> Document | None:
    stmt = (
        select(Document)
        .where(Document.uuid == document_uuid)
        .options(selectinload(Document.tags))
        .limit(1)
    )
    if refresh:
        stmt = stmt.execution_options(populate_existing=True)
    return await db.scalar(stmt)


async def get_documents_by_uuid(db: AsyncSession, document_uuids: list[UUID]) -> list[Document]:
    if not document_uuids:
        return []
    stmt = select(Document).where(Document.uuid.in_(document_uuids)).options(selectinload(Document.tags))
    return list((await db.scalars(stmt)).all())


async def list_documents_for_entity(
    db: AsyncSession, linkable_type: str, linkable_id: int, *, roles: list[str] | None = None,
    latest_only: bool = True,
) -> list[Document]:
    stmt = (
        select(Document)
        .join(DocumentLink, DocumentLink.document_id == Document.id)
        .where(
            DocumentLink.linkable_type == linkable_type,
            DocumentLink.linkable_id == linkable_id,
        )
        .options(selectinload(Document.tags))
        .order_by(DocumentLink.sort_order.asc(), Document.created_at.desc())
    )
    if roles:
        stmt = stmt.where(DocumentLink.link_role.in_(roles))
    if latest_only:
        stmt = stmt.where(Document.is_latest_version.is_(True))
    return list((await db.scalars(stmt)).unique().all())


# ── files ───────────────────────────────────────────────────────────────────

async def create_file(db: AsyncSession, values: dict) -> DocumentFile:
    file = DocumentFile(**values)
    db.add(file)
    await db.flush()
    return file


async def find_file_by_hash(db: AsyncSession, document_id: int, sha256: str) -> DocumentFile | None:
    return await db.scalar(
        select(DocumentFile).where(
            DocumentFile.document_id == document_id, DocumentFile.file_hash_sha256 == sha256.lower(),
        ).limit(1)
    )


# ── links ───────────────────────────────────────────────────────────────────

async def create_link(db: AsyncSession, values: dict) -> DocumentLink:
    link = DocumentLink(**values)
    db.add(link)
    await db.flush()
    return link


async def get_link(db: AsyncSession, document_id: int, link_uuid: UUID) -> DocumentLink | None:
    return await db.scalar(
        select(DocumentLink).where(DocumentLink.document_id == document_id, DocumentLink.uuid == link_uuid)
    )


async def find_link(
    db: AsyncSession, document_id: int, linkable_type: str, linkable_id: int, link_role: str,
) -> DocumentLink | None:
    return await db.scalar(
        select(DocumentLink).where(
            DocumentLink.document_id == document_id,
            DocumentLink.linkable_type == linkable_type,
            DocumentLink.linkable_id == linkable_id,
            DocumentLink.link_role == link_role,
        )
    )


async def find_owner_link(db: AsyncSession, document_id: int) -> DocumentLink | None:
    return await db.scalar(
        select(DocumentLink).where(
            DocumentLink.document_id == document_id, DocumentLink.link_role == DocumentLinkRole.OWNER.value,
        )
    )


async def attach_documents_to_entity(
    db: AsyncSession,
    linkable_type: str,
    linkable_id: int,
    document_uuids: list[UUID],
    *,
    link_role: str = DocumentLinkRole.ATTACHMENT.value,
    context_by_id: dict[UUID, dict] | None = None,
) -> list[Document]:
    """Link existing documents to an entity (e.g. attach uploads to an Email).

    Idempotent: re-attaching the same document in the same role only merges the
    per-link context (e.g. ``{"is_inline": True, "content_id": "cid:logo"}`` — it
    belongs to the LINK, because the same document can be inline in one email
    and a plain attachment in another). Returns the documents found; the caller
    compares against what it asked for.
    """
    docs = await get_documents_by_uuid(db, list(dict.fromkeys(document_uuids)))
    for doc in docs:
        context = (context_by_id or {}).get(doc.uuid)
        link = await find_link(db, doc.id, linkable_type, linkable_id, link_role)
        if link is None:
            await create_link(db, {
                "document_id": doc.id, "tenant_id": doc.tenant_id, "organization_id": doc.organization_id,
                "linkable_type": linkable_type, "linkable_id": linkable_id, "link_role": link_role,
                "context": context,
            })
        elif context:
            link.context = {**(link.context or {}), **context}
    await db.flush()
    return docs


# ── verification log ────────────────────────────────────────────────────────

async def add_log(db: AsyncSession, values: dict) -> DocumentVerificationLog:
    entry = DocumentVerificationLog(**values)
    db.add(entry)
    await db.flush()
    return entry


async def list_logs(db: AsyncSession, document_id: int) -> list[DocumentVerificationLog]:
    stmt = (
        select(DocumentVerificationLog)
        .where(DocumentVerificationLog.document_id == document_id)
        .order_by(DocumentVerificationLog.performed_at.asc(), DocumentVerificationLog.id.asc())
    )
    return list((await db.scalars(stmt)).all())
