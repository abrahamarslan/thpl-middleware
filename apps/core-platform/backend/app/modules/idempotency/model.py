"""``core.idempotency_keys`` — replay-safe mutations for offline clients.

An offline app replays its queue on reconnect, and a flaky network makes it resend a
request whose response it never saw. Creates are made safe structurally (the client names
the entity with its own UUIDv7), but a TRANSITION ("end this visit") has no row to collide
with. This ledger closes that gap: the first request with a key stores its response; a
replay with the same fingerprint gets that response back byte for byte; the same key
with a different body is refused (409 ``idempotency_key_reused``).

Platform-wide on purpose (schema ``core``): field operations use it first, DLP proof of
delivery next. LEDGER. ``organization_id`` stays NULL — the key belongs to a user, not a
branch.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, LedgerMixin, TimestampMixin

CORE_SCHEMA = "core"


class IdempotencyKey(BigIntPKWithUUIDv7Mixin, LedgerMixin, TimestampMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "key", name="uq_idempotency_keys_user_key"),
        Index("ix_idempotency_keys_expires", "expires_at"),
        CheckConstraint("state IN ('in_flight','completed')", name="chk_idempotency_keys_state"),
        {"schema": CORE_SCHEMA, "comment": "Stored responses of client-keyed mutations (offline replay safety)."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    key: Mapped[uuid_lib.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False,
                                               comment="Client-generated key (X-Idempotency-Key)")
    route: Mapped[str] = mapped_column(String(200), nullable=False, comment="METHOD + route template")
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False,
                                                     comment="sha256(method + route + canonical body)")
    state: Mapped[str] = mapped_column(String(12), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<IdempotencyKey user={self.user_id} {self.route} {self.state}>"
