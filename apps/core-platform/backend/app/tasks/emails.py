"""Email delivery tasks (queue: integrations — outbound HTTP like Zoho).

The worker owns everything slow: loading attachments, base64 encoding, the
Resend HTTP call, and retry pacing. Retries are DB-driven (attempts /
max_attempts on the row) layered under Celery's backoff — the email row is
always the source of truth for its own state.

Async-in-Celery: same _run pattern as app/tasks/zoho_sync.py (asyncpg-only
stack; throwaway NullPool engine per task).
"""

import asyncio
import base64
from datetime import UTC, datetime

import httpx
import structlog
from celery import shared_task
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.conf import settings

logger = structlog.get_logger("app.tasks.emails")


async def _load_attachments(db, email) -> list[dict]:
    """Documents -> Resend attachment dicts (base64 content).

    Local-disk backed documents are read directly; S3 documents are skipped
    with a loud log until the S3 client lands (attachment metadata carries
    everything needed to extend this).
    """
    from sqlalchemy import select

    from app.modules.documents.model import Document

    docs = (
        await db.scalars(
            select(Document).where(
                Document.documentable_type == "Email",
                Document.documentable_id == str(email.id),
            )
        )
    ).all()

    attachments: list[dict] = []
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
        att = {"filename": doc.file_name, "content": base64.b64encode(content).decode()}
        if meta.get("is_inline") and meta.get("content_id"):
            att["content_id"] = meta["content_id"]
        attachments.append(att)
    return attachments


@shared_task(bind=True, name="app.tasks.emails.send_email", max_retries=5)
def send_email(self, email_id: int) -> dict:
    from app.modules.emails.model import Email

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

                email.push_status("processing")
                email.attempts = (email.attempts or 0) + 1
                await db.commit()

                payload: dict = {
                    "from": email.email_from,
                    "to": email.email_to,
                    "subject": email.subject,
                }
                if email.body_html:
                    payload["html"] = email.body_html
                if email.body_text:
                    payload["text"] = email.body_text
                if email.email_cc:
                    payload["cc"] = email.email_cc
                if email.email_bcc:
                    payload["bcc"] = email.email_bcc
                if email.reply_to:
                    payload["reply_to"] = email.reply_to

                attachments = await _load_attachments(db, email)
                if attachments:
                    payload["attachments"] = attachments

                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            settings.RESEND_API_URL,
                            json=payload,
                            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                        )
                    resp.raise_for_status()
                    data = resp.json()
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
                email.provider_message_id = data.get("id")
                email.provider_response = data
                email.sent_at = datetime.now(UTC)
                email.error_message = None
                await db.commit()
                logger.info("email_sent", email_id=email_id, provider_message_id=data.get("id"))
                return {"status": "sent", "provider_message_id": data.get("id")}
        finally:
            await engine.dispose()

    out = asyncio.run(work())
    if out.get("status") == "missing":
        raise self.retry(countdown=10)  # enqueued before the compose txn committed
    if out.get("status") == "retry":
        # Exponential pacing: 1 min, 5 min, 15 min, ...
        raise self.retry(countdown=min(60 * (5 ** self.request.retries), 900))
    return out
