"""``core`` manufacturer master and its registrations/licences.

    Manufacturer            the manufacturer master (also marketers/importers/
                            principals — see ``BrandManufacturer.kind``).
    ManufacturerIdentifier  GSTIN, PAN, CIN, FSSAI, drug licence, … of a
                            manufacturer.

Scoping mirrors ``core.brands``: ``OrgEntityMixin`` (tenant + organization NOT
NULL), ``owner_type`` / ``owner_id`` provenance pair. ``fk_manufacturer_identifiers``
is a composite FK to ``(tenant_id, organization_id, id)``, so an identifier can
never belong to another organization's manufacturer.

``value`` is stored exactly as received; ``value_normalized`` is a STORED
generated column (upper-cased, whitespace removed) that backs the uniqueness
index and the statutory-format CHECKs. ``verified_*`` comes from
``VerificationMixin``; ``is_verified`` from ``StatusMixin``.

Loaders: every relationship is ``lazy="raise"``; lists use ``load_only``.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    Date,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    BigIntPKWithUUIDv7Mixin,
    DeactivationMixin,
    OrgEntityMixin,
    PolymorphicOwnerMixin,
    VerificationMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.documents.mixins import HasDocumentsMixin
from app.modules.entities.enums import MasterOwnerType
from app.modules.manufacturers.enums import (
    CORE_SCHEMA,
    ManufacturerIdentifierKind,
    ManufacturerStatus,
    values,
)
from app.modules.tags.mixins import HasTagsMixin

_LIVE = text("deleted_at IS NULL")

#: Statutory formats (India). Verify with counsel before relying on them.
_IDENTIFIER_FORMAT_SQL = """
    CASE kind
        WHEN 'gstin' THEN value_normalized ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'
        WHEN 'pan'   THEN value_normalized ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'
        WHEN 'cin'   THEN value_normalized ~ '^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$'
        WHEN 'fssai' THEN value_normalized ~ '^[0-9]{14}$'
        ELSE true
    END
"""


class Manufacturer(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
    PolymorphicOwnerMixin, HasTagsMixin, HasDocumentsMixin, SoftDeleteFilteredMixin, Base,
):
    """A manufacturer master (also marketer / importer / principal)."""

    __tablename__ = "manufacturers"
    __table_args__ = (
        # Target of the composite (tenant_id, organization_id, manufacturer_id) FK.
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_manufacturers_scope_id"),
        CheckConstraint(f"status IN ({values(ManufacturerStatus)})", name="ck_manufacturers_status"),
        CheckConstraint(f"owner_type IN ({values(MasterOwnerType)})", name="ck_manufacturers_owner_type"),
        CheckConstraint("btrim(name) <> ''", name="ck_manufacturers_name_not_blank"),
        CheckConstraint("legal_name IS NULL OR btrim(legal_name) <> ''",
                        name="ck_manufacturers_legal_name_not_blank"),
        CheckConstraint("code IS NULL OR btrim(code) <> ''", name="ck_manufacturers_code_not_blank"),
        CheckConstraint("country_code IS NULL OR country_code ~ '^[A-Z]{2}$'",
                        name="ck_manufacturers_country_code"),
        CheckConstraint("website_url IS NULL OR website_url ~* '^https?://'",
                        name="ck_manufacturers_website_url"),
        CheckConstraint("verified_at IS NULL OR is_verified IS TRUE", name="ck_manufacturers_verified"),
        Index("uq_manufacturers_scope_name", "tenant_id", "organization_id", "name_normalized",
              unique=True, postgresql_where=_LIVE),
        Index("uq_manufacturers_scope_code", "tenant_id", "organization_id", "code",
              unique=True, postgresql_where=text("code IS NOT NULL AND deleted_at IS NULL")),
        Index("uq_manufacturers_scope_slug", "tenant_id", "organization_id", "slug",
              unique=True, postgresql_where=text("slug IS NOT NULL AND deleted_at IS NULL")),
        Index("ix_manufacturers_owner_scope_name", "tenant_id", "organization_id", "name",
              postgresql_where=_LIVE),
        Index("ix_manufacturers_name_trgm", "name_normalized", postgresql_using="gin",
              postgresql_ops={"name_normalized": "gin_trgm_ops"}, postgresql_where=_LIVE),
        {"schema": CORE_SCHEMA,
         "comment": "Manufacturer master (also marketers/importers/principals), organization-scoped within a tenant."},
    )

    # ---- identity ------------------------------------------------------------
    name: Mapped[str] = mapped_column(Text, nullable=False, comment="Display/trading name")
    slug: Mapped[str | None] = mapped_column(
        Text, comment="URL-friendly identifier, unique per (tenant, organization) among live rows",
    )
    legal_name: Mapped[str | None] = mapped_column(
        Text, comment="Registered legal name; name is the display/trading name",
    )
    code: Mapped[str | None] = mapped_column(Text, comment="Short internal code; NULL = unclassified")
    name_normalized: Mapped[str | None] = mapped_column(
        Text, Computed(r"lower(btrim(regexp_replace(name, '\s+', ' ', 'g')))", persisted=True),
        comment="STORED generated lower-cased, whitespace-collapsed name; uniqueness + trigram search",
    )

    # ---- profile -------------------------------------------------------------
    country_code: Mapped[str | None] = mapped_column(Text, comment="ISO 3166-1 alpha-2 country code")
    website_url: Mapped[str | None] = mapped_column(Text)

    # status / is_verified / row_version / audit / app meta from OrgEntityMixin;
    # verification_* from VerificationMixin; deactivation_* from DeactivationMixin;
    # owner_* from PolymorphicOwnerMixin.

    identifiers: Mapped[list[ManufacturerIdentifier]] = relationship(
        "ManufacturerIdentifier",
        primaryjoin="Manufacturer.id == foreign(ManufacturerIdentifier.manufacturer_id)",
        order_by="ManufacturerIdentifier.kind, ManufacturerIdentifier.id",
        viewonly=True, lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Manufacturer id={self.id} name={self.name!r} org={self.organization_id}>"


class ManufacturerIdentifier(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, VerificationMixin, SoftDeleteFilteredMixin, Base,
):
    """A registration or licence of a manufacturer."""

    __tablename__ = "manufacturer_identifiers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "manufacturer_id"],
            [f"{CORE_SCHEMA}.manufacturers.tenant_id", f"{CORE_SCHEMA}.manufacturers.organization_id",
             f"{CORE_SCHEMA}.manufacturers.id"],
            name="fk_manufacturer_identifiers_manufacturer", ondelete="CASCADE",
        ),
        CheckConstraint(
            f"kind IS NULL OR kind IN ({values(ManufacturerIdentifierKind)})",
            name="ck_manufacturer_identifiers_kind",
        ),
        CheckConstraint("btrim(value) <> ''", name="ck_manufacturer_identifiers_value_not_blank"),
        CheckConstraint(_IDENTIFIER_FORMAT_SQL.strip(), name="ck_manufacturer_identifiers_format"),
        CheckConstraint("expires_on IS NULL OR issued_on IS NULL OR expires_on > issued_on",
                        name="ck_manufacturer_identifiers_expiry"),
        CheckConstraint("verified_at IS NULL OR is_verified IS TRUE",
                        name="ck_manufacturer_identifiers_verified"),
        # One live identifier per (manufacturer, kind, normalized value); NULLS
        # NOT DISTINCT so an unclassified kind is one value, not many.
        Index("uq_manufacturer_identifiers_current",
              "tenant_id", "organization_id", "manufacturer_id", "kind", "value_normalized",
              unique=True, postgresql_where=_LIVE, postgresql_nulls_not_distinct=True),
        Index("ix_manufacturer_identifiers_manufacturer_id", "manufacturer_id", postgresql_where=_LIVE),
        Index("ix_manufacturer_identifiers_lookup",
              "tenant_id", "organization_id", "kind", "value_normalized", postgresql_where=_LIVE),
        {"schema": CORE_SCHEMA,
         "comment": "Registrations and licences of a manufacturer (GSTIN, PAN, CIN, FSSAI, drug licence...)."},
    )

    manufacturer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Owning manufacturer")
    kind: Mapped[str | None] = mapped_column(
        Text, comment="gstin / pan / cin / fssai / …; NULL = unclassified",
    )
    value: Mapped[str] = mapped_column(Text, nullable=False, comment="Exactly as received")
    value_normalized: Mapped[str | None] = mapped_column(
        Text, Computed(r"upper(regexp_replace(value, '\s+', '', 'g'))", persisted=True),
        comment="STORED generated upper-cased, whitespace-free value; lookup + format checks",
    )
    issuing_authority: Mapped[str | None] = mapped_column(Text)
    issued_on: Mapped[dt.date | None] = mapped_column(Date)
    expires_on: Mapped[dt.date | None] = mapped_column(Date)

    manufacturer: Mapped[Manufacturer] = relationship(
        "Manufacturer", primaryjoin="foreign(ManufacturerIdentifier.manufacturer_id) == Manufacturer.id",
        viewonly=True, lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<ManufacturerIdentifier id={self.id} manufacturer={self.manufacturer_id} kind={self.kind!r}>"


__all__ = ["Manufacturer", "ManufacturerIdentifier"]
