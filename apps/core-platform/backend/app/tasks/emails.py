"""Email delivery tasks (queue: integrations — outbound HTTP like Zoho).

The worker owns everything slow: loading attachments, the provider HTTP call,
and retry pacing. It speaks only to the provider-neutral layer
(``app/modules/emails/provider.py``) — no provider payload shapes live here.
Retries are DB-driven (attempts / max_attempts on the row) layered under
Celery's backoff; the email row is always the source of truth for its state.

Async-in-Celery: ``run_async`` on the worker process's event loop with the
pooled session factory (ADR‑3, app/tasks/_loop.py).
"""

import asyncio
from datetime import UTC, datetime

import structlog
from celery import shared_task

from app.core.conf import settings
from app.database.db import async_session_factory
from app.tasks._loop import run_async

logger = structlog.get_logger("app.tasks.emails")


async def _load_attachments(db, email) -> list:
    """Files of the documents attached to the email -> provider-neutral
    ``EmailAttachment`` objects (raw bytes).

    An email's documents are the ones LINKED to it in the ``attachment`` role;
    each file (page) of a document becomes one attachment. Local-disk files are
    read directly; object-store files are skipped with a loud log until the S3
    client lands (the file row carries everything needed to extend this).
    Soft-deleted documents, files and links are never sent.
    """
    from sqlalchemy import select

    from app.modules.documents.enums import DocumentLinkRole, FileStorageProvider
    from app.modules.documents.mixins import linkable_type_of
    from app.modules.documents.model import Document, DocumentFile, DocumentLink
    from app.modules.emails.model import Email
    from app.modules.emails.provider import EmailAttachment

    rows = (
        await db.execute(
            select(DocumentFile, DocumentLink.context)
            .join(DocumentLink, DocumentLink.document_id == DocumentFile.document_id)
            .join(Document, Document.id == DocumentFile.document_id)
            .where(
                DocumentLink.linkable_type == linkable_type_of(Email),
                DocumentLink.linkable_id == email.id,
                DocumentLink.link_role == DocumentLinkRole.ATTACHMENT.value,
                DocumentLink.deleted_at.is_(None),
                DocumentFile.deleted_at.is_(None),
                Document.deleted_at.is_(None),
            )
            .order_by(DocumentLink.sort_order, DocumentFile.document_id, DocumentFile.page_index)
        )
    ).all()

    attachments: list[EmailAttachment] = []
    for file, context in rows:
        content: bytes | None = None
        if file.file_storage_provider == FileStorageProvider.LOCAL_DISK.value:
            try:
                content = await asyncio.to_thread(lambda p=file.file_key: open(p, "rb").read())
            except OSError as e:
                logger.error("email_attachment_read_failed", document_file_id=str(file.uuid), error=str(e))
        else:
            logger.warning("email_attachment_remote_skipped", document_file_id=str(file.uuid),
                           provider=file.file_storage_provider, file_key=file.file_key)
        if content is None:
            continue
        context = context or {}
        attachments.append(
            EmailAttachment(
                filename=file.file_name,
                content=content,
                content_id=context.get("content_id") if context.get("is_inline") else None,
            )
        )
    return attachments


@shared_task(bind=True, name="app.tasks.emails.send_email", max_retries=5)
def send_email(self, email_id: int) -> dict:
    from app.modules.emails.model import Email
    from app.modules.emails.provider import get_email_provider

    async def work() -> dict:
        async with async_session_factory() as db:
            email = await db.get(Email, email_id)
            if email is None:
                return {"status": "missing"}
            if email.status not in ("pending", "queued"):
                return {"status": "already_processed", "current": email.status}

            # Master switch: record the intent, never touch the network.
            if not settings.EMAIL_ENABLED:
                email.push_status("suppressed", "outbound email disabled (EMAIL_ENABLED=false)")
                await db.commit()
                logger.warning("email_suppressed_disabled", email_id=email_id)
                return {"status": "suppressed"}

            email.push_status("processing")
            email.attempts = (email.attempts or 0) + 1
            await db.commit()

            # Dev: persist + mark sent without a provider call (no key/network).
            if settings.EMAIL_LOG_ONLY:
                email.push_status("sent", "EMAIL_LOG_ONLY=true (not delivered)")
                email.sent_at = datetime.now(UTC)
                await db.commit()
                logger.info("email_log_only", email_id=email_id)
                return {"status": "sent", "log_only": True}

            from app.modules.emails.provider import OutboundEmail

            message = OutboundEmail(
                to=email.email_to or [],
                cc=email.email_cc or [],
                bcc=email.email_bcc or [],
                sender=email.email_from,
                reply_to=email.reply_to,
                subject=email.subject or "",
                html=email.body_html,
                text=email.body_text,
            )
            message.attachments = await _load_attachments(db, email)

            try:
                result = await get_email_provider().send(message)
            except Exception as e:  # noqa: BLE001 — classified below
                email.error_message = str(e)[:2000]
                if (email.attempts or 0) >= (email.max_attempts or settings.EMAIL_MAX_ATTEMPTS):
                    email.push_status("failed", "max attempts reached")
                    email.failed_at = datetime.now(UTC)
                    await db.commit()
                    logger.error("email_send_failed_final", email_id=email_id, error=str(e))
                    return {"status": "failed", "error": str(e)[:200]}
                email.push_status("pending", "retry scheduled")
                await db.commit()
                return {"status": "retry", "error": str(e)[:200]}

            email.push_status("sent")
            email.provider = result.provider
            email.provider_message_id = result.message_id
            email.provider_response = result.raw
            email.sent_at = datetime.now(UTC)
            email.error_message = None
            await db.commit()
            logger.info("email_sent", email_id=email_id, provider_message_id=result.message_id)
            return {"status": "sent", "provider_message_id": result.message_id}

    out = run_async(work())
    if out.get("status") == "missing":
        raise self.retry(countdown=10)  # enqueued before the compose txn committed
    if out.get("status") == "retry":
        # Exponential pacing: base, 2x, 4x, … capped.
        backoff = min(
            settings.EMAIL_RETRY_BASE_SECONDS * (2 ** self.request.retries),
            settings.EMAIL_RETRY_MAX_BACKOFF_SECONDS,
        )
        raise self.retry(countdown=backoff)
    return out
