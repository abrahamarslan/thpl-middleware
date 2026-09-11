"""Email delivery tasks (queue: integrations — outbound HTTP like Zoho).

The worker owns everything slow: loading attachments, the provider HTTP call,
and retry pacing. It speaks only to the provider-neutral layer
(``app/modules/emails/provider.py``) — no provider payload shapes live here.
Retries are DB-driven (attempts / max_attempts on the row) layered under
Celery's backoff; the email row is always the source of truth for its state.

Async-in-Celery: same _run pattern as app/tasks/zoho_sync.py (asyncpg-only
stack; throwaway NullPool engine per task).
"""

import asyncio
from datetime import UTC, datetime

import structlog
from celery import shared_task
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.conf import settings

logger = structlog.get_logger("app.tasks.emails")


async def _load_attachments(db, email) -> list:
    """Documents -> provider-neutral ``EmailAttachment`` objects (raw bytes).

    Local-disk backed documents are read directly; S3 documents are skipped
    with a loud log until the S3 client lands (attachment metadata carries
    everything needed to extend this).
    """
    from sqlalchemy import select

    from app.modules.documents.model import Document
    from app.modules.emails.provider import EmailAttachment

    docs = (
        await db.scalars(
            select(Document).where(
                Document.documentable_type == "Email",
                Document.documentable_id == str(email.id),
            )
        )
    ).all()

    attachments: list[EmailAttachment] = []
    for doc in docs:
        content: bytes | None = None
        meta = doc.metadata_ or {}
        local_path = meta.get("local_path")  # documents registered from local pipelines
        if local_path:
            try:
                content = await asyncio.to_thread(lambda p=local_path: open(p, "rb").read())
            except OSError as e:
                logger.error("email_attachment_read_failed", document_id=str(doc.id), error=str(e))
        elif doc.s3_key:
            logger.warning("email_attachment_s3_skipped", document_id=str(doc.id), s3_key=doc.s3_key)
        if content is None:
            continue
        attachments.append(
            EmailAttachment(
                filename=doc.file_name,
                content=content,
                content_id=meta.get("content_id") if meta.get("is_inline") else None,
            )
        )
    return attachments


@shared_task(bind=True, name="app.tasks.emails.send_email", max_retries=5)
def send_email(self, email_id: int) -> dict:
    from app.modules.emails.model import Email
    from app.modules.emails.provider import get_email_provider

    async def work() -> dict:
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as db:
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
        finally:
            await engine.dispose()

    out = asyncio.run(work())
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
