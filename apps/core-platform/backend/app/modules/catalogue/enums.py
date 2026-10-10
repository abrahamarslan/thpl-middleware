"""Vocabularies of the ``catalogue`` schema.

Closed sets WE own are guarded by CHECK constraints built from these enums (``values()``), so the
constraint and the vocabulary cannot drift. Vocabularies Zoho owns (e.g. an item's ``product_type``)
are deliberately NOT here — they stay open text, validated only on local writes.

Design: docs/implementation-plans/catalogue/ (README §2, 01 §2, 02).
"""

from __future__ import annotations

import enum

from app.modules.entities.enums import values

CATALOGUE_SCHEMA = "catalogue"

__all__ = [
    "CATALOGUE_SCHEMA",
    "AttributeInputType",
    "ComponentRole",
    "Composition",
    "DrugSchedule",
    "IdentifierKind",
    "IdentifierSource",
    "ItemStatus",
    "StorageCondition",
    "TrackMode",
    "ValuationMethod",
    "ChannelKind",
    "MasterStatus",
    "QuantityKind",
    "UnitClass",
    "values",
]


class MasterStatus(enum.StrEnum):
    """Lifecycle of a catalogue master row (units, packaging types, channels, groups, attributes)."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class UnitClass(enum.StrEnum):
    """What a unit measures. Count units have no physical size (a "box" is per item — item_units);
    physical classes convert through ``si_factor`` to the class base."""

    COUNT = "count"
    MASS = "mass"          # base: gram
    VOLUME = "volume"      # base: millilitre
    LENGTH = "length"      # base: millimetre
    AREA = "area"          # base: square millimetre
    TIME = "time"          # base: second
    OTHER = "other"

    @property
    def is_physical(self) -> bool:
        return self not in (UnitClass.COUNT, UnitClass.OTHER)


class QuantityKind(enum.StrEnum):
    """What a GST UQC counts (``catalogue.uqc_codes.quantity_kind``)."""

    COUNT = "count"
    MASS = "mass"
    VOLUME = "volume"
    LENGTH = "length"
    AREA = "area"
    OTHER = "other"


class ChannelKind(enum.StrEnum):
    """Route to market of a sales channel."""

    GENERAL_TRADE = "general_trade"
    MODERN_TRADE = "modern_trade"
    DISTRIBUTOR = "distributor"
    ECOMMERCE = "ecommerce"
    INSTITUTIONAL = "institutional"
    DIRECT = "direct"
    OTHER = "other"


class AttributeInputType(enum.StrEnum):
    """How a variant axis is chosen."""

    SELECT = "select"
    SWATCH = "swatch"
    NUMBER = "number"
    TEXT = "text"


# ── items (phase 2) ──────────────────────────────────────────────────────────

class ItemStatus(enum.StrEnum):
    """``draft`` is local-only (not offered); ``discontinued`` = sell-through, no new purchases."""

    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"


class Composition(enum.StrEnum):
    """none | assembly (own stock, built from components — Zoho combo_type=assembly) | kit (no own stock)."""

    NONE = "none"
    ASSEMBLY = "assembly"
    KIT = "kit"


class TrackMode(enum.StrEnum):
    """Lot/serial tracking. ``serial`` / ``batch_serial`` are reserved — no serial tables yet."""

    NONE = "none"
    BATCH = "batch"
    SERIAL = "serial"
    BATCH_SERIAL = "batch_serial"


class ValuationMethod(enum.StrEnum):
    FIFO = "fifo"
    WEIGHTED_AVERAGE = "weighted_average"
    MOVING_AVERAGE = "moving_average"


class StorageCondition(enum.StrEnum):
    AMBIENT = "ambient"
    COOL = "cool"
    COLD_CHAIN = "cold_chain"
    FROZEN = "frozen"


class DrugSchedule(enum.StrEnum):
    """Drugs and Cosmetics Rules schedules (verify with the compliance owner)."""

    G = "G"
    H = "H"
    H1 = "H1"
    X = "X"
    C = "C"
    C1 = "C1"
    OTC = "OTC"


class ComponentRole(enum.StrEnum):
    ASSEMBLY_COMPONENT = "assembly_component"
    KIT_MEMBER = "kit_member"
    BOX_CONTENT = "box_content"
    PACKAGING_MATERIAL = "packaging_material"


class IdentifierKind(enum.StrEnum):
    """Scannable kinds resolve to exactly one (item, level) per organization; mpn/part_number need not."""

    GTIN = "gtin"
    EAN = "ean"
    UPC = "upc"
    ISBN = "isbn"
    BARCODE = "barcode"
    MPN = "mpn"
    PART_NUMBER = "part_number"
    OTHER = "other"

    @property
    def is_scannable(self) -> bool:
        return self in (IdentifierKind.GTIN, IdentifierKind.EAN, IdentifierKind.UPC, IdentifierKind.ISBN,
                        IdentifierKind.BARCODE)


class IdentifierSource(enum.StrEnum):
    LOCAL = "local"
    ZOHO = "zoho"
    IMPORT = "import"
