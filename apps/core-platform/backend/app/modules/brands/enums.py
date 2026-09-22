"""Vocabularies for the ``core.brands`` tables.

Closed sets are guarded by CHECK constraints built FROM these enums
(``values()``), so the constraint and the vocabulary cannot drift.
"""

from __future__ import annotations

import enum

from app.modules.entities.enums import CORE_SCHEMA, values

__all__ = [
    "CORE_SCHEMA",
    "BrandKind",
    "BrandManufacturerKind",
    "BrandStatus",
    "values",
]


class BrandStatus(enum.StrEnum):
    """Lifecycle of a brand, distinct from soft delete."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"


class BrandKind(enum.StrEnum):
    """Ownership/positioning of the brand."""

    OWN = "own"                        # our own label
    THIRD_PARTY = "third_party"        # a supplier's brand we distribute
    PRIVATE_LABEL = "private_label"    # contract-manufactured for us


class BrandManufacturerKind(enum.StrEnum):
    """The role a manufacturer plays for a brand."""

    BRAND_OWNER = "brand_owner"
    MANUFACTURER = "manufacturer"
    CONTRACT_MANUFACTURER = "contract_manufacturer"
    MARKETER = "marketer"
    IMPORTER = "importer"
