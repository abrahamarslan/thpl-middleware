"""Vocabularies for the hub module.

Every value is stored in a ``text``/``varchar`` column guarded by a CHECK
constraint, so the constraint and the vocabulary can never drift apart.
"""

from __future__ import annotations

import enum


class HubType(str, enum.Enum):
    """What kind of operating point a hub is."""

    WAREHOUSE = "warehouse"      # stock-holding / dispatch origin
    BRANCH = "branch"            # regional office + small stock
    DARK_STORE = "dark_store"    # urban fulfilment micro-hub
    TRANSIT = "transit"          # cross-dock / line-haul transfer point
    SPOKE = "spoke"              # last-mile delivery spoke fed by a parent hub


class HubStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"      # temporarily not receiving/sending work
    ARCHIVED = "archived"        # closed; retained for history


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


__all__ = ["HubStatus", "HubType", "values"]
