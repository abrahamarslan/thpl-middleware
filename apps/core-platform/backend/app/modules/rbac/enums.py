"""Vocabularies for the RBAC module (docs/rbac-module.md).

Every closed set is stored in a text column guarded by a CHECK built FROM the
enum (``values()``), so the constraint and the vocabulary cannot drift.
"""

from __future__ import annotations

import enum

#: Postgres schema holding the RBAC tables (``roles`` itself stays in ``public``).
RBAC_SCHEMA = "rbac"


class GrantMode(str, enum.Enum):
    """How a role's permission set is determined.

    ``ALL`` and ``ALL_BUT_OWNER_ONLY`` are COMPUTED at evaluation time from the
    code-owned catalogue, so a new permission reaches ``owner``/``admin`` with no
    per-organization row to seed or re-sync. ``EXPLICIT`` roles (every custom role
    and the non-superuser templates) own exactly their ``role_permissions`` rows.
    """

    EXPLICIT = "explicit"
    ALL = "all"
    ALL_BUT_OWNER_ONLY = "all_but_owner_only"


class ScopeType(str, enum.Enum):
    """Where a contextual grant (``rbac.user_roles``) applies."""

    TENANT = "tenant"
    ORGANIZATION = "organization"
    DEPARTMENT = "department"
    TEAM = "team"


class AssignmentStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class RoleStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


__all__ = ["RBAC_SCHEMA", "AssignmentStatus", "GrantMode", "RoleStatus", "ScopeType", "values"]
