"""``core`` brand master and the brand ↔ manufacturer relation.

    Brand              the brand master (canonical, not a Zoho mirror).
    BrandManufacturer  which manufacturers make/market/import a brand, in what
                       role, with a validity window.

Scoping. Both tables are ``OrgEntityMixin``: ``tenant_id`` and
``organization_id`` are NOT NULL, so a row always belongs to one organization
of one tenant (the composite FK to ``org_management.organizations`` proves it).
``owner_type`` / ``owner_id`` (``PolymorphicOwnerMixin``) are the Lens-2
provenance pair — who the master is held for; the service sets them to the
owning organization.

Integrity the database owns:
  * ``uq_brands_scope_id (tenant_id, organization_id, id)`` is the target of the
    composite FKs on ``brand_manufacturers``, so a link can never pair a brand
    and a manufacturer of two different organizations/tenants;
  * ``fk_brands_parent (tenant_id, organization_id, parent_id)`` keeps a
    sub-brand in the same organization as its parent (``parent_id IS NULL`` →
    MATCH SIMPLE skips the check → top-level brand);
  * ``core.guard_brand_parent()`` rejects a move that would create a cycle;
  * ``core.check_brand_manufacturer_overlap()`` rejects overlapping validity
    windows for the same (brand, manufacturer, kind) — a deferrable constraint
    trigger so a batch may delete-then-insert in one transaction.

Loaders: every relationship is ``lazy="raise"``. Lists use ``load_only`` (Slim);
the detail read uses ``selectinload`` (Fat). Tags/documents are the shared
``HasTagsMixin`` / ``HasDocumentsMixin`` relationships.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
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
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.brands.enums import (
    CORE_SCHEMA,
    BrandKind,
    BrandManufacturerKind,
    BrandStatus,
    values,
)
from app.modules.documents.mixins import HasDocumentsMixin
from app.modules.entities.enums import MasterOwnerType
from app.modules.tags.mixins import HasTagsMixin

_LIVE = text("deleted_at IS NULL")


class Brand(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, DeactivationMixin, PolymorphicOwnerMixin,
    HasTagsMixin, HasDocumentsMixin, SoftDeleteFilteredMixin, Base,
):
    """A brand master (own, third-party or private-label)."""

    __tablename__ = "brands"
    __table_args__ = (
        # Target of the composite (tenant_id, organization_id, brand_id) FK on
        # brand_manufacturers, and of the self-referential parent FK.
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_brands_scope_id"),
        CheckConstraint(f"status IN ({values(BrandStatus)})", name="ck_brands_status"),
        CheckConstraint(f"kind IS NULL OR kind IN ({values(BrandKind)})", name="ck_brands_kind"),
        CheckConstraint(f"owner_type IN ({values(MasterOwnerType)})", name="ck_brands_owner_type"),
        CheckConstraint("btrim(name) <> ''", name="ck_brands_name_not_blank"),
        CheckConstraint("code IS NULL OR btrim(code) <> ''", name="ck_brands_code_not_blank"),
        CheckConstraint("country_code IS NULL OR country_code ~ '^[A-Z]{2}$'", name="ck_brands_country_code"),
        CheckConstraint("website_url IS NULL OR website_url ~* '^https?://'", name="ck_brands_website_url"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_brands_no_self_parent"),
        # Safe hierarchy FK: a sub-brand shares its parent's organization.
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "parent_id"],
            [f"{CORE_SCHEMA}.brands.tenant_id", f"{CORE_SCHEMA}.brands.organization_id",
             f"{CORE_SCHEMA}.brands.id"],
            name="fk_brands_parent", ondelete="RESTRICT",
        ),
        # One live brand per (tenant, organization, normalized name / code / slug).
        Index("uq_brands_scope_name", "tenant_id", "organization_id", "name_normalized",
              unique=True, postgresql_where=_LIVE),
        Index("uq_brands_scope_code", "tenant_id", "organization_id", "code",
              unique=True, postgresql_where=text("code IS NOT NULL AND deleted_at IS NULL")),
        Index("uq_brands_scope_slug", "tenant_id", "organization_id", "slug",
              unique=True, postgresql_where=text("slug IS NOT NULL AND deleted_at IS NULL")),
        Index("ix_brands_owner_scope_name", "tenant_id", "organization_id", "name", postgresql_where=_LIVE),
        Index("ix_brands_name_trgm", "name_normalized", postgresql_using="gin",
              postgresql_ops={"name_normalized": "gin_trgm_ops"}, postgresql_where=_LIVE),
        Index("ix_brands_parent_id", "parent_id", postgresql_where=text("parent_id IS NOT NULL")),
        {"schema": CORE_SCHEMA,
         "comment": "Brand master, organization-scoped within a tenant (NULL owner = global in the reference design)."},
    )

    # ---- identity ------------------------------------------------------------
    name: Mapped[str] = mapped_column(Text, nullable=False, comment="Display/trading name")
    slug: Mapped[str | None] = mapped_column(
        Text, comment="URL-friendly identifier, unique per (tenant, organization) among live rows",
    )
    code: Mapped[str | None] = mapped_column(Text, comment="Short internal code; NULL = unclassified")
    kind: Mapped[str | None] = mapped_column(
        Text, comment="own / third_party / private_label; NULL = unclassified",
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Parent brand (sub-brand); NULL = top-level",
    )
    name_normalized: Mapped[str | None] = mapped_column(
        Text, Computed(r"lower(btrim(regexp_replace(name, '\s+', ' ', 'g')))", persisted=True),
        comment="STORED generated lower-cased, whitespace-collapsed name; uniqueness + trigram search",
    )

    # ---- profile -------------------------------------------------------------
    country_code: Mapped[str | None] = mapped_column(Text, comment="ISO 3166-1 alpha-2 country code")
    description: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    logo_storage_key: Mapped[str | None] = mapped_column(
        Text, comment="Storage key, never a signed URL (AP18)",
    )

    # status / is_verified / row_version / audit / app meta come from OrgEntityMixin;
    # deactivation_* from DeactivationMixin; owner_* from PolymorphicOwnerMixin.

    parent: Mapped[Brand | None] = relationship(
        "Brand", remote_side="Brand.id", viewonly=True, lazy="raise",
    )
    manufacturer_links: Mapped[list[BrandManufacturer]] = relationship(
        "BrandManufacturer",
        primaryjoin="Brand.id == foreign(BrandManufacturer.brand_id)",
        order_by="BrandManufacturer.is_default.desc().nulls_last(), BrandManufacturer.id",
        viewonly=True, lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Brand id={self.id} name={self.name!r} org={self.organization_id}>"


class BrandManufacturer(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base,
):
    """A brand ↔ manufacturer link with role, default flag and validity window."""

    __tablename__ = "brand_manufacturers"
    __table_args__ = (
        # Composite FKs: the pair can never span two organizations or tenants.
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "brand_id"],
            [f"{CORE_SCHEMA}.brands.tenant_id", f"{CORE_SCHEMA}.brands.organization_id",
             f"{CORE_SCHEMA}.brands.id"],
            name="fk_brand_manufacturers_brand", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "manufacturer_id"],
            [f"{CORE_SCHEMA}.manufacturers.tenant_id", f"{CORE_SCHEMA}.manufacturers.organization_id",
             f"{CORE_SCHEMA}.manufacturers.id"],
            name="fk_brand_manufacturers_manufacturer", ondelete="CASCADE",
        ),
        CheckConstraint(
            f"kind IS NULL OR kind IN ({values(BrandManufacturerKind)})",
            name="ck_brand_manufacturers_kind",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="ck_brand_manufacturers_valid_window",
        ),
        # One current link per (brand, manufacturer, kind); NULLS NOT DISTINCT so
        # an unclassified (NULL) kind is treated as one value, not many.
        Index("uq_brand_manufacturers_current",
              "tenant_id", "organization_id", "brand_id", "manufacturer_id", "kind",
              unique=True, postgresql_where=text("deleted_at IS NULL AND valid_to IS NULL"),
              postgresql_nulls_not_distinct=True),
        # At most one default per (brand, kind).
        Index("ux_brand_manufacturers_default",
              "tenant_id", "organization_id", "brand_id", "kind",
              unique=True, postgresql_where=text("is_default IS TRUE AND deleted_at IS NULL AND valid_to IS NULL"),
              postgresql_nulls_not_distinct=True),
        Index("ix_brand_manufacturers_brand_id", "brand_id", postgresql_where=_LIVE),
        Index("ix_brand_manufacturers_manufacturer_id", "manufacturer_id", postgresql_where=_LIVE),
        {"schema": CORE_SCHEMA,
         "comment": "Brand x manufacturer relation with role, default and validity window."},
    )

    brand_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Owning brand")
    manufacturer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Linked manufacturer")
    kind: Mapped[str | None] = mapped_column(
        Text, comment="brand_owner / manufacturer / contract_manufacturer / marketer / importer; NULL = unclassified",
    )
    is_default: Mapped[bool | None] = mapped_column(
        Boolean, default=False, server_default=text("false"), comment="Default manufacturer for this brand and kind",
    )
    valid_from: Mapped[dt.date | None] = mapped_column(
        Date, default=dt.date.today, server_default=text("CURRENT_DATE"),
        comment="Business date the relation starts; NULL = unbounded past",
    )
    valid_to: Mapped[dt.date | None] = mapped_column(
        Date, comment="Half-open [valid_from, valid_to); NULL = still current",
    )

    brand: Mapped[Brand] = relationship(
        "Brand", primaryjoin="foreign(BrandManufacturer.brand_id) == Brand.id",
        viewonly=True, lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<BrandManufacturer id={self.id} brand={self.brand_id} manufacturer={self.manufacturer_id}>"


__all__ = ["Brand", "BrandManufacturer"]
