"""Document generation tasks (queue: documents)."""

import structlog
from celery import shared_task

from app.modules.documents.service import render_typst_to_pdf

logger = structlog.get_logger("app.tasks.documents")


@shared_task(name="app.tasks.documents.generate_pdf", max_retries=2, retry_backoff=True)
def generate_pdf(
    source: str,
    filename: str = "document.pdf",
    sys_inputs: dict[str, str] | None = None,
) -> str:
    """Compile Typst markup to PDF and return the stored path.

    Invoked by POST /api/documents/render (invoices, delivery notes,
    order confirmations). The shared backend_media volume makes the file
    available to the API container for download endpoints.
    """
    path = render_typst_to_pdf(source, filename, sys_inputs=sys_inputs)
    logger.info("pdf_task_complete", path=path)
    return path


@shared_task(name="app.tasks.documents.expire_due_documents")
def expire_due_documents() -> dict:
    """Move every verified document past its expiry date to ``expired`` (daily, all tenants).

    Runs in system scope — no tenant context, so the query spans tenants and the
    trail rows are stamped ``actor_type = system``. Beat: ``documents-expiry``.
    """
    from app.database.db import async_session_factory
    from app.modules.documents.verification import expire_due_documents as sweep
    from app.tasks._loop import run_async

    async def work() -> dict:
        async with async_session_factory() as db:
            expired = await sweep(db)
            await db.commit()
            return {"expired": expired}

    result = run_async(work())
    logger.info("documents_expiry_sweep", **result)
    return result
