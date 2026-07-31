"""Emails business logic: compose-and-queue + provider webhook processing.

Compose flow: persist first (status=pending), attach documents, THEN hand
off to Celery — the API answers instantly and the worker owns the slow I/O
(S3 attachment download, Resend HTTP call, retries with backoff).

Webhook flow: Resend pushes delivery/engagement events; each event appends
an email_events row and updates the aggregate counters/status on the email.
"""

import hashlib
import hmac
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AuthError, NotFoundError
from app.core.conf import settings
from app.modules.activity.recorder import record_activity
from app.modules.documents.crud import attach_documents_to_entity
from app.modules.emails import crud, schema
from app.modules.emails.model import Email, EmailEvent

logger = structlog.get_logger("app.emails")


async def compose_and_queue_email(
    db: AsyncSession, email_in: schema.EmailCreate, *, actor_id: int | None = None
) -> Email:
    all_recipients = sorted({*email_in.to, *email_in.cc, *email_in.bcc})

    email = await crud.create_email(
        db,
        dict(
            email_to=list(email_in.to),
            email_cc=list(email_in.cc) or None,
            email_bcc=list(email_in.bcc) or None,
            all_recipients=all_recipients,
            email_from=email_in.email_from or settings.RESEND_DEFAULT_FROM,
            reply_to=email_in.reply_to,
            subject=email_in.subject,
            body_html=email_in.body_html,
            body_text=email_in.body_text,
            emailable_id=email_in.emailable_id,
            emailable_type=email_in.emailable_type,
            campaign_id=email_in.campaign_id,
            scheduled_at=email_in.scheduled_at,
            metadata_=email_in.metadata_,
            status="pending",
            max_attempts=settings.EMAIL_MAX_ATTEMPTS,
        ),
    )

    # Attach existing documents; inline metadata (CID) rides on the document.
    if email_in.attachments:
        await attach_documents_to_entity(
            db, "Email", str(email.id),
            [a.document_id for a in email_in.attachments],
            metadata_by_id={
                a.document_id: {"is_inline": a.is_inline, "content_id": a.content_id}
                for a in email_in.attachments
            },
        )

    await record_activity(
        db, action="email_queued", actor_id=actor_id,
        subject_type="Email", subject_id=email.id,
        changes={"to": list(email_in.to), "subject": email_in.subject},
    )

    from app.tasks.emails import send_email  # lazy: avoid task import cycle

    eta = email_in.scheduled_at if email_in.scheduled_at else None
    send_email.apply_async(kwargs={"email_id": email.id}, eta=eta, countdown=None if eta else 2)
    logger.info("email_queued", email_id=email.id, scheduled=bool(eta))
    return email


async def get_email(db: AsyncSession, email_id: int) -> Email:
    email = await crud.get_email(db, email_id)
    if email is None:
        raise NotFoundError("Email not found")
    return email


# ── Resend webhooks ──────────────────────────────────────────────────────────

def verify_resend_signature(payload: bytes, headers: dict[str, str]) -> None:
    """Verify the svix signature Resend signs webhooks with.

    Skipped (log-only) when RESEND_WEBHOOK_SECRET is unset — dev convenience;
    ALWAYS set the secret in production.
    """
    secret = settings.RESEND_WEBHOOK_SECRET
    if not secret:
        logger.warning("resend_webhook_unverified", reason="RESEND_WEBHOOK_SECRET not set")
        return

    msg_id = headers.get("svix-id", "")
    timestamp = headers.get("svix-timestamp", "")
    signatures = headers.get("svix-signature", "")
    if not (msg_id and timestamp and signatures):
        raise AuthError("Missing webhook signature headers")

    secret_bytes = secret.removeprefix("whsec_").encode()
    import base64

    signed = f"{msg_id}.{timestamp}.{payload.decode()}".encode()
    expected = base64.b64encode(hmac.new(base64.b64decode(secret_bytes), signed, hashlib.sha256).digest()).decode()
    provided = {sig.split(",", 1)[-1] for sig in signatures.split(" ")}
    if not any(hmac.compare_digest(expected, p) for p in provided):
        raise AuthError("Invalid webhook signature")


_EVENT_STATUS = {
    "email.delivered": "delivered",
    "email.bounced": "bounced",
    "email.complained": "complained",
    "email.delivery_delayed": None,  # event recorded, status unchanged
    "email.opened": None,
    "email.clicked": None,
}


async def process_resend_webhook(db: AsyncSession, payload: dict) -> bool:
    """Apply one Resend event. Returns False when the email is unknown
    (2xx to the provider anyway — webhooks must never retry-storm us)."""
    event_type = payload.get("type", "")
    data = payload.get("data") or {}
    provider_msg_id = data.get("email_id")
    if not provider_msg_id:
        return False

    email = await crud.get_by_provider_message_id(db, str(provider_msg_id))
    if email is None:
        logger.warning("resend_webhook_unknown_email", provider_message_id=provider_msg_id)
        return False

    now = datetime.now(UTC)
    db.add(
        EmailEvent(
            email_id=email.id,
            event_type=event_type,
            event_at=now,
            url=(data.get("click") or {}).get("link"),
            ip_address=(data.get("click") or {}).get("ipAddress"),
            user_agent=(data.get("click") or {}).get("userAgent"),
            provider_event_id=data.get("id") or payload.get("id"),
            provider_data=data,
        )
    )

    if event_type == "email.delivered":
        email.push_status("delivered")
        email.delivered_at = now
    elif event_type == "email.bounced":
        email.push_status("bounced", (data.get("bounce") or {}).get("message"))
        email.bounce_type = (data.get("bounce") or {}).get("subType") or "hard"
        email.failed_at = now
    elif event_type == "email.opened":
        email.open_count = (email.open_count or 0) + 1
        email.last_opened_at = now
        email.first_opened_at = email.first_opened_at or now
    elif event_type == "email.clicked":
        email.click_count = (email.click_count or 0) + 1
        email.first_clicked_at = email.first_clicked_at or now

    await db.flush()
    logger.info("resend_webhook_processed", email_id=email.id, event_type=event_type)
    return True
