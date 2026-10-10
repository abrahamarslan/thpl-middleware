"""Configurable resolution policies — ``core.resolution_policies``.

The code registers a DEFAULT policy for every (facet, subject kind) (``registry.py``). A
tenant may override it tenant-wide (``organization_id`` NULL) and an organization may
override it again; the effective policy is the narrowest that exists:

    organization override  →  tenant override  →  code default

An override replaces the ordered steps (role, filter, on_unusable) and the
organization-default switch. It cannot invent roles, filters or expanders — it is
validated against the code default's vocabulary on write (``service.put_override``), so a
stored policy is always one the engine can run.

Scoping: ``TenantEntityMixin`` (tenant NOT NULL, organization optional) — a policy may
legitimately be tenant-wide. Soft-deletable; one live row per (tenant, organization,
facet, subject), ``NULLS NOT DISTINCT`` so the tenant-wide row is unique too.
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, TenantEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.entities.enums import CORE_SCHEMA


class ResolutionPolicyOverride(BigIntPKWithUUIDv7Mixin, TenantEntityMixin, SoftDeleteFilteredMixin, Base):
    """A tenant's or organization's override of a code-default resolution policy."""

    __tablename__ = "resolution_policies"
    __table_args__ = (
        Index("uq_resolution_policies_scope", "tenant_id", "organization_id", "facet", "subject", unique=True,
              postgresql_nulls_not_distinct=True, postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint("jsonb_typeof(steps) = 'array'", name="ck_resolution_policies_steps_array"),
        CheckConstraint("btrim(facet) <> '' AND btrim(subject) <> ''", name="ck_resolution_policies_keys"),
        {"schema": CORE_SCHEMA,
         "comment": "Tenant / organization overrides of the code-default resolution policies."},
    )

    facet: Mapped[str] = mapped_column(String(32), nullable=False, comment="Registered facet code (tax, account)")
    subject: Mapped[str] = mapped_column(String(64), nullable=False, comment="Subject kind (sales_line, …)")
    steps: Mapped[list] = mapped_column(
        JSONB, nullable=False, comment="Ordered [{role, filter, on_unusable}] — validated against the registry",
    )
    use_organization_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="false = the organization default does not close the chain",
    )
    notes: Mapped[str | None] = mapped_column(Text, comment="Why this override exists (accountant sign-off, …)")

    def __repr__(self) -> str:
        return f"<ResolutionPolicyOverride {self.facet}/{self.subject} org={self.organization_id}>"


__all__ = ["ResolutionPolicyOverride"]
