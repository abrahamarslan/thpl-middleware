"""Zoho taxes mirror (docs/zoho-docs-md/taxes.md — simple and compound taxes).

An O1 master: owned by Zoho, read-only here, referenced by items, contacts and
every line item (``tax_id``). Tax groups (/settings/taxgroups) are a separate
module, later. Composes Identity + Mirror mixins for the apply gate.
"""

from decimal import Decimal

from sqlalchemy import Boolean, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import DeactivationMixin, IntPKMixin, TenantEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.zoho.sync.mixins import ZohoIdentityMixin, ZohoMirrorMixin


class ZohoTax(IntPKMixin, TenantEntityMixin, DeactivationMixin, SoftDeleteFilteredMixin, ZohoMirrorMixin, ZohoIdentityMixin, Base):
    __tablename__ = "zoho_taxes"

    tax_name: Mapped[str | None] = mapped_column(String(255), index=True)
    tax_percentage: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    tax_type: Mapped[str | None] = mapped_column(String(32))            # tax | compound_tax
    tax_specific_type: Mapped[str | None] = mapped_column(String(32))   # India: igst | cgst | sgst | nil | cess
    tax_factor: Mapped[str | None] = mapped_column(String(16))
    tax_authority_id: Mapped[str | None] = mapped_column(String(50))
    tax_authority_name: Mapped[str | None] = mapped_column(String(255))
    is_value_added: Mapped[bool | None] = mapped_column(Boolean)
    is_default_tax: Mapped[bool | None] = mapped_column(Boolean)
    is_editable: Mapped[bool | None] = mapped_column(Boolean)
    country: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(8))
    tax_account_id: Mapped[str | None] = mapped_column(String(50))
    purchase_tax_account_id: Mapped[str | None] = mapped_column(String(50))
    output_tax_account_name: Mapped[str | None] = mapped_column(String(255))
    purchase_tax_account_name: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        Index(
            "uq_zoho_taxes_zoho_id_live", "tenant_id", "zoho_id", unique=True,
            postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL"),
        ),
    )
