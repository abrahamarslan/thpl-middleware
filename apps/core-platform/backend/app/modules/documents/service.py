"""PDF generation via Typst (service layer).

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
"""

import uuid
from pathlib import Path

import structlog
import typst

from app.common.exception.errors import UpstreamError
from app.core.conf import settings

logger = structlog.get_logger("app.documents")


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


# ── Polymorphic document attachments (async service) ─────────────────────────

from uuid import UUID  # noqa: E402

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.common.exception.errors import NotFoundError  # noqa: E402
from app.modules.activity.recorder import record_activity  # noqa: E402
from app.modules.documents import crud, schema  # noqa: E402
from app.modules.documents.model import Document  # noqa: E402


async def register_uploaded_document(
    db: AsyncSession, doc_in: schema.DocumentCreate, *, actor_id: int | None = None
) -> Document:
    """Create the DB record after the file bytes reached S3 (frontend upload)."""
    values = doc_in.model_dump(exclude_unset=True)
    if actor_id is not None:
        values["uploaded_by_id"] = str(actor_id)
    document = await crud.create_document(db, values)
    await record_activity(
        db, action="document_uploaded", actor_id=actor_id,
        subject_type="Document", subject_id=document.id,
        changes={"file_name": doc_in.file_name, "file_size": doc_in.file_size},
    )
    return await crud.get_document(db, document.id)  # re-fetch with tags loaded


async def get_document(db: AsyncSession, document_id: UUID) -> Document:
    document = await crud.get_document(db, document_id)
    if document is None:
        raise NotFoundError("Document not found")
    return document


async def attach_documents(
    db: AsyncSession, req: schema.AttachDocumentsRequest, *, actor_id: int | None = None
) -> list[Document]:
    docs = await crud.attach_documents_to_entity(
        db, req.documentable_type, req.documentable_id, req.document_ids,
        metadata_by_id=req.metadata_by_id,
    )
    if len(docs) != len(set(req.document_ids)):
        found = {d.id for d in docs}
        raise NotFoundError(f"Documents not found: {[str(i) for i in set(req.document_ids) - found]}")
    await record_activity(
        db, action="documents_attached", actor_id=actor_id,
        subject_type=req.documentable_type, subject_id=req.documentable_id,
        changes={"document_ids": [str(i) for i in req.document_ids]},
    )
    return docs


async def soft_delete_document(db: AsyncSession, document_id: UUID, *, actor_id: int | None = None) -> None:
    document = await get_document(db, document_id)
    document.soft_delete()
    await db.flush()
    await record_activity(
        db, action="document_deleted", actor_id=actor_id,
        subject_type="Document", subject_id=document_id,
    )
