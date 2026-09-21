"""Vocabularies for the currency module (docs/...).

Every value is stored in a ``text``/``varchar`` column guarded by a CHECK
constraint: the values are data, the closed sets below are contract. Source
vocabularies that Zoho (or a future rate feed) may extend without notice —
``exchange_rate_source`` / ``rate_source`` — deliberately have **no** enum
here; they are open ``text``, normalized app-side.
"""

from __future__ import annotations

import enum


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum, so the
    constraint and the vocabulary can never drift apart."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


class CurrencyStatus(str, enum.Enum):
    """Lifecycle of a currency or exchange-rate row.

    Distinct from soft-delete (``deleted_at``) and from the Zoho ``is_active``
    echo.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class CurrencyKind(str, enum.Enum):
    """Broad classification of the money unit (drives formatting/rounding)."""

    FIAT = "fiat"                     # ISO 4217 government-issued currency
    CRYPTO = "crypto"                 # non-ISO digital asset
    METALS = "metals"                 # XAU/XAG-style metal unit
    HISTORICAL = "historical"         # retired currency (e.g. pre-euro)


class CurrencyOwnerType(str, enum.Enum):
    """Polymorphic owner class for provenance/ownership.

    A row may be owned by a tenant (shared across its organizations), a single
    organization, the integration connection that produced it (Zoho), or the
    platform itself.
    """

    TENANT = "tenant"
    ORGANIZATION = "organization"
    CONNECTION = "connection"
    SYSTEM = "system"


class VerificationStatus(str, enum.Enum):
    """Verification workflow state of a currency / rate row."""

    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class SymbolPlacement(str, enum.Enum):
    """Where the currency symbol sits relative to the amount."""

    BEFORE = "before"
    AFTER = "after"


class RoundingMethod(str, enum.Enum):
    """How monetary amounts are rounded for this currency."""

    ROUND = "round"                   # half-up / half-even (banker's) per app policy
    CEIL = "ceil"
    FLOOR = "floor"


class RateUpdateFrequency(str, enum.Enum):
    """Cadence at which an automatic exchange-rate refresh runs."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MANUAL = "manual"


class ExchangeRateStatus(str, enum.Enum):
    """Lifecycle of one effective-dated exchange-rate row."""

    ACTIVE = "active"                 # currently usable for conversion
    SUPERSEDED = "superseded"         # a newer row for the same currency wins
    INVALID = "invalid"               # rejected / failed validation
    ARCHIVED = "archived"


__all__ = [
    "CurrencyKind",
    "CurrencyOwnerType",
    "CurrencyStatus",
    "ExchangeRateStatus",
    "RateUpdateFrequency",
    "RoundingMethod",
    "SymbolPlacement",
    "VerificationStatus",
    "values",
]