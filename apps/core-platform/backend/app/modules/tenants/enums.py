"""Tenancy enums (shared by tenants and organizations)."""

from __future__ import annotations

import enum


class TenantStatus(str, enum.Enum):
    """Lifecycle of a tenant account (the root of the multi-tenant model)."""

    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"

    @property
    def can_sign_in(self) -> bool:
        return self in (TenantStatus.TRIAL, TenantStatus.ACTIVE)


class OrganizationStatus(str, enum.Enum):
    """Operational status of a node in the organization tree."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class OrganizationType(str, enum.Enum):
    """Structural classification of an organization node.

    ``SOLO`` is a standalone entity: it can never have a parent
    (``chk_org_solo_rootless``) nor children (service rule).
    """

    HOLDING = "holding"
    LEGAL_ENTITY = "legal_entity"
    BRANCH = "branch"
    SOLO = "solo"


#: Which parent types each node type may hang under (None = may be a root).
#: holding → holding / legal entities → branches → sub-branches; solo stands alone.
ALLOWED_PARENTS: dict[OrganizationType, frozenset[OrganizationType | None]] = {
    OrganizationType.HOLDING: frozenset({None, OrganizationType.HOLDING}),
    OrganizationType.LEGAL_ENTITY: frozenset({None, OrganizationType.HOLDING}),
    OrganizationType.BRANCH: frozenset({OrganizationType.HOLDING, OrganizationType.LEGAL_ENTITY,
                                        OrganizationType.BRANCH}),
    OrganizationType.SOLO: frozenset({None}),
}
