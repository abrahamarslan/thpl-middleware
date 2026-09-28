"""Vocabularies for the ``core`` taxonomy/category tables.

Closed sets are guarded by CHECK constraints built FROM these enums (``values()``),
so the constraint and the vocabulary cannot drift. ``CORE_SCHEMA`` / ``values``
are re-exported from ``entities.enums`` — the shared root for the ``core``
schema, exactly as ``brands.enums`` does.
"""

from __future__ import annotations

import enum

from app.modules.entities.enums import CORE_SCHEMA, values

__all__ = [
    "CORE_SCHEMA",
    "CategoryRecordStatus",
    "CategoryStatus",
    "TaxonomyStatus",
    "values",
]


class TaxonomyStatus(enum.StrEnum):
    """Lifecycle of a taxonomy tree, distinct from soft delete."""

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class CategoryStatus(enum.StrEnum):
    """OUR lifecycle for a category (``StatusMixin.status`` on ``Category``)."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class CategoryRecordStatus(enum.IntEnum):
    """The source vocabulary kept typed (locked L1) as a smallint column.

    Deliberately an ``IntEnum``: ``values()`` quotes its members for a text
    CHECK, so the ``categories`` CHECK is written literally (``IN (-1, 0, 1)``).
    The inbound Zoho mapper may translate it to ``CategoryStatus`` at the
    boundary.
    """

    DELETED = -1
    NORMAL = 0
    ARCHIVED = 1
