"""Organization ↔ tax assignment.

``OrganizationTaxComponent`` is the junction that says "this organization may use
this tax component". It is what makes ``tax.tax_components`` tenant-wide and
shareable: the component does not belong to one organization, access is granted
per organization here (M:N — one component to many organizations, one
organization to many components).

Strict scope (``MultiTenantMixin``): ``organization_id`` is NOT NULL and the
composite FK ``(tenant_id, organization_id)`` is checked on every row, so a
grant can never name another tenant's organization and a "tenant-wide grant"
cannot exist by accident. If a component must belong to at most one
organization, add a partial unique index on ``tax_component_id``.

``is_active`` is the per-organization enablement switch, distinct from
``tax_components.is_inactive`` (the source's own flag) and from soft delete.

Loader strategy: ``tax_component`` is many-to-one — ``lazy="raise"`` on the
mapper, ``joinedload`` where a list needs it.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKeyConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    BigIntPKWithUUIDv7Mixin,
    MultiTenantMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.taxes.component import TaxComponent
from app.modules.taxes.enums import TAX_SCHEMA

_LIVE = text("deleted_at IS NULL")


class OrganizationTaxComponent(
    BigIntPKWithUUIDv7Mixin, MultiTenantMixin, AuditMixin, AppMetaMixin, TimestampMixin,
    SoftDeleteFilteredMixin, Base,
):
    """Grants an organization the use of one tax component."""

    __tablename__ = "organization_tax_components"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "tax_component_id"],
            [f"{TAX_SCHEMA}.tax_components.tenant_id", f"{TAX_SCHEMA}.tax_components.id"],
            name="fk_organization_tax_components_component", ondelete="RESTRICT",
        ),
        Index("uq_organization_tax_components_org_tax", "tenant_id", "organization_id", "tax_component_id",
              unique=True, postgresql_where=_LIVE),
        Index("ix_organization_tax_components_tax_component_id", "tax_component_id", postgresql_where=_LIVE),
        {"schema": TAX_SCHEMA, "comment": "Which organizations may use which tax components (M:N)."},
    )

    tax_component_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The tax rate/group assigned to the organization",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="Per-organization enablement switch (distinct from the component's own flags)",
    )

    tax_component: Mapped[TaxComponent] = relationship(
        "TaxComponent",
        primaryjoin="foreign(OrganizationTaxComponent.tax_component_id) == TaxComponent.id",
        viewonly=True, lazy="raise",
    )

    def __repr__(self) -> str:
        return (f"<OrganizationTaxComponent id={self.id} org={self.organization_id} "
                f"component={self.tax_component_id} active={self.is_active}>")


__all__ = ["OrganizationTaxComponent"]
