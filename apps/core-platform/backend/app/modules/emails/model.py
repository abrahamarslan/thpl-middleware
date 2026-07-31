"""Email models (docs/modules-to-implement/email.md).

``emails`` is the outbound message record; ``email_events`` the provider
webhook timeline; ``email_links`` per-link click aggregates. Recipients are
JSONB arrays so Postgres JSON operators can answer "every email ever sent
to x@y.com whether To, CC or BCC" without string parsing.
"""

import uuid as uuid_mod
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import IntPKMixin, TimestampMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.documents.mixins import HasDocumentsMixin
from app.modules.tags.mixins import HasTagsMixin


class Email(IntPKMixin, TimestampMixin, SoftDeleteFilteredMixin, HasDocumentsMixin, HasTagsMixin, Base):
    __tablename__ = "emails"

    uuid: Mapped[uuid_mod.UUID] = mapped_column(
        PgUUID(as_uuid=True), default=uuid_mod.uuid4, unique=True, index=True
    )

    # Polymorphic subject (what the email is ABOUT: an Invoice, a User, ...)
    emailable_id: Mapped[str | None] = mapped_column(String(64), index=True)
    emailable_type: Mapped[str | None] = mapped_column(String(100), index=True)

    # Recipients (JSONB arrays of address strings)
    email_to: Mapped[list] = mapped_column(JSONB, nullable=False)
    email_cc: Mapped[list | None] = mapped_column(JSONB)
    email_bcc: Mapped[list | None] = mapped_column(JSONB)
    all_recipients: Mapped[list | None] = mapped_column(JSONB, comment="Deduped union for fast lookups")

    # Sender
    email_from: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email_from_name: Mapped[str | None] = mapped_column(String(255))
    reply_to: Mapped[str | None] = mapped_column(String(255))
    return_path: Mapped[str | None] = mapped_column(String(255))

    # Content
    subject: Mapped[str | None] = mapped_column(String(998))  # RFC 2822 line limit
    preheader: Mapped[str | None] = mapped_column(String(255))
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    body_type: Mapped[str | None] = mapped_column(String(20), default="html")

    # Templates
    template_id: Mapped[str | None] = mapped_column(String(100))
    template_name: Mapped[str | None] = mapped_column(String(255))
    template_data: Mapped[dict | None] = mapped_column(JSONB)
    locale: Mapped[str | None] = mapped_column(String(10), default="en")

    # Source / organization
    campaign_id: Mapped[str | None] = mapped_column(String(100), index=True)
    batch_id: Mapped[str | None] = mapped_column(String(100), index=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)

    # Status & processing (pending -> processing -> sent -> delivered | failed | bounced)
    status: Mapped[str | None] = mapped_column(String(20), default="pending", index=True)
    status_message: Mapped[str | None] = mapped_column(String(500))
    error_message: Mapped[str | None] = mapped_column(Text)
    status_history: Mapped[list | None] = mapped_column(JSONB, default=list)

    # Retries
    attempts: Mapped[int | None] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int | None] = mapped_column(Integer, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    # Configuration
    is_bulk: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_transactional: Mapped[bool | None] = mapped_column(Boolean, default=True)
    track_opens: Mapped[bool | None] = mapped_column(Boolean, default=True)
    track_clicks: Mapped[bool | None] = mapped_column(Boolean, default=True)
    provider: Mapped[str | None] = mapped_column(String(50), default="resend")
    provider_message_id: Mapped[str | None] = mapped_column(String(100), index=True)
    provider_response: Mapped[dict | None] = mapped_column(JSONB)

    # Lifecycle timestamps
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Engagement timestamps
    first_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Metrics
    open_count: Mapped[int | None] = mapped_column(Integer, default=0)
    click_count: Mapped[int | None] = mapped_column(Integer, default=0)
    bounce_type: Mapped[str | None] = mapped_column(String(20), comment="soft | hard")
    spam_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    events: Mapped[list["EmailEvent"]] = relationship(
        back_populates="email", cascade="all, delete-orphan", lazy="selectin"
    )
    links: Mapped[list["EmailLink"]] = relationship(
        back_populates="email", cascade="all, delete-orphan", lazy="selectin"
    )

    def push_status(self, status: str, message: str | None = None) -> None:
        """Transition + append to the status_history journal."""
        from datetime import UTC

        self.status = status
        self.status_message = message
        history = list(self.status_history or [])
        history.append({"status": status, "at": datetime.now(UTC).isoformat(), "message": message})
        self.status_history = history[-50:]


class EmailEvent(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "email_events"

    uuid: Mapped[uuid_mod.UUID] = mapped_column(PgUUID(as_uuid=True), default=uuid_mod.uuid4, unique=True)
    email_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("emails.id", ondelete="CASCADE"), index=True
    )

    event_type: Mapped[str | None] = mapped_column(String(50), index=True)
    event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    url: Mapped[str | None] = mapped_column(String(2048), comment="Clicked URL")
    location: Mapped[str | None] = mapped_column(String(255))

    provider_event_id: Mapped[str | None] = mapped_column(String(100), index=True)
    provider_data: Mapped[dict | None] = mapped_column(JSONB)

    email: Mapped[Email] = relationship(back_populates="events")


class EmailLink(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "email_links"

    uuid: Mapped[uuid_mod.UUID] = mapped_column(PgUUID(as_uuid=True), default=uuid_mod.uuid4, unique=True)
    email_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("emails.id", ondelete="CASCADE"), index=True
    )

    original_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    link_hash: Mapped[str | None] = mapped_column(String(128), index=True)

    click_count: Mapped[int | None] = mapped_column(Integer, default=0)
    unique_clicks: Mapped[int | None] = mapped_column(Integer, default=0)
    first_clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    email: Mapped[Email] = relationship(back_populates="links")
