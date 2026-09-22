"""The tax component layer.

    TaxComponent   one row per tax rate OR tax group, discriminated by
                   ``tax_type``. Zoho shares one id namespace between its ``tax``
                   (CGST/SGST/IGST/…) and ``tax_group`` (composite, e.g. GST18)
                   entities, so they live in ONE table.
    TaxGroupMember which leaf components compose a ``tax_group`` row. Replaces
                   Zoho's nested ``tax_group.taxes[]`` array with a child table.

Scoping. ``tenant_id`` is NOT NULL; ``organization_id`` is the optional owning
organization (``TenantScopedMixin``: NULL = tenant-wide). Which organizations
may USE a component is not this column — it is ``tax.organization_tax_components``,
so one component is shareable across a tenant's organizations. Identity and
provenance are the crosswalk's (``sync.sync_records``); no table here carries a
source id.

Lifecycle lives on ``TaxComponent`` only: ``status`` and the reversible
deactivation triple (``DeactivationMixin``), both distinct from soft delete and
from ``is_inactive`` — Zoho's own flag, kept as an echo. The link table is a
plain audited, soft-deletable config row.

Opaque ids (``tax_authority_id``, ``tax_account_id``, ``tds_payable_account_id``,
``reference_id``) are raw source echoes (AP5): never cast, never joined.

Composite tenant FKs (``(tenant_id, x_id) → tax_components (tenant_id, id)``)
mean a membership can never pair components of two tenants, in the database and
not only in the service. ``members`` is view-only: memberships are written and
soft-deleted by the sync hook, and a cascade would turn "the group lost a member"
into a hard DELETE.

Loader strategy: every relationship is ``lazy="raise"`` — a group's members are
read with an explicit ``selectinload`` (crud.get_component), never lazily.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    BigIntPKWithUUIDv7Mixin,
    DeactivationMixin,
    HashGuardMixin,
    TenantEntityMixin,
    TenantScopedMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.taxes.enums import TAX_SCHEMA, TaxSpecification, TaxType, values

_LIVE = text("deleted_at IS NULL")


class TaxComponent(
    BigIntPKWithUUIDv7Mixin, TenantEntityMixin, DeactivationMixin, HashGuardMixin,
    SoftDeleteFilteredMixin, Base,
):
    """A tax rate or a tax group (discriminated by ``tax_type``)."""

    __tablename__ = "tax_components"
    __table_args__ = (
        # Target of the composite (tenant_id, x_id) FKs on every child table.
        UniqueConstraint("tenant_id", "id", name="uq_tax_components_tenant_id"),
        CheckConstraint(f"tax_type IN ({values(TaxType)})", name="chk_tax_components_tax_type"),
        CheckConstraint(
            "tax_type <> 'tax_group' OR tax_specific_type IS NULL",
            name="chk_tax_components_group_no_specific_type",
        ),
        CheckConstraint(
            f"tax_specification IS NULL OR tax_specification IN ({values(TaxSpecification)})",
            name="chk_tax_components_tax_specification",
        ),
        CheckConstraint("tax_percentage >= 0", name="chk_tax_components_tax_percentage"),
        Index("ix_tax_components_tenant_type", "tenant_id", "tax_type", postgresql_where=_LIVE),
        {"schema": TAX_SCHEMA,
         "comment": "Tax rates and tax groups (one id namespace, discriminated by tax_type)."},
    )

    # ---- the tax itself ------------------------------------------------------
    tax_name: Mapped[str] = mapped_column(Text, nullable=False, comment="Zoho tax or tax-group name")
    tax_display_name: Mapped[str | None] = mapped_column(
        Text, comment="Display name override carried from Zoho",
    )
    tax_percentage: Mapped[Decimal] = mapped_column(
        Numeric(7, 4), nullable=False, comment="Tax rate / group total percentage; Decimal, never float-parsed",
    )
    tax_type: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Discriminator: 'tax' (a single component like CGST9), 'compound_tax' or "
                "'tax_group' (a composite like GST18, see tax.tax_group_members)",
    )
    tax_specific_type: Mapped[str | None] = mapped_column(
        Text, comment="Edition-specific leg: IN cgst/sgst/igst/utgst/cess/nil, MX isr/iva/ieps, ZA soa_*/ciu_*; "
                      "NULL for groups and for the generic 'tax' sentinel",
    )
    tax_factor: Mapped[str | None] = mapped_column(Text, comment="(Mexico) rate | share")
    is_value_added: Mapped[bool | None] = mapped_column(Boolean, comment="VAT-style tax")

    # ---- authority -----------------------------------------------------------
    tax_authority_id: Mapped[str | None] = mapped_column(
        Text, comment="Opaque external reference to the source's tax authority record (AP5)",
    )
    tax_authority_name: Mapped[str | None] = mapped_column(Text, comment="Display echo of the tax authority name")

    # ---- geography -----------------------------------------------------------
    country: Mapped[str | None] = mapped_column(Text, comment="(UK, EU, Global) country the tax belongs to")
    country_code: Mapped[str | None] = mapped_column(
        Text, comment="(UK, EU, GCC, Global) two-letter country code",
    )

    # ---- accounts it posts to (display echoes and opaque ids, never local FKs)
    output_tax_account_name: Mapped[str | None] = mapped_column(
        Text, comment="Chart-of-accounts display echo (not a local FK)",
    )
    purchase_tax_account_name: Mapped[str | None] = mapped_column(
        Text, comment="Chart-of-accounts display echo for the purchase side (not a local FK)",
    )
    tax_account_id: Mapped[str | None] = mapped_column(
        Text, comment="Opaque external reference to the source's chart-of-accounts entry (AP5)",
    )
    purchase_tax_account_id: Mapped[str | None] = mapped_column(
        Text, comment="Opaque external reference to the purchase-side chart-of-accounts entry (AP5)",
    )
    tds_payable_account_id: Mapped[str | None] = mapped_column(
        Text, comment="Opaque external reference to the TDS-payable chart-of-accounts entry (AP5)",
    )
    purchase_tax_expense_account_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="(Australia, Canada) account purchase tax is computed in; documented as a long",
    )

    # ---- flags ---------------------------------------------------------------
    is_state_cess: Mapped[bool | None] = mapped_column(
        Boolean, comment="State cess component flag; NULL = unknown",
    )
    is_inactive: Mapped[bool | None] = mapped_column(
        Boolean,
        comment="The source's own deactivation flag; NULL = unknown/active. Distinct from deleted_at "
                "(no longer returned by the source) and deactivation_date (ours)",
    )
    is_default_tax: Mapped[bool | None] = mapped_column(Boolean, comment="NULL = false")
    is_editable: Mapped[bool | None] = mapped_column(
        Boolean, comment="Operator may override at invoice time; NULL = unknown",
    )
    is_non_advol_tax: Mapped[bool | None] = mapped_column(
        Boolean, comment="Non-ad-valorem flag; NULL = unknown/ad-valorem",
    )

    # ---- context & validity ---------------------------------------------------
    tax_specification: Mapped[str | None] = mapped_column(
        Text, comment="'inter' (inter-state) or 'intra' (intra-state)",
    )
    diff_rate_reason: Mapped[str | None] = mapped_column(
        Text, comment="Reason recorded when the rate differs from the standard",
    )
    start_date: Mapped[dt.date | None] = mapped_column(
        Date, comment="Business date validity start (AP7); empty string from source -> NULL at ingest",
    )
    end_date: Mapped[dt.date | None] = mapped_column(
        Date, comment="Business date validity end (AP7); same empty-string rule",
    )
    description: Mapped[str | None] = mapped_column(Text, comment="Free-text description")
    reference_id: Mapped[str | None] = mapped_column(Text, comment="Opaque external reference (AP5)")

    # ---- L1 mirrors / display cache -------------------------------------------
    tax_name_formatted: Mapped[str | None] = mapped_column(
        Text, comment="Display cache from the default_taxes endpoint",
    )
    source_default_tax_type_code: Mapped[int | None] = mapped_column(
        Integer,
        comment="Raw legacy numeric tax_type (0/2) from default_taxes; audit only, never drives the "
                "tax_type CHECK (AP8)",
    )
    source_new_tax_type: Mapped[str | None] = mapped_column(
        Text, comment="Raw string tax_type from default_taxes; preferred mapping source",
    )

    # status (default 'active'), is_verified, deactivation_*, content_hash, audit,
    # soft-delete, row_version and app meta come from the mixins.

    members: Mapped[list[TaxGroupMember]] = relationship(
        "TaxGroupMember",
        primaryjoin="TaxComponent.id == foreign(TaxGroupMember.tax_group_id)",
        order_by="TaxGroupMember.position, TaxGroupMember.id",
        viewonly=True,
        lazy="raise",
    )

    @property
    def is_group(self) -> bool:
        return self.tax_type == TaxType.TAX_GROUP.value

    def __repr__(self) -> str:
        return f"<TaxComponent id={self.id} name={self.tax_name!r} type={self.tax_type!r} pct={self.tax_percentage}>"


class TaxGroupMember(
    BigIntPKWithUUIDv7Mixin, TenantScopedMixin, AuditMixin, AppMetaMixin, TimestampMixin,
    SoftDeleteFilteredMixin, Base,
):
    """Which leaf components compose a ``tax_group`` row."""

    __tablename__ = "tax_group_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "tax_group_id"],
            [f"{TAX_SCHEMA}.tax_components.tenant_id", f"{TAX_SCHEMA}.tax_components.id"],
            name="fk_tax_group_members_group", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "member_tax_id"],
            [f"{TAX_SCHEMA}.tax_components.tenant_id", f"{TAX_SCHEMA}.tax_components.id"],
            name="fk_tax_group_members_member", ondelete="RESTRICT",
        ),
        CheckConstraint("tax_group_id <> member_tax_id", name="chk_tax_group_members_not_self"),
        Index("uq_tax_group_members_group_member", "tax_group_id", "member_tax_id",
              unique=True, postgresql_where=_LIVE),
        Index("ix_tax_group_members_member_tax_id", "member_tax_id", postgresql_where=_LIVE),
        {"schema": TAX_SCHEMA, "comment": "Leaf components composing a tax group."},
    )

    tax_group_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The composite group row (tax_components.tax_type = 'tax_group')",
    )
    member_tax_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The component that is a member (tax_components.tax_type = 'tax')",
    )
    position: Mapped[int | None] = mapped_column(
        SmallInteger, comment="Display order (index in the source's taxes[] array)",
    )

    tax_group: Mapped[TaxComponent] = relationship(
        "TaxComponent",
        primaryjoin="foreign(TaxGroupMember.tax_group_id) == TaxComponent.id",
        viewonly=True, lazy="raise",
    )
    member_tax: Mapped[TaxComponent] = relationship(
        "TaxComponent",
        primaryjoin="foreign(TaxGroupMember.member_tax_id) == TaxComponent.id",
        viewonly=True, lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<TaxGroupMember id={self.id} group={self.tax_group_id} member={self.member_tax_id} pos={self.position}>"


__all__ = ["TaxComponent", "TaxGroupMember"]
