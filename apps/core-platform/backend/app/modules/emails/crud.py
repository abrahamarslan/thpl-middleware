"""Data access for emails (crud layer — no business logic)."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.modules.emails.model import Email


async def create_email(db: AsyncSession, values: dict) -> Email:
    email = Email(**values)
    db.add(email)
    await db.flush()
    return email


async def get_email(db: AsyncSession, email_id: int) -> Email | None:
    stmt = (
        select(Email)
        .where(Email.id == email_id)
        .options(selectinload(Email.documents))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_by_provider_message_id(db: AsyncSession, provider_message_id: str) -> Email | None:
    stmt = select(Email).where(Email.provider_message_id == provider_message_id).limit(1)
    return await db.scalar(stmt)


async def list_emails(
    db: AsyncSession,
    *,
    status: str | None = None,
    recipient: str | None = None,
    emailable_type: str | None = None,
    emailable_id: str | None = None,
    template_name: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[Email]:
    # Slim list query: fetch only what EmailSlimOut renders — never message
    # bodies or relationship collections (Slim/Fat doctrine).
    stmt = select(Email).options(
        load_only(
            Email.id,
            Email.uuid,
            Email.email_to,
            Email.subject,
            Email.status,
            Email.template_name,
            Email.open_count,
            Email.click_count,
            Email.scheduled_at,
            Email.sent_at,
            Email.delivered_at,
            Email.created_at,
        )
    )
    if status:
        stmt = stmt.where(Email.status == status)
    if recipient:
        # JSONB containment: matches To, CC or BCC via the deduped union column
        stmt = stmt.where(Email.all_recipients.contains([recipient]))
    if emailable_type:
        stmt = stmt.where(Email.emailable_type == emailable_type)
    if emailable_id:
        stmt = stmt.where(Email.emailable_id == emailable_id)
    if template_name:
        stmt = stmt.where(Email.template_name == template_name)
    if date_from:
        stmt = stmt.where(Email.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Email.created_at <= date_to)
    stmt = stmt.order_by(Email.id.desc()).offset((page - 1) * page_size).limit(page_size)
    return list((await db.scalars(stmt)).all())


async def email_stats(
    db: AsyncSession, *, since: datetime | None = None, until: datetime | None = None
) -> dict:
    """Aggregate delivery/engagement counters for a time window.

    Counts come from the `emails` aggregates (kept current by the webhook);
    the per-event timeline (when/where/who) lives in `email_events`.
    """
    stmt = select(
        func.count(Email.id).label("total"),
        func.count(Email.id).filter(Email.status == "sent").label("sent"),
        func.count(Email.id).filter(Email.status == "delivered").label("delivered"),
        func.count(Email.id).filter(Email.status == "bounced").label("bounced"),
        func.count(Email.id).filter(Email.status == "failed").label("failed"),
        func.count(Email.id).filter(Email.status == "suppressed").label("suppressed"),
        func.coalesce(func.sum(Email.open_count), 0).label("opens"),
        func.coalesce(func.sum(Email.click_count), 0).label("clicks"),
    )
    if since:
        stmt = stmt.where(Email.created_at >= since)
    if until:
        stmt = stmt.where(Email.created_at <= until)
    row = (await db.execute(stmt)).one()
    counts = row._mapping
    total = counts["total"] or 0
    delivered = counts["delivered"] or 0
    return {
        "total": total,
        "sent": counts["sent"] or 0,
        "delivered": delivered,
        "bounced": counts["bounced"] or 0,
        "failed": counts["failed"] or 0,
        "suppressed": counts["suppressed"] or 0,
        "opens": counts["opens"] or 0,
        "clicks": counts["clicks"] or 0,
        # Rates are 0 when the denominator is 0 — never divide by zero.
        "delivery_rate": round(delivered / total, 4) if total else 0.0,
        "open_rate": round((counts["opens"] or 0) / delivered, 4) if delivered else 0.0,
        "click_rate": round((counts["clicks"] or 0) / delivered, 4) if delivered else 0.0,
        "since": since,
        "until": until,
    }
