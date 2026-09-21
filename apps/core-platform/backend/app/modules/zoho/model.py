"""SQLAlchemy models for the Zoho integration (model layer)."""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, LedgerMixin, TimestampMixin


class ZohoSyncState(LedgerMixin, Base):
    """Tracks the last successful sync per Zoho entity (items, contacts, ...).

    Celery Beat schedules periodic syncs; workers read/update this row to
    perform incremental pulls instead of full refetches.
    """

    __tablename__ = "zoho_sync_state"

    entity: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    detail: Mapped[str | None] = mapped_column(String(512))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ZohoOAuthCredential(IntPKMixin, LedgerMixin, TimestampMixin, Base):
    """The Zoho refresh token at rest — encrypted, never audited, never cached.

    Why its own table instead of the hierarchical settings module:
      * ``system_settings_service.set_setting`` writes every change into
        ``setting_audit_logs`` (old *and* new value), which would persist the
        refresh token in plaintext, forever, in a table built for reading;
      * Redis is LRU-evictable, so it is a cache, never the record of truth;
      * the token is a credential, so it is stored encrypted (pgcrypto
        ``pgp_sym_encrypt``) with the key held only in the environment.

    Reads and writes go through ``app.modules.zoho.core.auth``; nothing else
    touches this table. ``credential_version`` lets every process notice a
    rotation without polling the row on each call.
    """

    __tablename__ = "zoho_oauth_credentials"

    org_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(
        LargeBinary, comment="pgp_sym_encrypt(refresh_token, ZOHO_TOKEN_ENCRYPTION_KEY)"
    )
    api_domain: Mapped[str | None] = mapped_column(
        String(255), comment="api_domain returned by Zoho; validated against the configured base URLs"
    )
    scope: Mapped[str | None] = mapped_column(String(1024))
    credential_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_by: Mapped[int | None] = mapped_column(BigInteger, comment="users.id of the operator who reconnected")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
