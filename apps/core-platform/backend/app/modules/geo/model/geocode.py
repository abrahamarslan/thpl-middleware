"""Provenance layer — every external geo-API payload, stored exactly once.

One table for Google Geocoding / Places / Directions / Distance Matrix /
Roads / Timezone, MapMyIndia, Nominatim … Consumers keep their extracted
fields plus a ``geocode_call_id`` pointer; the raw payload lives here alone.

Three reasons it is worth a table of its own:

* **cost** — a hit on ``(provider, api_type, request_hash)`` is a request we
  do not pay for. Geocoding the same warehouse address on every import is the
  single easiest way to burn a maps budget.
* **audit** — "why is this customer pinned in the wrong district" is
  answerable a year later, against the exact bytes the provider returned.
* **licence** — Google permits caching geocode results for 30 days but
  ``place_id`` indefinitely. A per-row ``expires_at`` plus one purge job over
  THIS table clears every raw payload in the platform in one sweep; no other
  table needs to know the rule.

Append-only: a LEDGER in the table-class sense (tenant scope + app metadata,
no ``row_version``, no soft delete — you do not edit or "delete" evidence).
The cache is scoped per tenant on purpose: a request hash contains the
customer address that was looked up, so a shared cache would leak one
tenant's address book into another's lookups.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import AppMetaMixin, BigIntPKWithUUIDMixin, MultiTenantMixin
from app.modules.geo.enums import GeoApiType, values
from app.modules.geo.model.reference import GEO_SCHEMA


class GeocodeApiCall(BigIntPKWithUUIDMixin, MultiTenantMixin, AppMetaMixin, Base):
    """One external geo-API request/response. Append-only."""

    __tablename__ = "geocode_api_calls"
    __table_args__ = (
        CheckConstraint(f"api_type IN ({values(GeoApiType)})", name="chk_geocode_call_api_type"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="chk_geocode_call_latency"),
        # THE cache probe. Ordered by created_at so "newest usable answer" is
        # the first row read, not a sort over every historical call.
        Index("ix_geocode_calls_cache", "tenant_id", "provider", "api_type", "request_hash",
              text("created_at DESC")),
        Index("ix_geocode_calls_expiry", "expires_at", postgresql_where=text("expires_at IS NOT NULL")),
        Index("ix_geocode_calls_place", "resolved_place_id",
              postgresql_where=text("resolved_place_id IS NOT NULL")),
        {"schema": GEO_SCHEMA, "comment": "Raw external geo-API payloads (append-only, TOS-expiring)."},
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False, comment="google / mapmyindia / …")
    api_type: Mapped[str] = mapped_column(String(32), nullable=False)
    request_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="sha256 of the normalized request params — the cache key",
    )
    request_params: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="Normalized request parameters")
    response_raw: Mapped[dict | None] = mapped_column(
        JSONB, comment="THE untouched provider payload (the only copy platform-wide)",
    )
    response_status: Mapped[str | None] = mapped_column(
        String(64), comment="Provider status: OK / ZERO_RESULTS / OVER_QUERY_LIMIT …",
    )
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_units: Mapped[float | None] = mapped_column(
        Numeric(10, 4), comment="Billing units consumed — spend tracking per tenant",
    )
    resolved_place_id: Mapped[int | None] = mapped_column(
        BigInteger,
        # places → geocode_api_calls (provenance) and geocode_api_calls →
        # places (result) is a genuine cycle; the FK is added after both exist.
        ForeignKey(f"{GEO_SCHEMA}.places.id", ondelete="SET NULL",
                   name="fk_geocode_calls_place", use_alter=True),
        comment="The place this call resolved to, if any",
    )
    requested_by: Mapped[int | None] = mapped_column(
        BigInteger, comment="users.id that triggered the call (NULL = system)",
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    expires_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="End of the provider's cache window; the purge job sweeps on this",
    )

    @property
    def is_usable(self) -> bool:
        """A cached answer is usable while its licence window is open."""
        if self.expires_at is None:
            return True
        return self.expires_at > dt.datetime.now(dt.UTC)

    def __repr__(self) -> str:
        return f"<GeocodeApiCall id={self.id} {self.provider}/{self.api_type}>"
