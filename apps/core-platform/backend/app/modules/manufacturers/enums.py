"""Vocabularies for the ``core.manufacturers`` tables.

Closed sets are guarded by CHECK constraints built FROM these enums
(``values()``), so the constraint and the vocabulary cannot drift.
"""

from __future__ import annotations

import enum

from app.modules.entities.enums import CORE_SCHEMA, values

__all__ = [
    "CORE_SCHEMA",
    "ManufacturerIdentifierKind",
    "ManufacturerStatus",
    "values",
]


class ManufacturerStatus(enum.StrEnum):
    """Lifecycle of a manufacturer, distinct from soft delete."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"


class ManufacturerIdentifierKind(enum.StrEnum):
    """Kinds of registration/licence a manufacturer may carry.

    Only the India statutory formats are checked at the database (``gstin``,
    ``pan``, ``cin``, ``fssai``); the rest are stored verbatim. Verify the
    statutory patterns with counsel before relying on them.
    """

    GSTIN = "gstin"
    PAN = "pan"
    CIN = "cin"
    FSSAI = "fssai"
    DRUG_MANUFACTURING_LICENCE = "drug_manufacturing_licence"
    WHO_GMP = "who_gmp"
    ISO_CERTIFICATE = "iso_certificate"
    GS1_COMPANY_PREFIX = "gs1_company_prefix"
    DUNS = "duns"
    LEI = "lei"
    OTHER = "other"
