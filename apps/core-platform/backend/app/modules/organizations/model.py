"""``org_management.organizations`` — the legal / hierarchy tree
(holding → legal entities → branches), scoped strictly by tenant.

Tenant isolation is enforced by the database, not by convention:

  * ``uq_organizations_tenant_id UNIQUE (tenant_id, id)`` is the target of the
    COMPOSITE foreign key ``(tenant_id, organization_id)`` that every
    tenant-scoped table declares (TenantScopedMixin) — the DB guarantees a
    row's organization belongs to the row's tenant.
  * ``fk_organizations_parent (tenant_id, parent_id)`` applies the same trick to
    the tree: a parent and child can never belong to different tenants
    (``parent_id IS NULL`` → MATCH SIMPLE skips the check → root node).

``hierarchy_path`` is the materialized path of UUIDs INCLUDING the node itself
(root ``/<uuid>/``, child ``/<root>/<child>/``); ``depth`` = number of
ancestors. Both are maintained by the service (and ``before_insert`` for
roots); subtree scans use ``hierarchy_path LIKE '<path>%'`` served by
``idx_organizations_path`` (``text_pattern_ops``).

A Zoho organization is simply a node of this tree (a root legal entity) with
``zoho_id`` set: the Zoho sync writes Zoho-owned columns through the apply
gate (ZohoMirrorMixin); everything structural (code, type, parent, status)
stays ours. Replaces the v1 ``zoho_organizations`` mirror.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    ORG_SCHEMA,
    AppMetaMixin,
    AuditMixin,
    DeactivationMixin,
    RowVersionMixin,
    StatusMixin,
    TenantBound,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.tenants.model import Tenant  # noqa: F401 — the relationship target must be mapped
from app.modules.zoho.sync.mixins import ZohoMirrorMixin


class Organization(
    TenantBound, AuditMixin, StatusMixin, RowVersionMixin, AppMetaMixin, DeactivationMixin,
    ZohoMirrorMixin, TimestampMixin, SoftDeleteFilteredMixin, Base,
):
    """A node in a tenant's organization tree."""

    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("uuid", name="uq_organizations_uuid"),
        # TENANT ISOLATION KEY: target of composite FKs (here and on every tenant table).
        UniqueConstraint("tenant_id", "id", name="uq_organizations_tenant_id"),
        # Safe hierarchical FK: parent and child always share a tenant.
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            [f"{ORG_SCHEMA}.organizations.tenant_id", f"{ORG_SCHEMA}.organizations.id"],
            name="fk_organizations_parent", ondelete="RESTRICT",
        ),
        CheckConstraint("id > 0", name="chk_organizations_id_positive"),
        CheckConstraint("status IN ('active','suspended','archived')", name="chk_org_status"),
        CheckConstraint("org_type IN ('holding','legal_entity','branch','solo')", name="chk_org_type"),
        CheckConstraint("depth >= 0", name="chk_org_depth"),
        CheckConstraint("org_type <> 'solo' OR parent_id IS NULL", name="chk_org_solo_rootless"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="chk_org_not_own_parent"),
        Index("uq_organizations_code_active", "tenant_id", "org_code", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        Index("idx_organizations_parent", "tenant_id", "parent_id", postgresql_where=text("deleted_at IS NULL")),
        # Subtree scans: WHERE hierarchy_path LIKE '<path>%'
        Index("idx_organizations_path", "tenant_id", "hierarchy_path",
              postgresql_ops={"hierarchy_path": "text_pattern_ops"}),
        Index("idx_organizations_custom_attr", "custom_attributes", postgresql_using="gin"),
        # A Zoho organization maps to exactly one live node per tenant.
        Index("uq_organizations_zoho_id_live", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        {"schema": ORG_SCHEMA,
         "comment": "The legal/hierarchy tree (holding → entities → branches) scoped strictly by tenant."},
    )

    # ---- Identifiers -------------------------------------------------------
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True,
        comment="Internal fast-join primary key for relational integrity.",
    )
    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid_lib.uuid4, server_default=text("gen_random_uuid()"),
        comment="Public identifier. Use this in API payloads to prevent ID enumeration.",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{ORG_SCHEMA}.tenants.id", ondelete="RESTRICT", name="fk_organizations_tenant"),
        nullable=False, comment="Owning tenant. Ensures absolute data isolation.",
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Parent organization in the hierarchy. NULL = root node.",
    )

    # ---- Core attributes ---------------------------------------------------
    org_code: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Human-readable short code. Unique within the tenant.",
    )
    legal_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Official registered legal name of the organization or branch.",
    )
    trading_name: Mapped[str | None] = mapped_column(
        String(255), comment="DBA / recognizable display name for UI and reports.",
    )
    org_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="legal_entity", server_default=text("'legal_entity'"),
        comment="Structural classification (holding, legal_entity, branch, solo).",
    )

    # ---- Materialized hierarchy navigation -----------------------------------
    hierarchy_path: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'/'"),
        comment="Materialized path of UUIDs incl. self (/root/child/) for subtree queries.",
    )
    depth: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0"),
        comment="Zero-indexed depth in the tree. Root nodes are 0.",
    )

    # ---- Financial / legal ---------------------------------------------------
    tax_id: Mapped[str | None] = mapped_column(String(50), comment="Legal tax identifier (GSTIN, VAT, EIN …).")
    currency_id: Mapped[int | None] = mapped_column(
        # use_alter: currencies → organizations (tenant/org FK) and organizations →
        # currencies form a cycle; the FK is added after both tables exist.
        BigInteger, ForeignKey("zoho_currencies.id", ondelete="SET NULL", name="fk_organizations_currency",
                               use_alter=True),
        comment="Base reporting currency (zoho_currencies.id).",
    )
    timezone: Mapped[str | None] = mapped_column(
        String(50), comment="Operational IANA timezone, overriding the tenant default.",
    )
    custom_attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment="Organization-specific data (replaces EAV).",
    )

    # ---- Profile (Zoho-owned when zoho_id is set) ----------------------------
    name: Mapped[str | None] = mapped_column(String(255), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(255))
    industry_type: Mapped[str | None] = mapped_column(String(100))
    industry_size: Mapped[str | None] = mapped_column(String(100))
    is_default_org: Mapped[bool | None] = mapped_column(Boolean)

    # ---- Locale / formats ----------------------------------------------------
    language_code: Mapped[str | None] = mapped_column(String(10))
    time_zone: Mapped[str | None] = mapped_column(String(64), comment="Zoho's time zone label (e.g. IST)")
    date_format: Mapped[str | None] = mapped_column(String(50))
    field_separator: Mapped[str | None] = mapped_column(String(10))
    fiscal_year_start_month: Mapped[int | None] = mapped_column(
        Integer, comment="0 = January … 11 = December (Zoho sends a number OR a month name)",
    )
    tax_group_enabled: Mapped[bool | None] = mapped_column(Boolean)

    # ---- Zoho account ---------------------------------------------------------
    zoho_id: Mapped[str | None] = mapped_column(String(50), index=True, comment="Zoho organization_id")
    account_created_date: Mapped[dt.date | None] = mapped_column(Date)
    is_org_active: Mapped[bool | None] = mapped_column(Boolean, comment="Zoho's own active flag")
    user_role: Mapped[str | None] = mapped_column(String(100), comment="Connected user's role in Zoho")
    user_status: Mapped[str | None] = mapped_column(String(50))
    zoho_currency_id: Mapped[str | None] = mapped_column(String(50))
    currency_code: Mapped[str | None] = mapped_column(String(10))
    currency_symbol: Mapped[str | None] = mapped_column(String(10))
    currency_format: Mapped[str | None] = mapped_column(String(50))
    price_precision: Mapped[int | None] = mapped_column(Integer)

    # ---- Address -------------------------------------------------------------
    address_street1: Mapped[str | None] = mapped_column(String(255))
    address_street2: Mapped[str | None] = mapped_column(String(255))
    address_city: Mapped[str | None] = mapped_column(String(100))
    address_state: Mapped[str | None] = mapped_column(String(100))
    address_country: Mapped[str | None] = mapped_column(String(100))
    address_zip: Mapped[str | None] = mapped_column(String(20))

    # ---- Relationships (read-only navigation; the service sets parent_id) ----
    tenant: Mapped[Tenant] = relationship(back_populates="organizations", foreign_keys=[tenant_id], viewonly=True)

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def path_uuids(self) -> list[uuid_lib.UUID]:
        """Ancestors-then-self, from the materialized path."""
        return [uuid_lib.UUID(part) for part in (self.hierarchy_path or "").split("/") if part]

    @property
    def parent_uuid(self) -> uuid_lib.UUID | None:
        path = self.path_uuids
        return path[-2] if len(path) >= 2 else None

    @property
    def is_zoho_linked(self) -> bool:
        return self.zoho_id is not None

    def __repr__(self) -> str:
        return f"<Organization id={self.id} tenant={self.tenant_id} code={self.org_code!r} type={self.org_type!r}>"


@event.listens_for(Organization, "before_insert")
def _root_defaults(_mapper, _connection, target: Organization) -> None:
    """Rows created without the service (Zoho sync, seeders) become roots:
    uuid known before INSERT, path ``/<uuid>/``, depth 0, and a code/legal name
    derived from Zoho when not given."""
    if target.uuid is None:
        target.uuid = uuid_lib.uuid4()
    if target.parent_id is None and (not target.hierarchy_path or target.hierarchy_path == "/"):
        target.hierarchy_path = f"/{target.uuid}/"
        target.depth = 0
    if not target.org_code:
        target.org_code = f"ZOHO-{target.zoho_id}" if target.zoho_id else f"ORG-{str(target.uuid)[:8].upper()}"
    if not target.legal_name:
        target.legal_name = target.name or target.org_code
