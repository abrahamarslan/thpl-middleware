"""``auth.user_sessions`` — one row per sign-in (docs/auth/sessions.md).

First-party tokens carry the session's uuid as ``sid``. Every authenticated request checks the session
(``users/sessions.py``, Redis-cached), so revoking it — logout, a sign-in on another device under a
single-session rule, refresh-token reuse, a password change — takes effect at the NEXT request, not
when the JWT expires.

LEDGER-shaped (no ``row_version``): a session is created, touched (``last_seen_at``, throttled), rotated
(``refresh_jti_hash``) and revoked; it is never edited by a person. ``drain_until`` is the telemetry-drain
grant of a field-app session displaced by a newer sign-in: until then it may still upload the location
fixes it queued while it was signed in (and nothing else).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import AppMetaMixin, BigIntPKWithUUIDv7Mixin, MultiTenantMixin, TimestampMixin

AUTH_SCHEMA = "auth"
CLIENT_TYPES = ("field_app", "web", "service")
REVOKE_REASONS = ("logout", "logout_all", "signed_in_elsewhere", "refresh_reuse", "admin", "password_changed",
                  "user_deactivated", "expired")


class UserSession(BigIntPKWithUUIDv7Mixin, MultiTenantMixin, AppMetaMixin, TimestampMixin, Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
                             name="fk_user_sessions_user", ondelete="CASCADE"),
        CheckConstraint(f"client_type IN ({', '.join(repr(c) for c in CLIENT_TYPES)})",
                        name="chk_user_sessions_client_type"),
        CheckConstraint(f"revoked_reason IS NULL OR revoked_reason IN ({', '.join(repr(r) for r in REVOKE_REASONS)})",
                        name="chk_user_sessions_revoked_reason"),
        CheckConstraint("(revoked_at IS NULL) = (revoked_reason IS NULL)", name="chk_user_sessions_revoked_pair"),
        Index("ix_user_sessions_live", "tenant_id", "user_id", "client_type",
              postgresql_where=text("revoked_at IS NULL")),
        Index("ix_user_sessions_user", "tenant_id", "user_id", text("created_at DESC")),
        {"schema": AUTH_SCHEMA, "comment": "First-party sign-in sessions (tokens carry the uuid as sid)."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_type: Mapped[str] = mapped_column(String(12), nullable=False, comment="field_app | web | service")
    installation_id: Mapped[str | None] = mapped_column(String(64), comment="fieldops.devices.installation_id, if sent")
    device_label: Mapped[str | None] = mapped_column(String(160), comment="e.g. 'android · Samsung Galaxy M14'")
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                      server_default=text("now()"))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                    comment="Absolute cap (SESSION_MAX_DAYS)")
    refresh_jti_hash: Mapped[str | None] = mapped_column(String(64), comment="sha256 of the CURRENT refresh jti")
    previous_refresh_jti_hash: Mapped[str | None] = mapped_column(
        String(64), comment="sha256 of the jti it replaced — presenting it again = reuse = theft signal",
    )
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(24))
    revoked_by_session_id: Mapped[int | None] = mapped_column(BigInteger, comment="The sign-in that displaced it")
    drain_until: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Displaced field session: may upload queued fixes until then",
    )

    @property
    def is_live(self) -> bool:
        return self.revoked_at is None and self.expires_at > dt.datetime.now(dt.UTC)

    def __repr__(self) -> str:
        return f"<UserSession {self.uuid} user={self.user_id} {self.client_type} revoked={self.revoked_reason}>"


__all__ = ["AUTH_SCHEMA", "CLIENT_TYPES", "REVOKE_REASONS", "UserSession"]
