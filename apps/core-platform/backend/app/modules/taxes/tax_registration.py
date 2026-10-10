"""``tax.tax_registrations`` — the statutory registrations of any party: GSTIN, PAN, Udyam, VAT …

One polymorphic table (owner = a ``core.entity_types`` code + id, the ``tax_assignments`` shape) so
organizations, parties and later anyone else keep their registrations in one place, searchable as one
("who holds GSTIN X?" across every customer and vendor).

    registration_type   gstin | pan | udyam | vat | tax_reg_no
    registration_number the number, normalized (upper-case, no spaces) — stored in clear (owner decision
                        2026-10-09: PAN is not encrypted)
    zoho_id             Zoho ``tax_info_id`` for GSTIN rows from ``tax_info_list`` (one per GSTIN)

Formats are validated by the service for LOCAL writes only; a Zoho row is trusted as sent (a malformed
one is reported, never refused — the accounts rule). The owner's scope (exists, same tenant AND
organization) is checked by a deferred constraint trigger calling ``core.assert_owner_scope`` (migration),
exactly as ``tax_assignments`` does.
"""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, OrgEntityMixin, VerificationMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.taxes.enums import TAX_SCHEMA, values


class RegistrationType(enum.StrEnum):
    GSTIN = "gstin"
    PAN = "pan"
    UDYAM = "udyam"            # MSME registration (Zoho udyam_reg_no + msme_type)
    VAT = "vat"
    TAX_REG_NO = "tax_reg_no"  # Zoho tax_reg_no (non-India editions)


def normalize_number(value: str | None) -> str | None:
    """Upper-case, no whitespace; '' → None. The one spelling every lookup and unique index sees."""
    if value is None:
        return None
    cleaned = "".join(str(value).split()).upper()
    return cleaned or None


class TaxRegistration(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, VerificationMixin, SoftDeleteFilteredMixin, Base):
    """One statutory registration of one owner."""

    __tablename__ = "tax_registrations"
    __table_args__ = (
        CheckConstraint(f"registration_type IN ({values(RegistrationType)})", name="ck_tax_registrations_type"),
        CheckConstraint("btrim(registration_number) <> ''", name="ck_tax_registrations_number_not_blank"),
        CheckConstraint("owner_id > 0", name="ck_tax_registrations_owner_id"),
        CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
                        name="ck_tax_registrations_validity"),
        CheckConstraint("status IN ('active','inactive')", name="ck_tax_registrations_status"),
        Index("uq_tax_registrations_number", "tenant_id", "owner_type_code", "owner_id", "registration_type",
              "registration_number", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("uq_tax_registrations_one_primary", "tenant_id", "owner_type_code", "owner_id", "registration_type",
              unique=True, postgresql_where=text("is_primary AND deleted_at IS NULL")),
        Index("uq_tax_registrations_zoho_id", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        # "Who holds GSTIN X / PAN Y?" — duplicate-party detection across customers and vendors.
        Index("ix_tax_registrations_lookup", "tenant_id", "registration_type", "registration_number",
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_tax_registrations_owner", "tenant_id", "owner_type_code", "owner_id",
              postgresql_where=text("deleted_at IS NULL")),
        {"schema": TAX_SCHEMA, "comment": "Statutory registrations (GSTIN, PAN, Udyam, VAT …) of any owner."},
    )

    owner_type_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("core.entity_types.code", ondelete="RESTRICT", name="fk_tax_registrations_owner_type"),
        nullable=False, comment="core.entity_types.code of the owner (party, organization …)",
    )
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    registration_type: Mapped[str] = mapped_column(String(20), nullable=False)
    registration_number: Mapped[str] = mapped_column(Text, nullable=False, comment="Normalized: upper-case, no spaces")
    legal_name: Mapped[str | None] = mapped_column(Text)
    trade_name: Mapped[str | None] = mapped_column(Text)
    place_of_supply: Mapped[str | None] = mapped_column(String(4), comment="GST state code of this registration")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    valid_from: Mapped[dt.date | None] = mapped_column(Date)
    valid_to: Mapped[dt.date | None] = mapped_column(Date)
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment="Type-specific facts, e.g. udyam: {msme_type, is_valid, validated_at}",
    )
    zoho_id: Mapped[str | None] = mapped_column(String(50), comment="Zoho tax_info_id (GSTIN rows)")
    source_system: Mapped[str | None] = mapped_column(String(16), comment="'zoho' | NULL (local)")

    def __repr__(self) -> str:
        return f"<TaxRegistration {self.registration_type} {self.registration_number} {self.owner_type_code}:{self.owner_id}>"


__all__ = ["RegistrationType", "TaxRegistration", "normalize_number"]
