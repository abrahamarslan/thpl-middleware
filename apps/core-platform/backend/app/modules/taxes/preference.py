"""Organization default-tax preferences.

``OrgDefaultTaxPreference`` is the normalized replacement for re-storing a full
tax row per entry in Zoho's ``default_taxes`` response. It says which
``tax.tax_components`` row pre-selects for a new document in a given context
(inter-state vs intra-state), for an organization.

At most one default per (tenant, organization, tax_specification) is enforced by
a partial unique index. It is ``NULLS NOT DISTINCT`` so a tenant-wide default
(``organization_id IS NULL``) is still unique — a plain unique index would let
two tenant-wide defaults for the same context coexist, because NULLs compare
distinct.

Loader strategy: ``default_tax`` is many-to-one — ``lazy="raise"``.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    BigIntPKWithUUIDv7Mixin,
    TenantScopedMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.taxes.component import TaxComponent
from app.modules.taxes.enums import TAX_SCHEMA, TaxSpecification, values

_LIVE = text("deleted_at IS NULL")


class OrgDefaultTaxPreference(
    BigIntPKWithUUIDv7Mixin, TenantScopedMixin, AuditMixin, AppMetaMixin, TimestampMixin,
    SoftDeleteFilteredMixin, Base,
):
    """Which tax component pre-selects for a new document in a given context."""

    __tablename__ = "org_default_tax_preferences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "default_tax_id"],
            [f"{TAX_SCHEMA}.tax_components.tenant_id", f"{TAX_SCHEMA}.tax_components.id"],
            name="fk_org_default_tax_preferences_default_tax", ondelete="RESTRICT",
        ),
        CheckConstraint(f"tax_specification IN ({values(TaxSpecification)})",
                        name="chk_org_default_tax_preferences_spec"),
        Index("uq_org_default_tax_preferences_org_spec", "tenant_id", "organization_id", "tax_specification",
              unique=True, postgresql_where=_LIVE, postgresql_nulls_not_distinct=True),
        Index("ix_org_default_tax_preferences_default_tax_id", "default_tax_id", postgresql_where=_LIVE),
        {"schema": TAX_SCHEMA, "comment": "Default tax component per organization and inter/intra context."},
    )

    tax_specification: Mapped[str] = mapped_column(
        Text, nullable=False, comment="'inter' (inter-state) or 'intra' (intra-state)",
    )
    default_tax_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The tax component that is the default for this context",
    )

    default_tax: Mapped[TaxComponent] = relationship(
        "TaxComponent",
        primaryjoin="foreign(OrgDefaultTaxPreference.default_tax_id) == TaxComponent.id",
        viewonly=True, lazy="raise",
    )

    def __repr__(self) -> str:
        return (f"<OrgDefaultTaxPreference id={self.id} org={self.organization_id} "
                f"spec={self.tax_specification!r} default_tax={self.default_tax_id}>")


__all__ = ["OrgDefaultTaxPreference"]
