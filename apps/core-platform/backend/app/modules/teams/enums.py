"""Vocabularies for the teams module (docs/rbac-module.md).

Every value set is a closed vocabulary guarded by a CHECK built from the enum
(``values()``), so the constraint and the code cannot drift.
"""

from __future__ import annotations

import enum

#: Postgres schema holding the teams tables.
TEAMS_SCHEMA = "teams"


class DepartmentStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class CatalogueStatus(str, enum.Enum):
    """Job titles, team types and team roles."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"


class TeamStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"
    PENDING = "pending"


class MembershipStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ON_LEAVE = "on_leave"
    TRANSFERRED = "transferred"


class ApprovalStatus(str, enum.Enum):
    """A membership grants nothing until it is ``APPROVED``."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


__all__ = [
    "TEAMS_SCHEMA", "ApprovalStatus", "CatalogueStatus", "DepartmentStatus",
    "MembershipStatus", "TeamStatus", "values",
]
