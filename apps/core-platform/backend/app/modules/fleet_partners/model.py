"""``fleet_partners`` — the legal entity that supplies vehicles/personnel.

    fleet_partners   ENTITY   a vendor/business (or individual) contracted to
                              supply vehicles and/or drivers

Scoping: ``OrgEntityMixin`` (organization NOT NULL) + soft delete + verification.
Statutory identifiers follow the platform's encrypt/mask pattern (the full PAN
is app-layer ciphertext; only the masked form is queryable). The registered
address is a ``geo.places`` row; the proof documents (GST/CIN) attach through
``HasDocumentsMixin``.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    DeactivationMixin,
    IntPKMixin,
    OrgEntityMixin,
    VerificationMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.documents.mixins import HasDocumentsMixin
from app.modules.fleet_partners.enums import FleetPartnerEntityType, FleetPartnerStatus, values


class FleetPartner(
    IntPKMixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
    SoftDeleteFilteredMixin, HasDocumentsMixin, Base,
):
    """A vendor/business entity supplying vehicles and/or personnel."""

    __tablename__ = "fleet_partners"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_fleet_partners_tenant_org_id"),
        CheckConstraint(f"entity_type IN ({values(FleetPartnerEntityType)})",
                        name="chk_fleet_partner_entity_type"),
        CheckConstraint(f"status IN ({values(FleetPartnerStatus)})", name="chk_fleet_partner_status"),
        CheckConstraint("contract_end_date IS NULL OR contract_start_date IS NULL "
                        "OR contract_end_date >= contract_start_date", name="chk_fleet_partner_contract"),
        CheckConstraint("commission_rate IS NULL OR (commission_rate >= 0 AND commission_rate <= 100)",
                        name="chk_fleet_partner_commission"),
        CheckConstraint("payment_terms_days IS NULL OR payment_terms_days >= 0",
                        name="chk_fleet_partner_payment_terms"),
        Index("uq_fleet_partners_tenant_org_code_live", "tenant_id", "organization_id", "code",
              unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("uq_fleet_partners_pan_live", "tenant_id", "pan_masked", unique=True,
              postgresql_where=text("deleted_at IS NULL AND pan_masked IS NOT NULL")),
        Index("uq_fleet_partners_zoho_id_live", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("ix_fleet_partners_owner_user", "tenant_id", "owner_user_id",
              postgresql_where=text("owner_user_id IS NOT NULL")),
        Index("ix_fleet_partners_place", "registered_address_place_id",
              postgresql_where=text("registered_address_place_id IS NOT NULL")),
        {"comment": "Vendor/business entities supplying vehicles and/or personnel."},
    )

    # ---- Identity ----------------------------------------------------------
    code: Mapped[str] = mapped_column(String(50), nullable=False, comment="Stable short code, e.g. FP-AHM-07")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Registered / trading name")
    entity_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=FleetPartnerEntityType.INDIVIDUAL.value,
        server_default=text("'individual'"),
        comment="individual / proprietorship / partnership / llp / private_limited",
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"),
        comment="For individual/proprietorship partners, the person behind the entity",
    )

    # ---- Statutory identity (encrypt/mask pattern) -------------------------
    pan_masked: Mapped[str | None] = mapped_column(String(12), comment="Masked PAN, e.g. ABCDE****F")
    pan_encrypted: Mapped[str | None] = mapped_column(Text, comment="App-layer-encrypted full PAN")
    gstin: Mapped[str | None] = mapped_column(String(20))
    cin: Mapped[str | None] = mapped_column(String(25), comment="Corporate Identification Number")
    tan: Mapped[str | None] = mapped_column(String(20))

    # ---- Contact -----------------------------------------------------------
    registered_address_place_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo.places.id", ondelete="SET NULL"),
        comment="Registered address (geo.places)",
    )
    contact_person_name: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    contact_email: Mapped[str | None] = mapped_column(String(255))

    # ---- Commercial --------------------------------------------------------
    contract_start_date: Mapped[dt.date | None] = mapped_column(Date)
    contract_end_date: Mapped[dt.date | None] = mapped_column(Date)
    commission_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), comment="Commission percentage (0-100)",
    )
    payment_terms_days: Mapped[int | None] = mapped_column(Integer)

    # ---- External systems --------------------------------------------------
    zoho_id: Mapped[str | None] = mapped_column(String(50), comment="Zoho vendor/contact id, if linked")

    # ---- Extras ------------------------------------------------------------
    notes: Mapped[str | None] = mapped_column(Text)
    custom_attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
    )

    def __repr__(self) -> str:
        return f"<FleetPartner id={self.id} code={self.code!r} type={self.entity_type!r}>"
