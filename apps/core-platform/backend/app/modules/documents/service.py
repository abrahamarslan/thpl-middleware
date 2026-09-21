"""Documents service: PDF generation via Typst, and the document domain.

PDF generation
--------------
In-process rendering with typst-py (https://pypi.org/project/typst/):
no sidecar service, no Docker network, no HTTP hop. The Celery worker
compiles Typst markup to PDF bytes and stores the file in the shared
media volume.

Sync implementation because PDF rendering belongs in Celery workers
(documents queue) — it is slow, CPU-heavy and must not block API workers.

Data injection: prefer ``sys_inputs`` over string interpolation. Pass JSON
strings and decode them inside Typst::

    sys_inputs = {"invoice": json.dumps(invoice_dict)}

    #let invoice = json(bytes(sys.inputs.invoice))

Templates live next to the caller (or under
``app/modules/documents/templates/*.typ``); for multi-file projects pass a
``dict[str, bytes]`` with a ``"main.typ"`` entry — see typst-py docs.

Document domain
---------------
Registration, files, links, versions and deletion. The verification lifecycle
lives in ``verification.py``. Authorisation is the API layer's business.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import structlog
import typst
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError, UpstreamError
from app.core.conf import settings
from app.modules.activity.recorder import record_activity
from app.modules.documents import crud, schema, verification
from app.modules.documents.enums import (
    DocumentAuditAction,
    DocumentLinkRole,
    DocumentPageSide,
    DocumentVerificationStatus,
    Requirement,
)
from app.modules.documents.errors import DocumentRuleError
from app.modules.documents.model import Document, DocumentFile, DocumentLink, DocumentType
from app.modules.documents.seed import GENERAL_TYPE_CODE

logger = structlog.get_logger("app.documents")

_S = DocumentVerificationStatus
#: A document still collecting its files may take more; after that a change is a new version.
_OPEN_FOR_FILES = {_S.NOT_UPLOADED.value, _S.PENDING_UPLOAD.value, _S.UPLOADED.value}
#: States a document can be resubmitted from.
_RESUBMITTABLE = {_S.REJECTED.value, _S.RESUBMISSION_REQUIRED.value, _S.EXPIRED.value}


# ── PDF generation ──────────────────────────────────────────────────────────

def render_typst_to_pdf(
    source: str | bytes | dict[str, bytes],
    filename: str = "document.pdf",
    sys_inputs: dict[str, str] | None = None,
) -> str:
    """Compile Typst markup to PDF. Returns the stored file path."""
    out_dir = Path(settings.MEDIA_DIR) / "pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{uuid.uuid4().hex}-{filename}"

    if isinstance(source, str):
        typst_input: str | bytes | dict[str, bytes] = source.encode("utf-8")
    else:
        typst_input = source

    kwargs: dict = {"format": "pdf"}
    if settings.TYPST_FONT_PATHS:
        kwargs["font_paths"] = settings.TYPST_FONT_PATHS
    if settings.TYPST_PDF_STANDARDS:
        kwargs["pdf_standards"] = settings.TYPST_PDF_STANDARDS
    if sys_inputs:
        kwargs["sys_inputs"] = sys_inputs

    try:
        pdf_bytes = typst.compile(typst_input, **kwargs)
    except Exception as exc:  # typst.TypstError + input validation
        logger.error("typst_render_failed", error=str(exc)[:300])
        raise UpstreamError("PDF rendering failed") from exc

    if not isinstance(pdf_bytes, (bytes, bytearray)):
        logger.error("typst_render_unexpected", type=type(pdf_bytes).__name__)
        raise UpstreamError("PDF rendering failed")

    out_path.write_bytes(bytes(pdf_bytes))
    logger.info("pdf_rendered", path=str(out_path), size_bytes=len(pdf_bytes))
    return str(out_path)


# ── the catalog ─────────────────────────────────────────────────────────────

async def list_document_types(
    db: AsyncSession, *, category: str | None = None, include_deactivated: bool = False,
) -> list[DocumentType]:
    return await crud.list_document_types(db, category=category, include_deactivated=include_deactivated)


async def get_document_type(db: AsyncSession, code: str) -> DocumentType:
    document_type = await crud.get_document_type_by_code(db, code)
    if document_type is None:
        raise NotFoundError(f"Unknown document type '{code}'")
    return document_type


async def _require_active_type(db: AsyncSession, code: str) -> DocumentType:
    document_type = await get_document_type(db, code)
    if document_type.deactivation_date is not None:
        raise ConflictError(f"Document type '{code}' is deactivated and no longer requested")
    return document_type


# ── the document number ─────────────────────────────────────────────────────

def mask_number(number: str) -> str:
    """Keep the last four characters: ``XXXXXXXX1234``. Four or fewer: mask all."""
    compact = "".join(number.split())
    return "X" * len(compact) if len(compact) <= 4 else "X" * (len(compact) - 4) + compact[-4:]


async def _number_fields(db: AsyncSession, document_type: DocumentType, number) -> dict:
    """The number columns to write, honouring the type's storage rule.

    The masked form is always kept (search, de-duplication). The FULL number is
    stored only when the type allows it AND an encryption key is configured;
    for an ``allows_full_number_storage = false`` type (Aadhaar) it is discarded
    here, so no caller can persist it by mistake.
    """
    raw = number.get_secret_value().strip() if number is not None else ""
    if not raw:
        return {}
    fields: dict = {"document_number_masked": mask_number(raw)}
    if not document_type.allows_full_number_storage:
        return fields
    key = settings.DOCUMENT_NUMBER_ENCRYPTION_KEY
    if not key:
        # Fail closed: never store it readable.
        logger.warning("document_number_not_stored", type=document_type.code,
                       reason="DOCUMENT_NUMBER_ENCRYPTION_KEY is empty")
        return fields
    fields["document_number_full_encrypted"] = await db.scalar(
        select(func.armor(func.pgp_sym_encrypt(raw, key)))
    )
    return fields


# ── validation ──────────────────────────────────────────────────────────────

def _check_new_files(files: list[schema.FileIn]) -> None:
    sides = [f.page_side for f in files if f.page_side in (DocumentPageSide.FRONT, DocumentPageSide.BACK)]
    if len(sides) != len(set(sides)):
        raise DocumentRuleError("A document has at most one FRONT and one BACK file")
    hashes = [f.file_hash_sha256.lower() for f in files if f.file_hash_sha256]
    if len(hashes) != len(set(hashes)):
        raise DocumentRuleError("The same file (identical sha256) was submitted twice")


def _check_new_links(links: list[schema.LinkIn]) -> None:
    if sum(1 for link in links if link.link_role is DocumentLinkRole.OWNER) > 1:
        raise DocumentRuleError("A document has at most one owner link")


def _default_expiry(document_type: DocumentType, issued: date | None, expiry: date | None) -> date | None:
    """Pre-fill the expiry from the type's default validity when the caller gave none."""
    if expiry is not None or not document_type.has_expiry or not document_type.default_validity_days:
        return expiry
    return (issued or datetime.now(UTC).date()) + timedelta(days=document_type.default_validity_days)


# ── writing rows ────────────────────────────────────────────────────────────

async def _create_file(
    db: AsyncSession, document: Document, file_in: schema.FileIn, *, page_index: int, is_primary: bool,
    actor_id: int | None,
) -> DocumentFile:
    values = file_in.model_dump(mode="json", exclude={"page_index"})
    if values.get("file_hash_sha256"):
        values["file_hash_sha256"] = values["file_hash_sha256"].lower()
    return await crud.create_file(db, {
        **values, "document_id": document.id, "tenant_id": document.tenant_id,
        "organization_id": document.organization_id, "page_index": page_index, "is_primary": is_primary,
        "uploaded_by": actor_id, "uploaded_at": datetime.now(UTC),
    })


async def _create_link(db: AsyncSession, document: Document, link_in: schema.LinkIn) -> DocumentLink:
    return await crud.create_link(db, {
        **link_in.model_dump(mode="json"), "document_id": document.id,
        "tenant_id": document.tenant_id, "organization_id": document.organization_id,
    })


async def _reload(db: AsyncSession, document: Document) -> Document:
    """Re-read with the viewonly collections (files, links, tags) fresh."""
    return await crud.get_document(db, document.uuid, refresh=True)


# ── registration ────────────────────────────────────────────────────────────

async def register_document(
    db: AsyncSession, doc_in: schema.DocumentCreate, *, actor_id: int | None = None,
) -> Document:
    """Create a logical document with its files and owners, after the bytes reached storage."""
    document_type = await _require_active_type(db, doc_in.document_type_code)
    _check_new_files(doc_in.files)
    _check_new_links(doc_in.links)

    complete = verification.is_complete(document_type, (f.page_side for f in doc_in.files))
    if doc_in.personnel_type is not None:
        is_mandatory = document_type.requirement_for(doc_in.personnel_type.value) == Requirement.MANDATORY.value
    else:
        is_mandatory = document_type.code != GENERAL_TYPE_CODE

    values = {
        "document_type_id": document_type.id,
        "document_purpose": document_type.category,
        "issuing_authority": doc_in.issuing_authority,
        "issuing_state": doc_in.issuing_state,
        "issued_date": doc_in.issued_date,
        "expiry_date": _default_expiry(document_type, doc_in.issued_date, doc_in.expiry_date),
        "retention_expiry_date": doc_in.retention_expiry_date,
        "ocr_extracted_data": doc_in.ocr_extracted_data,
        "is_mandatory": is_mandatory,
        "verification_status": (_S.UPLOADED if complete else _S.PENDING_UPLOAD).value,
        **await _number_fields(db, document_type, doc_in.document_number),
    }
    document = await crud.create_document(db, values)
    for index, file_in in enumerate(doc_in.files):
        await _create_file(db, document, file_in, page_index=file_in.page_index if file_in.page_index is not None
                           else index, is_primary=index == 0, actor_id=actor_id)
    for link_in in doc_in.links:
        await _create_link(db, document, link_in)

    await verification.record_event(
        db, document, action=DocumentAuditAction.UPLOADED, previous_status=None,
        new_status=document.verification_status, actor_id=actor_id,
    )
    await record_activity(
        db, action="document_registered", actor_id=actor_id, subject_type="Document", subject_id=str(document.uuid),
        changes={"type": document_type.code, "files": len(doc_in.files), "links": len(doc_in.links)},
    )
    return await _reload(db, document)


async def get_document(db: AsyncSession, document_uuid: UUID) -> Document:
    document = await crud.get_document(db, document_uuid)
    if document is None:
        raise NotFoundError("Document not found")
    return document


async def list_documents_for_entity(
    db: AsyncSession, linkable_type: str, linkable_id: int, *, roles: list[str] | None = None,
    latest_only: bool = True,
) -> list[Document]:
    return await crud.list_documents_for_entity(db, linkable_type, linkable_id, roles=roles, latest_only=latest_only)


# ── files ───────────────────────────────────────────────────────────────────

async def add_file(
    db: AsyncSession, document_uuid: UUID, file_in: schema.FileIn, *, actor_id: int | None = None,
) -> Document:
    """Add a page to a document that is still collecting its files.

    Completing the type's requirement (one file, or front + back) moves a
    ``pending_upload`` document to ``uploaded``. Once it is in review or beyond,
    a change is a new version — see ``resubmit_document``.
    """
    document = await get_document(db, document_uuid)
    if document.verification_status not in _OPEN_FOR_FILES:
        raise ConflictError(
            f"Files cannot be added to a document that is '{document.verification_status}'; resubmit a new version",
        )
    live = list(document.files)
    if file_in.page_side in (DocumentPageSide.FRONT, DocumentPageSide.BACK) and any(
        f.page_side == file_in.page_side.value for f in live
    ):
        raise DocumentRuleError(f"The document already has a {file_in.page_side.value} file")
    if file_in.file_hash_sha256 and await crud.find_file_by_hash(db, document.id, file_in.file_hash_sha256):
        raise ConflictError("This file (identical sha256) is already part of the document")

    index = file_in.page_index if file_in.page_index is not None else len(live)
    await _create_file(db, document, file_in, page_index=index, is_primary=not live, actor_id=actor_id)

    sides = [f.page_side for f in live] + [file_in.page_side]
    if document.verification_status != _S.UPLOADED.value and verification.is_complete(document.document_type, sides):
        await verification.transition(db, document, _S.UPLOADED, actor_id=actor_id)
    await record_activity(
        db, action="document_file_added", actor_id=actor_id, subject_type="Document", subject_id=str(document.uuid),
        changes={"file_name": file_in.file_name, "page_side": file_in.page_side.value},
    )
    return await _reload(db, document)


# ── links ───────────────────────────────────────────────────────────────────

async def link_document(
    db: AsyncSession, document_uuid: UUID, link_in: schema.LinkIn, *, actor_id: int | None = None,
) -> Document:
    document = await get_document(db, document_uuid)
    if link_in.link_role is DocumentLinkRole.OWNER and await crud.find_owner_link(db, document.id):
        raise DocumentRuleError("The document already has an owner; detach it first")
    if await crud.find_link(db, document.id, link_in.linkable_type.value, link_in.linkable_id,
                            link_in.link_role.value):
        raise ConflictError("The document is already linked to this entity in this role")
    await _create_link(db, document, link_in)
    await record_activity(
        db, action="document_linked", actor_id=actor_id, subject_type="Document", subject_id=str(document.uuid),
        changes={"linkable_type": link_in.linkable_type.value, "linkable_id": link_in.linkable_id,
                 "link_role": link_in.link_role.value},
    )
    return await _reload(db, document)


async def unlink_document(
    db: AsyncSession, document_uuid: UUID, link_uuid: UUID, *, reason: str | None = None,
    actor_id: int | None = None,
) -> Document:
    """Detach = soft delete the link (who / when / why are ``deleted_by`` / ``_at`` / ``_reason``)."""
    document = await get_document(db, document_uuid)
    link = await crud.get_link(db, document.id, link_uuid)
    if link is None:
        raise NotFoundError("Link not found")
    link.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="document_unlinked", actor_id=actor_id, subject_type="Document", subject_id=str(document.uuid),
        changes={"linkable_type": link.linkable_type, "linkable_id": link.linkable_id, "link_role": link.link_role},
    )
    return await _reload(db, document)


async def attach_documents(
    db: AsyncSession, req: schema.AttachDocumentsRequest, *, actor_id: int | None = None,
) -> list[Document]:
    """Link existing documents to an entity (an email's attachments, …)."""
    docs = await crud.attach_documents_to_entity(
        db, req.linkable_type.value, req.linkable_id, req.document_ids,
        link_role=req.link_role.value, context_by_id=req.context_by_id,
    )
    if len(docs) != len(set(req.document_ids)):
        missing = set(req.document_ids) - {d.uuid for d in docs}
        raise NotFoundError(f"Documents not found: {sorted(str(i) for i in missing)}")
    await record_activity(
        db, action="documents_attached", actor_id=actor_id, subject_type=req.linkable_type.value,
        subject_id=str(req.linkable_id), changes={"document_ids": [str(i) for i in req.document_ids]},
    )
    return docs


# ── versions ────────────────────────────────────────────────────────────────

async def resubmit_document(
    db: AsyncSession, document_uuid: UUID, req: schema.ResubmitRequest, *, actor_id: int | None = None,
) -> Document:
    """Create the next version of a rejected / expired / resubmission-required document.

    The new row starts at ``uploaded`` (or ``pending_upload`` while incomplete),
    supersedes the old one, inherits its owners, and the old row stays as
    evidence of what was rejected and why.
    """
    old = await get_document(db, document_uuid)
    if not old.is_latest_version:
        raise ConflictError("Only the latest version of a document can be resubmitted")
    if old.verification_status not in _RESUBMITTABLE:
        raise ConflictError(f"A '{old.verification_status}' document cannot be resubmitted")
    _check_new_files(req.files)

    document_type = old.document_type
    complete = verification.is_complete(document_type, (f.page_side for f in req.files))
    issued = req.issued_date or old.issued_date
    number = await _number_fields(db, document_type, req.document_number) or {
        "document_number_masked": old.document_number_masked,
        "document_number_full_encrypted": old.document_number_full_encrypted,
    }
    new = await crud.create_document(db, {
        "tenant_id": old.tenant_id, "organization_id": old.organization_id,
        "document_type_id": old.document_type_id, "document_purpose": old.document_purpose,
        "issuing_authority": req.issuing_authority or old.issuing_authority,
        "issuing_state": req.issuing_state or old.issuing_state,
        "issued_date": issued, "expiry_date": _default_expiry(document_type, issued, req.expiry_date),
        "retention_expiry_date": old.retention_expiry_date, "is_mandatory": old.is_mandatory,
        "version_number": old.version_number + 1, "supersedes_document_id": old.id,
        "resubmission_count": old.resubmission_count + 1,
        "verification_status": (_S.UPLOADED if complete else _S.PENDING_UPLOAD).value,
        **number,
    })
    old.is_latest_version = False
    for index, file_in in enumerate(req.files):
        await _create_file(db, new, file_in, page_index=file_in.page_index if file_in.page_index is not None
                           else index, is_primary=index == 0, actor_id=actor_id)
    for link in old.links:
        await crud.create_link(db, {
            "document_id": new.id, "tenant_id": new.tenant_id, "organization_id": new.organization_id,
            "linkable_type": link.linkable_type, "linkable_id": link.linkable_id, "link_role": link.link_role,
            "is_primary": link.is_primary, "sort_order": link.sort_order, "context": link.context,
        })
    await verification.record_event(
        db, new, action=DocumentAuditAction.RESUBMITTED, previous_status=None, new_status=new.verification_status,
        actor_id=actor_id, remarks=f"Version {new.version_number}; supersedes version {old.version_number}",
    )
    await record_activity(
        db, action="document_resubmitted", actor_id=actor_id, subject_type="Document", subject_id=str(new.uuid),
        changes={"supersedes": str(old.uuid), "version": new.version_number},
    )
    return await _reload(db, new)


# ── deletion ────────────────────────────────────────────────────────────────

async def soft_delete_document(
    db: AsyncSession, document_uuid: UUID, *, reason: str | None = None, actor_id: int | None = None,
) -> None:
    """Soft-delete the document AND its files and links, so no query can reach them
    through a child row (an email must not send the attachment of a deleted document)."""
    document = await get_document(db, document_uuid)
    # The trail first: the owner link it snapshots is about to be soft-deleted.
    await verification.record_event(
        db, document, action=DocumentAuditAction.DELETED, previous_status=document.verification_status,
        new_status=None, actor_id=actor_id, remarks=reason,
    )
    for child in (*document.files, *document.links):
        child.soft_delete(reason=reason, by=actor_id)
    document.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="document_deleted", actor_id=actor_id, subject_type="Document", subject_id=str(document.uuid),
    )
