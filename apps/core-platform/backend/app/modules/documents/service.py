"""PDF generation via Gotenberg (service layer).

Gotenberg is reachable ONLY on the app-pdf Docker network — no host port,
no Traefik route. The backend and Celery workers are the only containers
attached to that network, which is what enforces "only my application can
use Gotenberg".

Sync implementation because PDF rendering belongs in Celery workers
(documents queue) — it is slow, CPU-heavy and must not block API workers.
"""

import uuid
from pathlib import Path

import httpx
import structlog

from app.common.exception.errors import UpstreamError
from app.core.conf import settings

logger = structlog.get_logger("app.documents")


def render_html_to_pdf(html: str, filename: str = "document.pdf") -> str:
    """Render an HTML string to PDF via Gotenberg. Returns the stored file path."""
    out_dir = Path(settings.MEDIA_DIR) / "pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{uuid.uuid4().hex}-{filename}"

    with httpx.Client(base_url=settings.GOTENBERG_URL, timeout=60.0) as client:
        resp = client.post(
            "/forms/chromium/convert/html",
            files={"files": ("index.html", html.encode("utf-8"), "text/html")},
        )

    if resp.status_code != 200:
        logger.error("gotenberg_render_failed", status=resp.status_code, body=resp.text[:300])
        raise UpstreamError("PDF rendering failed")

    out_path.write_bytes(resp.content)
    logger.info("pdf_rendered", path=str(out_path), size_bytes=len(resp.content))
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
