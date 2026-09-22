"""Vocabularies shared by the ``core`` master-data schema.

Every closed set is stored in a ``text`` column guarded by a CHECK built FROM
the enum (``values()``), so the constraint and the vocabulary cannot drift.
This module is the common root for the ``brands`` and ``manufacturers``
packages: both import ``CORE_SCHEMA`` and ``MasterOwnerType`` from here.
"""

from __future__ import annotations

import enum

#: Postgres schema holding the shared master-data tables.
CORE_SCHEMA = "core"


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


class MasterOwnerType(enum.StrEnum):
    """Polymorphic owner class for a master-data row's provenance pair.

    Mirrors ``CurrencyOwnerType``: a brand/manufacturer is held for a tenant
    (shared across its organizations), a single organization, the integration
    connection that produced it, or the platform itself.
    """

    TENANT = "tenant"
    ORGANIZATION = "organization"
    CONNECTION = "connection"
    SYSTEM = "system"


class EntityAliasKind(enum.StrEnum):
    """Why an alias exists — drives display and de-duplication heuristics."""

    ABBREVIATION = "abbreviation"
    FORMER_NAME = "former_name"
    MISSPELLING = "misspelling"
    TRANSLATION = "translation"
    TRADE_NAME = "trade_name"


__all__ = [
    "CORE_SCHEMA",
    "EntityAliasKind",
    "MasterOwnerType",
    "values",
]
