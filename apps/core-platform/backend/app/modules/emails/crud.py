"""Data access for emails (crud layer — no business logic)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
    page: int = 1,
    page_size: int = 50,
) -> list[Email]:
    stmt = select(Email).options(selectinload(Email.documents))
    if status:
        stmt = stmt.where(Email.status == status)
    if recipient:
        # JSONB containment: matches To, CC or BCC via the deduped union column
        stmt = stmt.where(Email.all_recipients.contains([recipient]))
    if emailable_type:
        stmt = stmt.where(Email.emailable_type == emailable_type)
    if emailable_id:
        stmt = stmt.where(Email.emailable_id == emailable_id)
    stmt = stmt.order_by(Email.id.desc()).offset((page - 1) * page_size).limit(page_size)
    return list((await db.scalars(stmt)).all())
