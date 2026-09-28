"""``core`` taxonomies, categories and their polymorphic assignments.

    Taxonomy            a named, organization-scoped category tree
    TaxonomyEntityType  the per-taxonomy whitelist of categorisable entity types
    Category            a tree node (nested-set bounds maintained app-side); Zoho-synced
                        through the crosswalk (business columns + a ``zoho_id`` echo)
    Categorizable       a polymorphic, temporally-windowed assignment of a thing to a category

Scoping. Every table is ``OrgEntityMixin``: ``tenant_id`` / ``organization_id``
are NOT NULL, and the composite FK to ``org_management.organizations`` proves a
row's organization belongs to its tenant. Because every row carries the same
scope shape, the reference design's polymorphic owner pair collapses into
structural composite FKs:

    fk_categories_taxonomy_scope    a category shares its taxonomy's scope+taxonomy
    fk_categories_parent_scope      a parent shares the child's scope
    fk_categorizables_category      an assignment pins the category's scope+taxonomy

The genuinely polymorphic side is ``categorizable_type``/``categorizable_id``:
the type is a real FK to ``core.entity_types.code`` and the id is proved at
COMMIT by ``core.check_categorizable_integrity()`` calling the existing
``core.assert_entity_exists()`` — the same shape ``core.check_entity_alias()``
runs in production.

Zoho provenance. ``Category`` is a crosswalk module (``SyncContract.crosswalk``):
identity, the apply gate's fence and hash, the raw document and the custom
fields live in ``sync.sync_records`` / ``sync.sync_payloads`` — NOT on this row,
so it carries none of the in-place mirror columns (``zoho_raw``,
``zoho_raw_hash``, ``sync_version`` … or ``ZohoPushableMixin``'s push state; the
crosswalk path never writes them). The one Zoho column is the ``zoho_id`` echo:
a maintained copy of Zoho's ``category_id`` that the engine writes (never by
hand, never the identity of record), kept because "is this row Zoho-linked?" is
asked on every local edit and should not need a join. Same division as
``currency.currencies`` and ``org_management.organizations``
(docs/implementation-plan/sync-crosswalk-delta-v3.md §3).

Loaders (stated): ``Taxonomy.entity_types`` → ``selectin``;
``Taxonomy.categories`` / ``Category.taxonomy`` / ``Category.parent`` →
``lazy="raise"`` (tree reads go through ``crud.py`` and the nested-set index);
``HasTagsMixin`` / ``HasDocumentsMixin`` / ``HasTaxesMixin`` are the shared viewonly relationships
(the last one: the category's taxes — ``tax.tax_assignments``, owner class ``category``).
No relationship can exist from ``Categorizable`` back to its polymorphic
target — that is what the registry + trigger replace.

Known deviation from the approved DDL: ``TaxonomyEntityType``'s uniqueness on
``(taxonomy_id, entity_type_code)`` must be a NON-partial unique index to be the
target of an FK — and PostgreSQL cannot reference a partial index. The
``categorizables`` whitelist guard is therefore enforced by
``core.check_categorizable_integrity()`` (which already reads
``allows_multiple`` from that table) instead of a composite FK.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    BigIntPKWithUUIDv7Mixin,
    DeactivationMixin,
    OrgEntityMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.categories.enums import (
    CORE_SCHEMA,
    CategoryRecordStatus,
    CategoryStatus,
    TaxonomyStatus,
    values,
)
from app.modules.documents.mixins import HasDocumentsMixin
from app.modules.tags.mixins import HasTagsMixin
from app.modules.taxes.mixins import HasTaxesMixin

_LIVE = text("deleted_at IS NULL")
_NAME_NORM = r"lower(btrim(regexp_replace(name, '\s+', ' ', 'g')))"
_RECORD_STATUSES = ",".join(str(int(member)) for member in CategoryRecordStatus)


class Taxonomy(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A named category tree, organization-scoped within a tenant."""

    __tablename__ = "taxonomies"
    __table_args__ = (
        # FK targets for categories: the (id, slug) pair backs taxonomy_slug's
        # cascade; the (tenant, organization, id) key backs the scope FK.
        UniqueConstraint("id", "slug", name="uq_taxonomies_id_slug"),
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_taxonomies_scope_id"),
        CheckConstraint(f"status IN ({values(TaxonomyStatus)})", name="ck_taxonomies_status"),
        CheckConstraint("btrim(slug) <> ''", name="ck_taxonomies_slug_not_blank"),
        # organization_id is NOT NULL, so this needs no NULLS NOT DISTINCT dance.
        Index("uq_taxonomies_scope_slug", "tenant_id", "organization_id", "slug",
              unique=True, postgresql_where=_LIVE),
        {"schema": CORE_SCHEMA, "comment": "Named category tree, organization-scoped."},
    )

    slug: Mapped[str] = mapped_column(Text, nullable=False, comment="Stable per-organization key")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Redeclared over StatusMixin: 'draft' until an admin activates the tree.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TaxonomyStatus.DRAFT.value,
        server_default=text("'draft'"), index=True, comment="draft / active / retired",
    )

    entity_types: Mapped[list["TaxonomyEntityType"]] = relationship(
        "TaxonomyEntityType",
        primaryjoin="Taxonomy.id == foreign(TaxonomyEntityType.taxonomy_id)",
        order_by="TaxonomyEntityType.entity_type_code",
        viewonly=True, lazy="selectin",
    )
    categories: Mapped[list["Category"]] = relationship(
        "Category",
        primaryjoin="Taxonomy.id == foreign(Category.taxonomy_id)",
        viewonly=True, lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Taxonomy id={self.id} slug={self.slug!r} org={self.organization_id}>"


class TaxonomyEntityType(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """Which entity types a taxonomy accepts, and whether a thing may pick many.

    ``allows_multiple``: NULL = multi-valued (permissive), ``false`` =
    single-valued (the integrity trigger rejects a second live category).
    """

    __tablename__ = "taxonomy_entity_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_taxonomy_entity_types_scope_id"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "taxonomy_id"],
            [f"{CORE_SCHEMA}.taxonomies.tenant_id", f"{CORE_SCHEMA}.taxonomies.organization_id",
             f"{CORE_SCHEMA}.taxonomies.id"],
            name="fk_taxonomy_entity_types_taxonomy", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["entity_type_code"], [f"{CORE_SCHEMA}.entity_types.code"],
                             name="fk_taxonomy_entity_types_entity_type", ondelete="RESTRICT"),
        Index("uq_taxonomy_entity_types_scope", "taxonomy_id", "entity_type_code",
              unique=True, postgresql_where=_LIVE),
        {"schema": CORE_SCHEMA, "comment": "Per-taxonomy whitelist of categorisable entity types."},
    )

    taxonomy_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entity_type_code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="core.entity_types.code",
    )
    allows_multiple: Mapped[bool | None] = mapped_column(
        Boolean, comment="NULL = multi-valued (permissive); false = single-valued",
    )

    taxonomy: Mapped[Taxonomy] = relationship(
        "Taxonomy",
        primaryjoin="foreign(TaxonomyEntityType.taxonomy_id) == Taxonomy.id",
        viewonly=True, lazy="raise",
    )


class Category(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, DeactivationMixin,
    SoftDeleteFilteredMixin, HasTagsMixin, HasDocumentsMixin, HasTaxesMixin, Base,
):
    """A category tree node; nested-set bounds (``_lft``/``_rgt``) maintained app-side."""

    __tablename__ = "categories"
    __table_args__ = (
        # FK target of fk_categories_parent (same-taxonomy self reference).
        UniqueConstraint("taxonomy_id", "id", name="uq_categories_taxonomy_id_id"),
        # FK target of fk_categories_parent_scope ((tenant, org, parent_id)).
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_categories_scope_id"),
        # FK target of fk_categorizables_category (scope + taxonomy + category).
        UniqueConstraint("tenant_id", "organization_id", "taxonomy_id", "id",
                         name="uq_categories_scope_taxonomy_id"),
        # A category always shares its taxonomy's scope and taxonomy (D1).
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "taxonomy_id"],
            [f"{CORE_SCHEMA}.taxonomies.tenant_id", f"{CORE_SCHEMA}.taxonomies.organization_id",
             f"{CORE_SCHEMA}.taxonomies.id"],
            name="fk_categories_taxonomy_scope", ondelete="CASCADE",
        ),
        # taxonomy_slug follows a taxonomy rename (cascade), the id does not.
        ForeignKeyConstraint(
            ["taxonomy_id", "taxonomy_slug"],
            [f"{CORE_SCHEMA}.taxonomies.id", f"{CORE_SCHEMA}.taxonomies.slug"],
            name="fk_categories_taxonomy_slug", onupdate="CASCADE",
        ),
        # A parent is in the same taxonomy and, structurally, the same scope.
        ForeignKeyConstraint(
            ["taxonomy_id", "parent_id"],
            [f"{CORE_SCHEMA}.categories.taxonomy_id", f"{CORE_SCHEMA}.categories.id"],
            name="fk_categories_parent", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "parent_id"],
            [f"{CORE_SCHEMA}.categories.tenant_id", f"{CORE_SCHEMA}.categories.organization_id",
             f"{CORE_SCHEMA}.categories.id"],
            name="fk_categories_parent_scope", ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN ({values(CategoryStatus)})", name="ck_categories_status"),
        CheckConstraint("NOT (is_root AND parent_id IS NOT NULL)", name="ck_categories_root_no_parent"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_categories_no_self_parent"),
        CheckConstraint("_rgt >= _lft", name="ck_categories_nested_set_bounds"),
        CheckConstraint("depth >= 0", name="ck_categories_depth_nonneg"),
        CheckConstraint(f"record_status IN ({_RECORD_STATUSES})", name="ck_categories_record_status"),
        CheckConstraint("position >= 0", name="ck_categories_position_nonneg"),
        CheckConstraint("display_order >= 0", name="ck_categories_display_order_nonneg"),
        CheckConstraint("menu_order >= 0", name="ck_categories_menu_order_nonneg"),
        CheckConstraint("num_nulls(noteable_type, noteable_id) IN (0, 2)", name="ck_categories_noteable_pair"),
        CheckConstraint("code IS NULL OR btrim(code) <> ''", name="ck_categories_code_not_blank"),
        CheckConstraint("slug IS NULL OR btrim(slug) <> ''", name="ck_categories_slug_not_blank"),
        Index("uq_categories_zoho_id_live", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("uq_categories_scope_code", "tenant_id", "organization_id", "taxonomy_id", "code",
              unique=True, postgresql_where=text("code IS NOT NULL AND deleted_at IS NULL")),
        Index("uq_categories_scope_slug", "tenant_id", "organization_id", "taxonomy_id", "slug",
              unique=True, postgresql_where=text("slug IS NOT NULL AND deleted_at IS NULL")),
        Index("ix_categories_scope_lft_rgt", "tenant_id", "organization_id", "taxonomy_id",
              "_lft", "_rgt", postgresql_where=_LIVE),
        Index("ix_categories_taxonomy_id", "taxonomy_id"),
        Index("ix_categories_parent_position", "parent_id", "position"),
        Index("ix_categories_is_active", "is_active"),
        Index("ix_categories_name_trgm", "name_normalized", postgresql_using="gin",
              postgresql_ops={"name_normalized": "gin_trgm_ops"}, postgresql_where=_LIVE),
        {"schema": CORE_SCHEMA,
         "comment": "Category tree node (nested-set bounds maintained app-side); Zoho-synced."},
    )

    # ---- Zoho echo (the identity of record is sync.sync_records) --------------
    zoho_id: Mapped[str | None] = mapped_column(
        String(50), index=True,
        comment="Echo of Zoho's category_id, written by the sync engine; identity of record is sync.sync_records",
    )

    # ---- identity / display --------------------------------------------------
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str | None] = mapped_column(
        Text, Computed(_NAME_NORM, persisted=True),
        comment="STORED generated lower-cased name; uniqueness + trigram search",
    )
    category: Mapped[str | None] = mapped_column(Text, comment="Source 'category' label")
    code: Mapped[str | None] = mapped_column(Text, comment="Short internal code, unique per taxonomy")
    title: Mapped[str | None] = mapped_column(Text)
    sub_title: Mapped[str | None] = mapped_column(Text)
    slug: Mapped[str | None] = mapped_column(Text, comment="URL-friendly key, unique per taxonomy")
    short_description: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text, comment="Source classification")
    ondc_category_type: Mapped[str | None] = mapped_column(Text)

    # ---- tree ----------------------------------------------------------------
    taxonomy_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    taxonomy_slug: Mapped[str | None] = mapped_column(Text, comment="Denormalised, follows a rename")
    parent_id: Mapped[int | None] = mapped_column(BigInteger, comment="NULL = root of the taxonomy")
    is_root: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    can_have_children: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="Service-set; the scope guard refuses a child under a leaf",
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    path: Mapped[str | None] = mapped_column(Text, comment="Text breadcrumb, maintained by tree.py")
    lft: Mapped[int] = mapped_column("_lft", Integer, nullable=False, default=0, server_default=text("0"))
    rgt: Mapped[int] = mapped_column("_rgt", Integer, nullable=False, default=0, server_default=text("0"))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    menu_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    show_in_menu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    # ---- record_* (source metadata ported verbatim, L1) ----------------------
    record_order: Mapped[int | None] = mapped_column(Integer)
    record_previous: Mapped[int | None] = mapped_column(BigInteger)
    record_next: Mapped[int | None] = mapped_column(BigInteger)
    record_status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=int(CategoryRecordStatus.NORMAL),
        server_default=text("0"), comment="-1 deleted / 0 normal / 1 archived (source vocabulary)",
    )
    record_tags: Mapped[dict | None] = mapped_column(JSONB)
    record_notes: Mapped[dict | None] = mapped_column(JSONB)
    noteable_type: Mapped[str | None] = mapped_column(String(64))
    noteable_id: Mapped[int | None] = mapped_column(BigInteger)
    document_id: Mapped[int | None] = mapped_column(BigInteger)
    # DB column stays `documents`; the Python attribute is renamed because
    # HasDocumentsMixin owns `.documents` (the relationship) — the same
    # collision-avoidance transform as the `metadata` trap.
    documents_snapshot: Mapped[dict | None] = mapped_column("documents", JSONB)

    # ---- SEO -----------------------------------------------------------------
    meta_title: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    meta_keywords: Mapped[list | None] = mapped_column(
        JSONB, comment="JSON array of keyword strings (Zoho sends one comma-separated string)",
    )

    # ---- media / display -----------------------------------------------------
    icon: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    icon_color: Mapped[str | None] = mapped_column(Text)
    icon_bg_color: Mapped[str | None] = mapped_column(Text)
    icon_bg_image: Mapped[str | None] = mapped_column(Text)
    icon_border_color: Mapped[str | None] = mapped_column(Text)
    preview_image: Mapped[str | None] = mapped_column(Text)
    thumbnail: Mapped[str | None] = mapped_column(Text)
    banner: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text, comment="Stored display cache (L1)")
    thumbnail_url: Mapped[str | None] = mapped_column(Text, comment="Stored display cache (L1)")
    banner_url: Mapped[str | None] = mapped_column(Text, comment="Stored display cache (L1)")

    # ---- flags ---------------------------------------------------------------
    # status / is_verified come from StatusMixin; status redeclares the default.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CategoryStatus.ACTIVE.value,
        server_default=text("'active'"), index=True, comment="active / archived",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_promoted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_sponsored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_partnered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    visibility: Mapped[str | None] = mapped_column(String(20))
    is_bookmarked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    # ---- flexible buckets ----------------------------------------------------
    settings: Mapped[dict | None] = mapped_column(JSONB)
    # The SQLAlchemy `metadata` trap: DB column stays `metadata`, the attribute
    # is `metadata_`.
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    extra_attributes: Mapped[dict | None] = mapped_column(JSONB)

    # ---- relationships -------------------------------------------------------
    taxonomy: Mapped[Taxonomy] = relationship(
        "Taxonomy",
        primaryjoin="foreign(Category.taxonomy_id) == Taxonomy.id",
        viewonly=True, lazy="raise",
    )
    # Two FKs link the table to itself (taxonomy-scoped parent + scope-guarded
    # parent), so the join needs an explicit foreign key.
    @declared_attr
    def parent(cls):  # noqa: N805
        return relationship(
            "Category", remote_side="Category.id",
            foreign_keys=[cls.taxonomy_id, cls.parent_id],
            viewonly=True, lazy="raise",
        )

    def __repr__(self) -> str:
        return f"<Category id={self.id} name={self.name!r} taxonomy={self.taxonomy_id}>"


class Categorizable(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A thing's assignment to a category, with a validity window."""

    __tablename__ = "categorizables"
    __table_args__ = (
        # Pins the assignment to the category's scope AND taxonomy at once.
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "taxonomy_id", "category_id"],
            [f"{CORE_SCHEMA}.categories.tenant_id", f"{CORE_SCHEMA}.categories.organization_id",
             f"{CORE_SCHEMA}.categories.taxonomy_id", f"{CORE_SCHEMA}.categories.id"],
            name="fk_categorizables_category", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["categorizable_type"], [f"{CORE_SCHEMA}.entity_types.code"],
                             name="fk_categorizables_entity_type", ondelete="RESTRICT"),
        CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
                        name="ck_categorizables_valid_window"),
        CheckConstraint("sort_order >= 0", name="ck_categorizables_sort_order"),
        # One live open-ended assignment per (category, thing).
        Index("uq_categorizables_category_thing", "category_id", "categorizable_type", "categorizable_id",
              unique=True, postgresql_where=text("deleted_at IS NULL AND valid_to IS NULL")),
        # At most one primary per (thing, taxonomy).
        Index("uq_categorizables_one_primary", "taxonomy_id", "categorizable_type", "categorizable_id",
              unique=True,
              postgresql_where=text("is_primary IS TRUE AND deleted_at IS NULL AND valid_to IS NULL")),
        Index("ix_categorizables_category_sort", "category_id", "sort_order"),
        Index("ix_categorizables_thing", "categorizable_type", "categorizable_id", postgresql_where=_LIVE),
        Index("ix_categorizables_taxonomy_type", "taxonomy_id", "categorizable_type"),
        {"schema": CORE_SCHEMA,
         "comment": "Polymorphic assignment of a thing to a category, with validity window."},
    )

    category_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    taxonomy_id: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                             comment="Derived from the category by a BEFORE INSERT trigger")
    categorizable_type: Mapped[str] = mapped_column(String(64), nullable=False,
                                                    comment="core.entity_types.code")
    categorizable_id: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                  comment="Internal id; proved at COMMIT by trigger")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    valid_from: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    valid_to: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)

    def __repr__(self) -> str:
        return (f"<Categorizable {self.category_id} -> "
                f"{self.categorizable_type}:{self.categorizable_id}>")


__all__ = ["Category", "Categorizable", "Taxonomy", "TaxonomyEntityType"]
