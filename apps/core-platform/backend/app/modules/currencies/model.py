"""``currency`` schema — the canonical currency master and rate history.

    Currency      one canonical currency per tenant. Carries the business
                  identity (code/symbol/name), display & formatting rules,
                  rounding policy, accounting linkage, risk policy,
                  verification workflow, and a *cache* of the current rate.
    ExchangeRate  append-only, effective-dated rate history. THE source of
                  truth for rates; ``Currency.exchange_rate`` is only a
                  denormalized cache (refreshed from here).

Scoping & provenance
  * ``organization_id`` is NOT NULL (``OrgEntityMixin``): every currency and
    rate belongs to one organization; ``tenant_id`` is the hard isolation key.
    The composite FK ``(tenant_id, organization_id)`` →
    ``org_management.organizations(tenant_id, id)`` proves the organization
    belongs to the same tenant.
  * ``owner_type`` / ``owner_id`` (``PolymorphicOwnerMixin``) are the
    provenance pair: who the row is held for — a tenant, an organization, the
    connection that produced it or the platform.
  * External identity (Zoho ids) lives on the L3 edge; ``currency_id`` /
    ``zoho_id`` are retained here only as L1 source echoes for reconciliation.

Mixins replace what the reference design declared by hand: tenancy + audit
(``created_by`` / ``created_by_name`` / ``updated_by`` / ``updated_by_name``),
``status``, ``row_version``, ``app_version`` / ``app_metadata``
(``OrgEntityMixin``); ``verification_*`` (``VerificationMixin``);
``deactivated_*`` (``DeactivationMixin``); ``deleted_*``
(``SoftDeleteFilteredMixin``, with the automatic filter); ``owner_*``
(``PolymorphicOwnerMixin``).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    BigIntPKWithUUIDMixin,
    DeactivationMixin,
    OrgEntityMixin,
    PolymorphicOwnerMixin,
    VerificationMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.currencies.enums import (
    CurrencyKind,
    CurrencyOwnerType,
    CurrencyStatus,
    ExchangeRateStatus,
    RateUpdateFrequency,
    RoundingMethod,
    SymbolPlacement,
    VerificationStatus,
    values,
)

CURRENCY_SCHEMA = "currency"


class Currency(
    BigIntPKWithUUIDMixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
    PolymorphicOwnerMixin, SoftDeleteFilteredMixin, Base,
):
    """Canonical currency master (one live row per tenant + currency code)."""

    __tablename__ = "currencies"
    __table_args__ = (
        # Target of exchange_rates' composite (tenant_id, currency_id) FK.
        UniqueConstraint("tenant_id", "id", name="uq_currencies_tenant_id"),
        CheckConstraint(f"kind IS NULL OR kind IN ({values(CurrencyKind)})", name="chk_currency_kind"),
        CheckConstraint(f"status IN ({values(CurrencyStatus)})", name="chk_currency_status"),
        CheckConstraint(f"verification_status IN ({values(VerificationStatus)})",
                        name="chk_currency_verification_status"),
        CheckConstraint(f"owner_type IN ({values(CurrencyOwnerType)})", name="chk_currency_owner_type"),
        CheckConstraint(
            f"symbol_placement IS NULL OR symbol_placement IN ({values(SymbolPlacement)})",
            name="chk_currency_symbol_placement",
        ),
        CheckConstraint(
            f"rounding_method IS NULL OR rounding_method IN ({values(RoundingMethod)})",
            name="chk_currency_rounding_method",
        ),
        CheckConstraint(
            f"rate_update_frequency IS NULL OR rate_update_frequency IN ({values(RateUpdateFrequency)})",
            name="chk_currency_rate_update_frequency",
        ),
        # FIAT codes are ISO 4217; other kinds are free-form.
        CheckConstraint(
            "kind IS DISTINCT FROM 'fiat' OR currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'",
            name="chk_currency_code_iso4217",
        ),
        CheckConstraint("exchange_rate IS NULL OR exchange_rate >= 0", name="chk_currency_exchange_rate"),
        CheckConstraint("price_precision IS NULL OR price_precision >= 0", name="chk_currency_price_precision"),
        CheckConstraint("rounding_precision IS NULL OR rounding_precision >= 0",
                        name="chk_currency_rounding_precision"),
        CheckConstraint("rate_fluctuation_threshold IS NULL OR rate_fluctuation_threshold >= 0",
                        name="chk_currency_fluctuation_threshold"),
        CheckConstraint("region_specific_formatting IS NULL OR jsonb_typeof(region_specific_formatting) = 'object'",
                        name="chk_currency_region_formatting_object"),
        CheckConstraint("risk_management_rules IS NULL OR jsonb_typeof(risk_management_rules) = 'object'",
                        name="chk_currency_risk_rules_object"),
        CheckConstraint("currency_formatter IS NULL OR jsonb_typeof(currency_formatter) = 'object'",
                        name="chk_currency_formatter_object"),
        # One live row per (tenant, code).
        Index("uq_currencies_tenant_code", "tenant_id", "currency_code", unique=True,
              postgresql_where=text("deleted_at IS NULL AND currency_code IS NOT NULL")),
        # Exactly one base / one default currency per (tenant, organization).
        Index("uq_currencies_one_base", "tenant_id", "organization_id", unique=True,
              postgresql_where=text("is_base_currency AND deleted_at IS NULL")),
        Index("uq_currencies_one_default", "tenant_id", "organization_id", unique=True,
              postgresql_where=text("is_default_currency AND deleted_at IS NULL")),
        Index("ix_currencies_owner", "tenant_id", "owner_type", "owner_id",
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_currencies_kind_active", "tenant_id", "kind", "is_active",
              postgresql_where=text("deleted_at IS NULL")),
        {"schema": CURRENCY_SCHEMA,
         "comment": "Canonical currency master (one live row per tenant + currency code)."},
    )

    # ---- L1 source echoes (canonical external identity lives on the edge) ---
    currency_id: Mapped[str | None] = mapped_column(
        Text, comment="L1 source echo of Zoho's currency_id (opaque, preserved exactly)",
    )
    zoho_id: Mapped[str | None] = mapped_column(Text, comment="L1 source echo of the Zoho Books id")
    currency_code: Mapped[str | None] = mapped_column(
        String(3), comment="ISO 4217 alphabetic code (e.g. INR); NULL = unclassified",
    )
    currency_symbol: Mapped[str | None] = mapped_column(Text, comment="Display symbol, e.g. '₹', '$'")
    currency_name: Mapped[str | None] = mapped_column(Text, comment="Canonical name, e.g. 'Indian Rupee'")
    iso_numeric_code: Mapped[str | None] = mapped_column(
        Text, comment="ISO 4217 numeric code (3 digits), kept as text; '' -> NULL at ingest",
    )
    country_code: Mapped[str | None] = mapped_column(Text, comment="ISO 3166 country code (L1 echo)")

    # ---- classification ----------------------------------------------------
    kind: Mapped[str | None] = mapped_column(
        Text, default=CurrencyKind.FIAT.value, server_default=text("'fiat'"),
        comment="fiat / crypto / metals / historical; NULL = unclassified",
    )

    # ---- formatting & display ---------------------------------------------
    price_precision: Mapped[int | None] = mapped_column(
        Integer, default=2, server_default=text("2"), comment="Decimal places for prices (JPY = 0)",
    )
    decimal_separator: Mapped[str | None] = mapped_column(
        String(1), default=".", server_default=text("'.'"), comment="Decimal separator symbol",
    )
    thousand_separator: Mapped[str | None] = mapped_column(
        String(1), default=",", server_default=text("','"), comment="Thousands separator",
    )
    symbol_placement: Mapped[str | None] = mapped_column(
        Text, default=SymbolPlacement.BEFORE.value, server_default=text("'before'"),
        comment="before / after",
    )
    space_between_symbol: Mapped[bool | None] = mapped_column(
        Boolean, default=False, server_default=text("false"),
        comment="Whether a space is rendered between symbol and amount",
    )
    secondary_grouping_size: Mapped[int | None] = mapped_column(
        Integer, default=3, server_default=text("3"),
        comment="Digits in the group after the first (Indian lakh/crore = 2; default 3)",
    )
    currency_name_formatted: Mapped[str | None] = mapped_column(
        Text, comment="L1 display twin, e.g. 'INR- Indian Rupee' (recomputed by the API)",
    )
    currency_format: Mapped[str | None] = mapped_column(
        Text, comment="L1 display twin of the sample formatted number",
    )
    currency_formatter: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), comment="L1 source echo of Zoho's currency_formatter object (raw)",
    )
    region_specific_formatting: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), comment="Region-specific formatting rules (object)",
    )
    use_regional_settings: Mapped[bool | None] = mapped_column(
        Boolean, default=False, server_default=text("false"),
        comment="Apply region_specific_formatting instead of tenant defaults",
    )

    # ---- status flags ------------------------------------------------------
    is_default_currency: Mapped[bool | None] = mapped_column(
        Boolean, default=False, server_default=text("false"),
        comment="Default display currency for the organization (one, partial-unique enforced)",
    )
    is_base_currency: Mapped[bool | None] = mapped_column(
        Boolean, default=False, server_default=text("false"),
        comment="Base/accounting currency (one per organization, partial-unique enforced)",
    )
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, default=True, server_default=text("true"),
        comment="Operational kill-switch; distinct from status and soft-delete",
    )
    allow_transactions: Mapped[bool | None] = mapped_column(
        Boolean, default=True, server_default=text("true"),
        comment="Whether documents may be transacted in this currency",
    )

    # ---- exchange-rate cache (truth is currency.exchange_rates) -----------
    exchange_rate: Mapped[float | None] = mapped_column(
        Numeric(20, 10), server_default=text("1.00"),
        comment="CACHE of the latest rate vs the base currency; never the source of record",
    )
    exchange_rate_as_of: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="As-of instant of the cached exchange_rate",
    )
    exchange_rate_last_updated: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="When the cached exchange_rate was last refreshed",
    )
    exchange_rate_source: Mapped[str | None] = mapped_column(
        Text, comment="Open vocabulary: zoho / rbi / ecb / manual / ... (no CHECK)",
    )
    historical_rates: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), comment="L1 source mirror only; canonical history is currency.exchange_rates",
    )
    auto_update_rate: Mapped[bool | None] = mapped_column(
        Boolean, default=False, server_default=text("false"),
        comment="Our flag: refresh the rate automatically",
    )
    auto_exchange_rate_enabled: Mapped[bool | None] = mapped_column(
        Boolean, comment="Zoho's auto_exchange_rate_enabled echo; NULL = unknown",
    )
    rate_update_frequency: Mapped[str | None] = mapped_column(
        Text, comment="hourly / daily / weekly / manual; NULL = unspecified",
    )

    # ---- rounding policy ---------------------------------------------------
    rounding_method: Mapped[str | None] = mapped_column(
        Text, default=RoundingMethod.ROUND.value, server_default=text("'round'"), comment="round / ceil / floor",
    )
    rounding_precision: Mapped[int | None] = mapped_column(
        Integer, default=2, server_default=text("2"), comment="Rounding precision for monetary amounts",
    )
    apply_rounding_to_total_only: Mapped[bool | None] = mapped_column(
        Boolean, default=False, server_default=text("false"),
        comment="Round only the document total, not each line",
    )

    # ---- temporal ----------------------------------------------------------
    effective_date: Mapped[dt.date | None] = mapped_column(
        Date, comment="Business date the current rate takes effect (source '' -> NULL)",
    )
    effective_date_formatted: Mapped[str | None] = mapped_column(
        Text, comment="L1 display twin of effective_date (never truth)",
    )

    # ---- integration sync echo --------------------------------------------
    last_api_sync: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Last Zoho API sync instant (freshness truth is sync_cursors)",
    )

    # ---- accounting linkage -----------------------------------------------
    gl_account_code: Mapped[str | None] = mapped_column(
        Text, comment="General-ledger account code (opaque external reference)",
    )
    require_exchange_rate_entry: Mapped[bool | None] = mapped_column(
        Boolean, default=False, server_default=text("false"),
        comment="Force an explicit rate on every foreign-currency document",
    )
    allow_override_rate: Mapped[bool | None] = mapped_column(
        Boolean, default=False, server_default=text("false"), comment="Allow operator rate override",
    )

    # ---- risk & authorization ---------------------------------------------
    rate_fluctuation_threshold: Mapped[float | None] = mapped_column(
        Numeric(5, 2), comment="Alert threshold for rate change (%)",
    )
    risk_management_rules: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), comment="Rules for currency risk management (object)",
    )
    requires_authorization: Mapped[bool | None] = mapped_column(
        Boolean, default=False, server_default=text("false"),
        comment="Rate/currency changes require authorization",
    )

    # ---- extensibility -----------------------------------------------------
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB(none_as_null=True), comment="Sparse, non-indexed tenant extension bucket",
    )

    exchange_rates: Mapped[list["ExchangeRate"]] = relationship(
        "ExchangeRate",
        back_populates="currency",
        primaryjoin="Currency.id == foreign(ExchangeRate.currency_id)",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    @property
    def is_zoho_linked(self) -> bool:
        return self.zoho_id is not None or self.currency_id is not None

    def __repr__(self) -> str:
        return (
            f"<Currency id={self.id} code={self.currency_code!r} "
            f"tenant={self.tenant_id} base={self.is_base_currency}>"
        )


class ExchangeRate(
    BigIntPKWithUUIDMixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
    PolymorphicOwnerMixin, SoftDeleteFilteredMixin, Base,
):
    """One effective-dated exchange rate. The append-only source of truth."""

    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_exchange_rates_tenant_id"),
        # Tenant-scoped parent: a rate can never pair a currency with another tenant.
        ForeignKeyConstraint(
            ["tenant_id", "currency_id"],
            [f"{CURRENCY_SCHEMA}.currencies.tenant_id", f"{CURRENCY_SCHEMA}.currencies.id"],
            name="fk_exchange_rates_currency", ondelete="CASCADE",
        ),
        CheckConstraint("rate >= 0", name="chk_exchange_rate_nonnegative"),
        CheckConstraint(f"status IN ({values(ExchangeRateStatus)})", name="chk_exchange_rate_status"),
        CheckConstraint(f"verification_status IN ({values(VerificationStatus)})",
                        name="chk_exchange_rate_verification_status"),
        CheckConstraint(f"owner_type IN ({values(CurrencyOwnerType)})", name="chk_exchange_rate_owner_type"),
        CheckConstraint("sync_metadata IS NULL OR jsonb_typeof(sync_metadata) = 'object'",
                        name="chk_exchange_rate_sync_metadata_object"),
        # One rate per currency per business date PER SOURCE among live rows.
        # ``rate_source`` joined the key so Zoho and SAP (and an operator) can
        # each quote the same day without overwriting one another; precedence
        # decides which one feeds the Currency.exchange_rate cache.
        Index("uq_exchange_rates_currency_date", "tenant_id", "currency_id", "effective_date",
              "rate_source", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("ix_exchange_rates_currency_date", "currency_id", "effective_date",
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_exchange_rates_owner", "tenant_id", "owner_type", "owner_id",
              postgresql_where=text("deleted_at IS NULL")),
        {"schema": CURRENCY_SCHEMA, "comment": "Append-only, effective-dated exchange-rate history."},
    )

    zoho_id: Mapped[str | None] = mapped_column(
        Text, comment="L1 source echo of the Zoho rate id (canonical external identity on the edge)",
    )
    currency_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="Owning currency (composite tenant FK)",
    )
    rate: Mapped[float] = mapped_column(Numeric(15, 6), nullable=False, comment="Exchange rate; never float-parsed")
    effective_date: Mapped[dt.date] = mapped_column(
        Date, nullable=False, comment="Business date the rate is effective",
    )
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, default=True, server_default=text("true"), comment="Operational kill-switch",
    )
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="L1 source sync echo (freshness truth is sync_cursors)",
    )
    sync_metadata: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), comment="L1 source sync envelope echo (object)")

    # ---- rate provenance (open vocabulary, no CHECK) -----------------------
    # NOT NULL because it is part of the uniqueness key: a NULL there would
    # make every unsourced rate distinct from every other and let duplicates in.
    rate_source: Mapped[str] = mapped_column(
        Text, nullable=False, default="manual", server_default=text("'manual'"),
        comment="zoho / rbi / ecb / manual / ... (part of the per-day uniqueness key)",
    )
    rate_type: Mapped[str | None] = mapped_column(Text, comment="e.g. spot / reference / average; NULL = unspecified")

    # ---- source identity (the crosswalk owns currency identity; a rate is a
    # child row with its own upstream id, so it carries its own echo) --------
    external_source: Mapped[str | None] = mapped_column(
        Text, comment="Source system that produced this rate (zoho / sap / ...)",
    )
    external_id: Mapped[str | None] = mapped_column(
        Text, comment="The source's id for this rate, verbatim (e.g. Zoho exchange_rate_id)",
    )

    currency: Mapped["Currency"] = relationship(
        "Currency",
        back_populates="exchange_rates",
        primaryjoin="foreign(ExchangeRate.currency_id) == Currency.id",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return (
            f"<ExchangeRate id={self.id} currency_id={self.currency_id} "
            f"date={self.effective_date} rate={self.rate}>"
        )


__all__ = ["CURRENCY_SCHEMA", "Currency", "ExchangeRate"]