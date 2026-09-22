# Categories & Taxonomies — Implementation Plan

**Document Reference:** `docs/implementation-plan/categories-taxonomies-implementation-plan.md`
**Status:** DRAFT (Architecture Review)
**Author:** Principal Enterprise Systems Architect
**Date:** September 2026
**Scope:** new `app/modules/categories/` (backend); consumes `app/modules/entities/`,
`app/database/mixins.py`, `app/database/tenancy.py`, `app/database/soft_delete.py`,
`app/modules/tags/`, `app/modules/documents/`
**Source design:** the approved *Categories — Architecture & Implementation Guide*
(registry-driven taxonomy tree + `categorizables` M:N; `models.py` / `enums.py` /
`sql/categories_module.sql` companion) pasted with this task, reconciled against
`docs/architecture-prompts/master-prompt.md`.

---

## 1. Understanding (what was asked)

Build the **Categories and Taxonomies** module in the backend: a named, optionally
org-owned **taxonomy tree** (`core.taxonomies` → `core.categories`), a per-taxonomy
**whitelist of categorisable entity types** (`core.taxonomy_entity_types`), and a
**polymorphic many-to-many assignment table** (`core.categorizables`) with
temporal validity windows, cardinality rules and a registry-validated
`categorizable_type`. The source design solves polymorphic integrity with a
registry (`core.entity_types`) + PL/pgSQL `assert_entity_exists()` + deferred
constraint triggers.

The task explicitly asks to reconcile this against what this codebase **already
has** (mixins, tenancy, the `core` registry, the documents/tags/media
attachment mixins, …), decide what is reused vs. built, and produce the full
implementation plan. This document is that plan.

**Open questions are collected in §14** — the two that could change the schema
are (a) the fate of the legacy Zoho/ONDC `record_*` column family and (b)
whether "global" taxonomies must be **cross-tenant** or tenant-shared. Defaults
for both are baked into the plan below and marked where they bite.

---

## 2. Current state — what already exists (and therefore is NOT built)

The source design assumes a greenfield schema. Two thirds of its machinery
already exists in this repository, in mature, tested form. **Do not rebuild any
of this:**

| Source-design concept | Already implemented here | Evidence |
|---|---|---|
| `core` schema + `pg_trgm` | created by migration `b1a2c3d4e5f6` | `alembic/versions/20260922_0900_…_core_master_data_brands_manufacturers.py` |
| **`core.entity_types` registry** (`code → target_schema.target_table`) | `app.modules.entities.model.EntityType` + `GET /api/entities/types` | `app/modules/entities/model.py` |
| **`core.assert_entity_exists(type, id)`** — dynamic-SQL polymorphic existence check, `STABLE`, `23503` on failure | `CREATE FUNCTION core.assert_entity_exists(text, bigint)` | migration `b1a2c3d4e5f6` (functions & triggers section) |
| Registry-fed deferred constraint trigger proving a polymorphic target exists | `core.check_entity_alias()` + `ctrg_entity_aliases_integrity` (works exactly like the design's `check_owner_exists`) | same migration |
| Registry-fed orphan detector (`find_orphan_*`) | `core.find_orphan_entity_aliases()` | same migration |
| Cycle-guarded self-referential tree + advisory lock + recursive-CTE cycle check | `core.guard_brand_parent()` + `trg_brands_parent_guard` (identical shape to the design's `guard_category_scope` (c)/(d)) | same migration |
| No-overlapping-validity-windows deferred trigger (`23P01 exclusion_violation`) | `core.check_brand_manufacturer_overlap()` + `ctrg_brand_manufacturers_overlap` (identical shape to the design's `check_categorizable_integrity` step 6) | same migration |
| Timestamps / audit (`created_by_name` "who, denormalised") / optimistic lock / UUID v7 / soft delete / app meta | `TimestampMixin`, `AuditMixin`, `RowVersionMixin`, `BigIntPKWithUUIDv7Mixin`, `SoftDeleteFilteredMixin`, `AppMetaMixin` | `app/database/mixins.py` |
| Tenant/organization scoping ("owner") incl. DB-enforced org existence | `TenantScopedMixin` / `MultiTenantMixin` + composite FK `(tenant_id, organization_id) → org_management.organizations(tenant_id, id)` + the tenancy runtime (auto filter + insert stamping + cross-tenant guard) | `app/database/mixins.py`, `app/database/tenancy.py` |
| Polymorphic owner/provenance pair (if we ever need non-org owners) | `PolymorphicOwnerMixin` (CHECK'd vocabulary) — and the newer registry-validated variant is exactly `EntityAlias.entity_type/entity_id` | `app/modules/entities/model.py` |
| One-line "attach X to any model" mixins (viewonly, selectinload-friendly, async-safe) | `HasTagsMixin`, `HasDocumentsMixin`, `HasMediaMixin` | `app/modules/{tags,documents,media}/mixins.py` |
| Catalog table + polymorphic pivot with `sort_order` / `is_primary` / partial uniques / validity & versioning | the **documents** module (`document_types` + `document_links`) | `app/modules/documents/model.py` |
| Assignment write path (validate ids in one query → sync pivot → record activity) | `tags.service.sync_tags_for_entity` / `tags.crud.sync_entity_tags` | `app/modules/tags/` |
| The module template this plan copies (scope resolver, rule table in the service docstring, Slim/Fat DTOs, uuid refs, activity log, conflict errors, `lazy="raise"` loaders, trigram index) | the **brands** module | `app/modules/brands/` |
| PL/pgSQL placement convention | SQL lives **inside the Alembic migration** (`op.execute`), downgrade drops functions/triggers — there is no `sql/*.sql` sidecar in this repo | migration `b1a2c3d4e5f6` |
| Enum vocabulary → CHECK building (`values(MyEnum)`) so constraint and vocabulary cannot drift | `app/modules/entities/enums.py: values()` | used by documents, brands |
| Error hierarchy + response envelope + activity recorder + structlog conventions | `app/common/exception/errors.py`, `app/common/response/`, `app/modules/activity/recorder.py` | — |
| Test infrastructure (scratch-Postgres `db` fixture, `_TEST_TABLES` truncation, `worlds` two-tenant fixture, hermetic/mocked/integration layers) | `tests/conftest.py`, `tests/tenancy_fixtures.py` | — |
| `uuidv7()` PG18, `pg_trgm`, `ltree` availability | deployment Postgres 18 image | master prompt `<deployment_topology>` |

**Net: the source design's registry layer, existence resolver, orphan-detector
pattern, cycle guard, overlap-window trigger, owner-existence trigger, and all
column-bundle mixins are already built and proven.** The genuinely new surface
is: four tables (+1 deferred), three new PL/pgSQL functions + two guards, the
tree-bounds maintenance routine, the `HasCategoriesMixin`, and the
api/schema/service/crud layer.

---

## 3. Design deltas — reconciling the approved DDL with house patterns

These are the deliberate deviations from the pasted DDL. Each replaces a
hand-rolled mechanism of the reference with an established one here, exactly as
migration `b1a2c3d4e5f6` did when it adopted its own reference design.

### D1. Ownership: `owner_type/owner_id` → tenancy columns (largest delta)

The reference models "this taxonomy belongs to org 42" as a polymorphic pair
`owner_type='organization', owner_id=42`, validated by `check_owner_exists()`
plus **three constraint triggers** (`ctrg_taxonomies_owner`,
`ctrg_categories_owner`, `ctrg_categorizables_owner`), guarded by an
`owner_pair` CHECK on three tables.

Here, "belongs to org 42 of tenant T" is exactly what
`TenantScopedMixin`/`TenantEntityMixin` already express, with **better**
integrity: the composite FK `(tenant_id, organization_id) →
org_management.organizations(tenant_id, id)` proves existence *immediately* (no
deferred trigger needed) **and** proves tenant-membership, which the reference
design cannot check at all. On top of that we inherit the tenancy runtime (auto
tenant filter on every SELECT, insert stamping, cross-tenant write guard).

**Mapping of the reference's owner semantics:**

| Reference | This implementation |
|---|---|
| `(owner_type, owner_id)` = organization | `organization_id` (FK-proven) |
| `NULL/NULL` = global/shared | `organization_id IS NULL` = shared across the tenant |
| `owner_pair` CHECK `num_nulls(...) IN (0,2)` | not needed — `tenant_id` is NOT NULL and `organization_id` is a single nullable column; `MATCH SIMPLE` on the composite org FK does the rest |
| `check_owner_exists()` + 3 constraint triggers | **deleted** — the composite FK replaces them |
| `find_orphan_owners()` | **deleted** — orphans are impossible by construction |
| cross-tenant "global" taxonomy | **not in v1** — every row is tenant-scoped (isolation is non-negotiable in this platform). Platform-wide template taxonomies are a later seed/export feature (§14 Q2) |

The design's *business* owner rules survive unchanged (they are cross-row, so
they stay in `core.guard_category_scope()` / `core.check_categorizable_integrity()`):

- category `organization_id` must equal the taxonomy's when the taxonomy is org-scoped (shared taxonomy ⇒ category may be shared or org-scoped);
- parent category must share the child's `(tenant_id, organization_id)`;
- assignments of an org-scoped category carry that same organization.

### D2. The categorisable side keeps the registry — and reuses the one we have

`categorizable_type`/`categorizable_id` is genuinely polymorphic (brands, items,
vehicles, …) and gets the reference's treatment **verbatim in mechanism**, but
served by the existing infrastructure: `categorizable_type` is a **real FK to
`core.entity_types.code`** (registry-validated spelling, exactly like
`EntityAlias.entity_type`), and `categorizable_id` is proven at COMMIT by a
deferred constraint trigger calling the existing
`core.assert_entity_exists()`. This is byte-for-byte the pattern
`core.check_entity_alias()` already runs in production.

### D3. `core.entity_types` needs **no change**

The reference adds `status (active/retired)` and stops filtering on
`deleted_at`. Ours resolves registry rows with `deleted_at IS NULL` and is
wrapped by FK `ondelete=RESTRICT`. Semantics difference and why we keep ours:

- Retiring = soft delete of the registry row. New writes of that type then fail
  `assert_entity_exists` (`23503`) — "retired type" behaves like the
  reference's retired type **for new writes**.
- **Existing rows stay valid**, because the constraint triggers only fire on
  `INSERT`/`UPDATE OF <validated columns>` — a tombstone or unrelated edit never
  re-validates. This is the one behavioral nuance vs. the reference (which
  re-validates on any trigger firing even for retired types); it is acceptable
  and arguably better. Adding `status` later is a two-line migration if
  "retired but must keep validating" turns out to matter (§14 Q5).

### D4. Category columns: typed for what we query, JSONB for the rest

The reference `Category` is a ~55-column verbatim port of a Zoho/ONDC source
record (`record_order`, `record_previous`, `record_next`, `record_status`,
`record_tags`, `record_notes`, `noteable_*`, six `icon_*` columns, three cached
`*_url` columns, …). House doctrine #3/#4 says: extracted typed columns for what
we query and index; the untouched source payload survives in JSONB; presentation
fields (`*_url`) are computed, never persisted (`media` module is the precedent
— `_url_for()` derives URLs from storage keys). The full per-column mapping is
in §5.3 — **every reference column is accounted for** (KEEP / MIXIN / FOLD into
`extra_metadata` / SUPERSEDED / DROP-derived), per the ingestion protocol's
"never silently drop a column".

### D5. Tree structure: `parent_id` + `_lft`/`_rgt` + `depth` + `path`, maintained app-side

Keep the approved columns. Maintenance strategy (the reference says
"maintained app-side" without saying how):

- **One routine owns the bounds**: `app/modules/categories/tree.py`, pure
  functions (`recompute_bounds(rows) -> rows`, `ancestors_of`, `subtree_of`) so
  the algorithm is hermetically unit-testable;
- the service calls it after every structural change (create/move/delete),
  recomputing `_lft/_rgt/depth/path` for the **whole taxonomy** in the same
  transaction while holding the design's per-taxonomy advisory lock
  (`pg_advisory_xact_lock(hashtextextended('category_tree:'||taxonomy_id, 0))`,
  already taken by `guard_category_scope` on re-parents). Category trees are
  small (hundreds of nodes); a full recompute under an exclusive per-tree lock
  is simpler and provably correct vs. incremental bound shifts.
- `path` stays a text breadcrumb (`/apparel/shirts`) maintained in the same
  pass. The `ltree` extension is available if subtree queries outgrow
  `BETWEEN _lft AND _rgt`, but v1 does not need both (§14 Q6).

### D6. `core.category_stats` — deferred to phase 2

It is an **inferred** table even in the reference (the approved DDL only
mentions it), and every counter it caches (`items_count`, `has_active_items`)
counts `categorizables` of entity types that are not categorised yet at launch.
Building a cache before its source of truth is in use violates AP20 ("a counter
is a cache") in spirit. Phase 2 (§12) adds it with the exact minimal shape from
the reference model (`category_id` 1:1, `items_count`, `views_count`,
`has_active_items`, `stats_as_of`) plus a Celery refresh job.

### D7. Naming: house prefixes for constraints, verbatim names for functions

The "names match the approved DDL verbatim" property is a property of the
*source repo's* SQL file. Here, `core` already contains objects named in house
style (`ck_entity_types_code_not_blank`, `uq_entity_aliases_current`,
`guard_brand_parent`). We keep **function/trigger names verbatim** where they
don't collide (they fit the house `guard_*`/`check_*`/`find_orphan_*`
convention) and use **house prefixes** for constraints/indexes. The complete
approved-name → house-name map is in §5.4 so a reviewer can diff against the
approved DDL without guessing.

### D8. SQL placement: inside the Alembic migration

No `sql/categories_module.sql` sidecar. The functions/triggers/seed go in the
one migration that creates the tables, exactly like `b1a2c3d4e5f6` (upgrade
creates, downgrade drops in reverse order). Grants/roles policy is unchanged
platform-wide and is **not** part of this module (the reference's §4 grants
assume a DB-role model this platform does not use; the registry's write
protection here is "the API exposes `entity_types` read-only" — already true:
`GET /api/entities/types` only).

### D9. `check_categorizable_integrity` is kept almost verbatim — the one real temporal guard

Steps 1–6 of the reference survive with `x.tenant_id = NEW.tenant_id` added to
the overlap scan and `organization_id` substituted for the owner pair. It is
the same shape as the proven `check_brand_manufacturer_overlap()`, extended
with the looked-up cardinality (`allows_multiple`). `tstzrange` + advisory lock
+ `23P01` on failure are kept exactly.

### D10. `guard_taxonomy_owner_change` survives as `guard_taxonomy_organization_change`

Same rule, one column narrower: once a taxonomy has any categories its
`organization_id` is frozen (BEFORE UPDATE OF organization_id). Moving
ownership = empty/move the categories first.

### D11. `fill_categorizable_defaults` survives with tenant-aware inheritance

BEFORE INSERT on `categorizables`: derive `taxonomy_id` from the category;
inherit `organization_id` from the category when the caller supplied none (the
tenancy runtime stamps it from request context first if a context org is bound —
so "explicit request org" wins and rule enforcement (§D9 step 4) rejects a
mismatch with a clean pre-flight 422 in the service).

### D12. New: `HasCategoriesMixin` (the design has no mixin)

Every attachment concern in this codebase ships a one-line mixin
(`HasTagsMixin`/`HasDocumentsMixin`/`HasMediaMixin`). Categories get the same:

```python
class HasCategoriesMixin:
    @declared_attr
    def categories(cls): ...  # viewonly, through Categorizable, lazy="raise_on_sql"
```

viewonly (async-safety, the tags/documents rule), `lazy="raise_on_sql"` (the
media N+1 firewall, generalized as house style in
`<n_plus_one_doctrine>`), join filtered to live + currently-valid assignments,
ordered by `Categorizable.sort_order`. Read path is always an explicit
`selectinload(Model.categories)`.

### D13. Cross-cutting: translate deferred-trigger failures at COMMIT

Deferred constraint triggers raise at the `session.commit()` inside `get_db`
(`app/database/db.py`), which today falls through to the generic 500 handler.
Services pre-flight the common violations for clean 422s (the brands pattern),
but the temporal/registry checks are *deliberately* deferred. Add one shared
handler in `app/common/exception/handlers.py`: `IntegrityError` → envelope
response mapped by SQLSTATE (`23505`→409, `23503`→422 "referenced row does not
exist", `23514`→422, `23P01`→409, `40001`/deadlock →409 retry). This benefits
every existing module too and is the only change outside `app/modules/categories/`.

---

## 4. Module / file plan (FBA layering)

```
app/modules/categories/
├── __init__.py
├── model.py       # Taxonomy, TaxonomyEntityType, Category, Categorizable  (core schema)
├── enums.py       # TaxonomyStatus, CategoryStatus, AssignmentFlags vocab; values()
├── mixins.py      # HasCategoriesMixin (viewonly categories relationship)
├── tree.py        # PURE nested-set/path/depth recompute functions (unit-tested, no I/O)
├── crud.py        # all SQL; load_only Slim queries; no business rules
├── service.py     # rules table in the docstring; pre-flight validation; activity log
├── schema.py      # Slim/Fat Out DTOs + Create/Update DTOs (row_version in updates)
├── api.py         # taxonomies_router, categories_router, categorizables_router
└── seed.py        # starter taxonomies / whitelist rows (idempotent, never overwrites)
```

Registration checklist (master prompt §6):

1. `alembic/env.py`: `from app.modules.categories import model as _categories_model  # noqa: F401`
2. `app/router.py`: three includes — `/api/taxonomies`, `/api/categories`,
   `/api/categorizables` (multi-router module precedent: `geo`).
3. `tests/conftest.py` `_TEST_TABLES`: children before parents (see §9).
4. Debezium `table.include.list` / `SEARCH_CDC_TOPICS` / `SearchableEntity`:
   **phase 2 option** (§12) — not required for v1 correctness.

---

## 5. Schema

### 5.1 Target model shape (sketch)

```python
# model.py — column sets abbreviated; full mapping in §5.3
_LIVE = text("deleted_at IS NULL")

class Taxonomy(BigIntPKWithUUIDv7Mixin, TenantEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "taxonomies"
    __table_args__ = (
        UniqueConstraint("id", "slug", name="uq_taxonomies_id_slug"),      # FK target for categories.taxonomy_slug
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_taxonomies_scope_id"),
        CheckConstraint(f"status IN ({values(TaxonomyStatus)})", name="ck_taxonomies_status"),
        CheckConstraint("btrim(slug) <> ''", name="ck_taxonomies_slug_not_blank"),
        # one live slug per owner scope; organization_id NULL = tenant-shared (NULLS NOT DISTINCT,
        # house precedent: uq_manufacturer_identifiers_current)
        Index("uq_taxonomies_scope_slug", "tenant_id", "organization_id", "slug", unique=True,
              postgresql_nulls_not_distinct=True, postgresql_where=_LIVE),
        {"schema": CORE_SCHEMA, "comment": "Named category tree; organization_id NULL = tenant-shared."},
    )
    slug / name / description ...
    status: Mapped[str]   # redeclared over StatusMixin: server_default 'draft', CHECK TaxonomyStatus
    categories: Mapped[list["Category"]] = relationship(lazy="raise", viewonly=True, ...)
    entity_types: Mapped[list["TaxonomyEntityType"]] = relationship(lazy="selectin", ...)   # Fat read

class TaxonomyEntityType(BigIntPKWithUUIDv7Mixin, TenantEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "taxonomy_entity_types"
    # (tenant_id, taxonomy_id) composite FK → taxonomies(tenant_id, id)   [documents child pattern]
    # entity_type_code FK → core.entity_types.code (ondelete RESTRICT)
    # allows_multiple: bool | None      # NULL = multi-valued (permissive), false = single-valued
    # UNIQUE (taxonomy_id, entity_type_code) WHERE deleted_at IS NULL

class Category(BigIntPKWithUUIDv7Mixin, TenantEntityMixin, DeactivationMixin,
               SoftDeleteFilteredMixin, HasTagsMixin, HasDocumentsMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("taxonomy_id", "id", name="uq_categories_taxonomy_id_id"),
        ForeignKeyConstraint(["tenant_id", "taxonomy_id"],
                            ["core.taxonomies.tenant_id", "core.taxonomies.id"],
                            name="fk_categories_taxonomy", ondelete="CASCADE"),
        ForeignKeyConstraint(["taxonomy_id", "taxonomy_slug"],
                            ["core.taxonomies.id", "core.taxonomies.slug"],
                            name="fk_categories_taxonomy_slug", onupdate="CASCADE"),
        # parent in the SAME taxonomy (MATCH SIMPLE: roots skip it)
        ForeignKeyConstraint(["taxonomy_id", "parent_id"],
                            ["core.categories.taxonomy_id", "core.categories.id"],
                            name="fk_categories_parent", ondelete="SET NULL (parent_id)"),
        # parent in the SAME tenant+organization (rule (c) as a real FK)
        ForeignKeyConstraint(["tenant_id", "organization_id", "parent_id"],
                            ["core.categories.tenant_id", "core.categories.organization_id",
                             "core.categories.id"],
                            name="fk_categories_parent_scope", ondelete="SET NULL (parent_id)"),
        CheckConstraint("NOT (is_root AND parent_id IS NOT NULL)", name="ck_categories_root_no_parent"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_categories_no_self_parent"),
        CheckConstraint("_rgt >= _lft", name="ck_categories_nested_set_bounds"),
        CheckConstraint("depth >= 0", name="ck_categories_depth_nonneg"),
        CheckConstraint("position >= 0", name="ck_categories_position_nonneg"),
        CheckConstraint("display_order >= 0", name="ck_categories_display_order_nonneg"),
        CheckConstraint("menu_order >= 0", name="ck_categories_menu_order_nonneg"),
        CheckConstraint("code IS NULL OR btrim(code) <> ''", name="ck_categories_code_not_blank"),
        CheckConstraint("slug IS NULL OR btrim(slug) <> ''", name="ck_categories_slug_not_blank"),
        Index("uq_categories_scope_code", "tenant_id", "organization_id", "taxonomy_id", "code",
              unique=True, postgresql_nulls_not_distinct=True,
              postgresql_where=text("code IS NOT NULL AND deleted_at IS NULL")),
        Index("uq_categories_scope_slug", "tenant_id", "organization_id", "taxonomy_id", "slug",
              unique=True, postgresql_nulls_not_distinct=True,
              postgresql_where=text("slug IS NOT NULL AND deleted_at IS NULL")),
        Index("ix_categories_scope_lft_rgt", "tenant_id", "organization_id", "taxonomy_id", "_lft", "_rgt",
              postgresql_where=_LIVE),
        Index("ix_categories_parent_position", "parent_id", "position"),          # sibling menu read
        Index("ix_categories_name_trgm", "name_normalized", postgresql_using="gin",
              postgresql_ops={"name_normalized": "gin_trgm_ops"}, postgresql_where=_LIVE),
        {"schema": CORE_SCHEMA, "comment": "Category tree node (nested-set bounds maintained app-side)."},
    )
    # identity/display: name (+ Computed name_normalized, brands pattern), category, code, title,
    #   sub_title, slug, short_description, description, type
    # tree: taxonomy_id, taxonomy_slug, parent_id, is_root, can_have_children, depth, path,
    #   lft ("_lft"), rgt ("_rgt"), position, display_order, menu_order, show_in_menu
    # SEO: meta_title, meta_description, meta_keywords (JSONB)
    # media keys: icon, color, preview_image, thumbnail, banner
    # flags: is_active, is_blocked, is_featured, is_promoted, is_sponsored, is_partnered, is_visible
    # buckets: extra_metadata (JSONB) — see §5.3
    row_version via RowVersionMixin (inside TenantEntityMixin) — ORM optimistic lock, as approved

class Categorizable(BigIntPKWithUUIDv7Mixin, TenantEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "categorizables"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "taxonomy_id", "category_id"],
                            ["core.categories.tenant_id", "core.categories.taxonomy_id", "core.categories.id"],
                            name="fk_categorizables_category", ondelete="CASCADE"),
        ForeignKeyConstraint(["taxonomy_id", "categorizable_type"],
                            ["core.taxonomy_entity_types.taxonomy_id",
                             "core.taxonomy_entity_types.entity_type_code"],
                            name="fk_categorizables_taxonomy_entity_type"),
        ForeignKeyConstraint(["categorizable_type"], ["core.entity_types.code"],
                            name="fk_categorizables_entity_type", ondelete="RESTRICT"),
        CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
                        name="ck_categorizables_valid_window"),
        CheckConstraint("sort_order >= 0", name="ck_categorizables_sort_order"),
        # one live open-ended assignment per (category, thing)
        Index("uq_categorizables_category_thing", "category_id", "categorizable_type", "categorizable_id",
              unique=True, postgresql_where=text("deleted_at IS NULL AND valid_to IS NULL")),
        # at most one primary per (thing, taxonomy)
        Index("uq_categorizables_one_primary", "taxonomy_id", "categorizable_type", "categorizable_id",
              unique=True, postgresql_where=text("is_primary IS TRUE AND deleted_at IS NULL AND valid_to IS NULL")),
        Index("ix_categorizables_category_sort", "category_id", "sort_order"),
        Index("ix_categorizables_thing", "categorizable_type", "categorizable_id", postgresql_where=_LIVE),
        Index("ix_categorizables_taxonomy_type", "taxonomy_id", "categorizable_type"),
        {"schema": CORE_SCHEMA, "comment": "Polymorphic assignment of a thing to a category, with validity window."},
    )
    category_id / taxonomy_id / categorizable_type / categorizable_id / sort_order /
    is_primary / is_featured / valid_from (server_default now()) / valid_to / extra_metadata
```

**Loader strategy for every relationship (stated, per `<n_plus_one_doctrine>`):**
`Taxonomy.entity_types` → `selectin` (small bounded set, always wanted on Fat
reads); `Taxonomy.categories` → `lazy="raise"` (never accidentally); `Category`
parent/children → not modelled as relationships in v1 (tree reads go through
the nested-set index in `crud.py`); `HasCategoriesMixin.categories` →
`lazy="raise_on_sql"` + explicit `selectinload`; `Document`/`Tag` via their
existing viewonly mixins (always loaded through an explicit `selectinload`, per
their own doctrine).

### 5.2 `enums.py`

```python
CORE_SCHEMA = "core"        # re-exported from entities.enums — no second constant
values(enum_cls)            # imported from entities.enums — no second implementation

class TaxonomyStatus(StrEnum):  DRAFT / ACTIVE / RETIRED          # CHECK on taxonomies.status
class CategoryStatus(StrEnum):  ACTIVE / ARCHIVED                 # CHECK on categories.status (OUR lifecycle)
class CategoryRecordStatus(IntEnum):  DELETED=-1 / NORMAL=0 / ARCHIVED=1
    # the source vocabulary — documentation + inbound mapper translation only
    # (record_status is folded into extra_metadata; see §5.3)
```

Module-local, per the reference's own note. Open vocabularies (category `type`,
entity-type codes) carry no enum — `core.entity_types` is the extension point.

### 5.3 Full column mapping — reference `Category` → target (nothing dropped silently)

| Reference column | Disposition | Target |
|---|---|---|
| `id`, `uuid` | MIXIN | `BigIntPKWithUUIDv7Mixin` |
| `created_at/updated_at` | MIXIN | `TimestampMixin` |
| `created_by_name` | MIXIN (richer) | `AuditMixin` (`created_by` + `created_by_name` + `updated_by` + `updated_by_name`) |
| `row_version` | MIXIN | `RowVersionMixin` (via `TenantEntityMixin`) |
| `deleted_*` | MIXIN | `SoftDeleteFilteredMixin` |
| `owner_type/owner_id` | **REPLACED (D1)** | `TenantScopedMixin.tenant_id/organization_id` + composite org FK |
| `taxonomy_id`, `taxonomy_slug` | KEEP | as approved (composite FK keeps slug honest, `ON UPDATE CASCADE`) |
| `parent_id`, `is_root`, `can_have_children` | KEEP | tree structure + `ck_categories_root_no_parent` |
| `depth`, `path`, `_lft`, `_rgt`, `position` | KEEP | maintained by `tree.py` (D5) |
| `display_order`, `menu_order`, `show_in_menu` | KEEP | UI ordering flags |
| `name` | KEEP | + generated `name_normalized` (brands pattern) for trigram search |
| `category`, `code`, `title`, `sub_title`, `slug` | KEEP | identity/display; `code`/`slug` partial-unique per scope |
| `short_description`, `description`, `type` | KEEP | `type` stays open vocabulary (registry doctrine) |
| `meta_title`, `meta_description`, `meta_keywords` | KEEP | SEO (`meta_keywords` JSONB) |
| `icon`, `color`, `preview_image`, `thumbnail`, `banner` | KEEP | storage keys / display tokens |
| `icon_color`, `icon_bg_color`, `icon_bg_image`, `icon_border_color` | FOLD | `extra_metadata` (JSONB keys as-is) — presentational theming, never queried |
| `image_url`, `thumbnail_url`, `banner_url` | **DROP-derived** | computed at the schema boundary from storage keys (media module doctrine: "URL generation — never stored"). Alternative if a consumer truly needs stored URLs: fold into `extra_metadata` (§14 Q1) |
| `is_active` | KEEP | plain flag (distinct from `DeactivationMixin`, which also comes in the bundle for "reversible not-usable-for-new-work" — the documents precedent) |
| `is_verified` | MIXIN | `StatusMixin.is_verified` |
| `is_blocked`, `is_featured`, `is_promoted`, `is_sponsored`, `is_partnered`, `is_visible` | KEEP | the standard flag set (same names as `ZohoEntityMixin`, explicit here because this table is canonical, not a mirror) |
| `visibility` (legacy bool), `is_bookmarked` | FOLD | `extra_metadata` — legacy/user-scraping state, no query path |
| `record_order`, `record_previous`, `record_next`, `record_status` | FOLD | `extra_metadata` (source-ordering/status verbatim). `CategoryRecordStatus` enum documents the vocabulary; the inbound mapper (if a source import lands) translates it to `CategoryStatus` at the boundary (mapper discipline: source quirks never leak past it) |
| `record_tags` | **SUPERSEDED** | `HasTagsMixin` (multilingual tags module) + fold raw value into `extra_metadata` if an import carries it |
| `record_notes`, `noteable_type`, `noteable_id` | **SUPERSEDED** | activity log (`record_activity`) for notes-on-a-category; a category *as note-owner* is folded into `extra_metadata` until a real notes table exists (§14 Q1) |
| `document_id`, `documents` | **SUPERSEDED** | `HasDocumentsMixin` (polymorphic document links); raw values folded into `extra_metadata` |
| `settings`, `metadata`, `extra_attributes` | FOLD | `extra_metadata` JSONB keys `settings` / `metadata` / `extra_attributes` (avoids the `metadata`-attribute trap by construction) |
| `ondc_category_type` | KEEP (provisional) | nullable Text (P0 in the source). Confirm ONDC is in scope for THPL; if not, fold (§14 Q1) |
| `is_verified`, `status`-family duplicates in `CategoryStats` | DEFER (D6) | phase 2 |

`Taxonomy` mapping: `id/uuid/timestamps/audit/row_version/deleted_*` → mixins;
`slug/name/description/status` KEEP; `owner_type/owner_id` → D1 replacement.
`TaxonomyEntityType`: `taxonomy_id/entity_type_code/allows_multiple` KEEP verbatim.
`Categorizable`: all KEEP except `owner_type/owner_id` → D1 and `metadata` →
`extra_metadata`.

### 5.4 Approved-DDL name → house-name map

| Approved DDL | House |
|---|---|
| `owner_pair` (×3) | dropped with the owner pair (D1) |
| `code_not_blank` / `slug_not_blank` | `ck_categories_code_not_blank` / `ck_categories_slug_not_blank` |
| `status` (×2) | `ck_taxonomies_status` / `ck_categories_status` |
| `depth_nonneg`, `display_order_nonneg`, `menu_order_nonneg`, `record_status`, `root_no_parent`, `no_self_parent`, `nested_set_bounds`, `noteable_pair` | `ck_categories_*` (see §5.1); `record_status`/`noteable_pair` dropped with the folded columns |
| `categories_uuid_unique`, `uq_entity_types_uuid`, … | `ix_<table>_uuid` unique (mixin convention) |
| `categories_parent_id_foreign` | `fk_categories_parent` + `fk_categories_parent_scope` |
| `fk_categories_taxonomy_id`, `fk_categories_taxonomy_id_slug` | `fk_categories_taxonomy`, `fk_categories_taxonomy_slug` |
| `categorizables_category_id_foreign` | `fk_categorizables_category` |
| `categorizable_primary`, `ux_categorizables_primary` | `uq_categorizables_category_thing`, `uq_categorizables_one_primary` |
| `valid_window` | `ck_categorizables_valid_window` |
| functions `guard_taxonomy_owner_change`, `guard_category_scope`, `fill_categorizable_defaults`, `check_categorizable_integrity`, `find_orphan_categorizables` | **kept verbatim** (no collisions; match house verb conventions) |
| triggers `trg_*` / `ctrg_*` | kept verbatim |
| `check_owner_exists` + `ctrg_*_owner` (×3) | **dropped** (D1) |
| `find_orphan_owners` | **dropped** (D1) |
| `assert_entity_exists` | **already exists** — reused as-is |
| `ix_categories_name_trgm` | `ix_categories_name_trgm` (kept) |

---

## 6. PL/pgSQL layer (in the migration, `op.execute`)

### 6.1 Reused (no work)

`core.assert_entity_exists(text, bigint)`, `pg_trgm` GIN ops,
`pg_advisory_xact_lock(hashtextextended(…, 0))` idiom.

### 6.2 New functions (sketches — approved logic, tenant-adapted)

```sql
-- 6.2.1 BEFORE UPDATE OF organization_id ON core.taxonomies — D10
CREATE FUNCTION core.guard_taxonomy_organization_change() RETURNS trigger ... $$
BEGIN
    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
       AND EXISTS (SELECT 1 FROM core.categories c
                    WHERE c.tenant_id = OLD.tenant_id AND c.taxonomy_id = OLD.id) THEN
        RAISE EXCEPTION 'taxonomy % has categories; its organization cannot change', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

-- 6.2.2 BEFORE INSERT OR UPDATE OF parent_id, taxonomy_id, organization_id ON core.categories
CREATE FUNCTION core.guard_category_scope() RETURNS trigger ... $$
-- (a) taxonomy org-scoped ⇒ category org must equal it (IS DISTINCT FROM, NULL-safe);
--     taxonomy shared (organization_id NULL) ⇒ category may be shared or org-scoped;
-- (b) parent.can_have_children must be true;
-- (c) parent shares (tenant_id, organization_id)          [belt-and-braces: fk_categories_parent_scope];
-- (d) on UPDATE: pg_advisory_xact_lock(hashtextextended('category_tree:' || NEW.tenant_id || ':' ||
--     NEW.taxonomy_id, 0)); recursive-CTE ancestor walk; reject if NEW.id appears;
-- ERRCODE 'check_violation' throughout (matches guard_brand_parent).

-- 6.2.3 BEFORE INSERT ON core.categorizables — D11
CREATE FUNCTION core.fill_categorizable_defaults() RETURNS trigger ... $$
-- SELECT c.taxonomy_id, c.organization_id FROM core.categories c WHERE c.id = NEW.category_id;
-- NOT FOUND → RAISE 23503 'category % does not exist';
-- NEW.taxonomy_id := COALESCE(NEW.taxonomy_id, c_tax);
-- NEW.organization_id := COALESCE(NEW.organization_id, c_org);
-- (a caller-supplied taxonomy_id is still pinned to the category's by
--  fk_categorizables_category — the fill is convenience, not a loophole)

-- 6.2.4 AFTER INSERT OR UPDATE OF category_id, taxonomy_id, categorizable_type, categorizable_id,
--        organization_id, valid_from, valid_to, deleted_at ON core.categorizables
--        DEFERRABLE INITIALLY DEFERRED — D9 (steps verbatim from the design)
CREATE FUNCTION core.check_categorizable_integrity() RETURNS trigger ... $$
-- 1. tombstone → RETURN NULL
-- 2. pg_advisory_xact_lock(hashtextextended('categorizables:'||type||':'||id, 0))
-- 3. PERFORM core.assert_entity_exists(NEW.categorizable_type, NEW.categorizable_id)
-- 4. category org-scoped ⇒ NEW.organization_id must match it
-- 5. v_multi := (tet.allows_multiple IS DISTINCT FROM false)
--      FROM core.taxonomy_entity_types tet
--      WHERE tet.taxonomy_id = NEW.taxonomy_id AND tet.entity_type_code = NEW.categorizable_type
-- 6. overlap scan over live rows of the SAME tenant:
--      (x.category_id = NEW.category_id
--       OR (NOT COALESCE(v_multi, true) AND x.taxonomy_id = NEW.taxonomy_id))
--      AND tstzrange(x.valid_from, x.valid_to) && tstzrange(NEW.valid_from, NEW.valid_to)
--    → RAISE 'exclusion_violation' (23P01)

-- 6.2.5 scheduled safety net — D2 (registry loop, exactly find_orphan_entity_aliases' shape)
CREATE FUNCTION core.find_orphan_categorizables()
RETURNS TABLE (link_id bigint, orphan_type text, orphan_id bigint) ... $$
-- FOR r IN SELECT code, target_schema, target_table FROM core.entity_types WHERE deleted_at IS NULL
--   RETURN QUERY EXECUTE format('SELECT z.id, z.categorizable_type, z.categorizable_id
--       FROM core.categorizables z WHERE z.categorizable_type = %L AND z.deleted_at IS NULL
--       AND NOT EXISTS (SELECT 1 FROM %I.%I o WHERE o.id = z.categorizable_id)', ...)
```

### 6.3 Trigger inventory (5 — vs. the reference's 7)

| Table | Trigger | Timing | Function |
|---|---|---|---|
| `taxonomies` | `trg_taxonomies_organization_guard` | BEFORE UPDATE OF organization_id | `guard_taxonomy_organization_change` |
| `categories` | `trg_categories_scope_guard` | BEFORE INSERT/UPDATE OF parent_id, taxonomy_id, organization_id | `guard_category_scope` |
| `categorizables` | `trg_categorizables_fill_defaults` | BEFORE INSERT | `fill_categorizable_defaults` |
| `categorizables` | `ctrg_categorizables_integrity` | AFTER INSERT/UPDATE, DEFERRED | `check_categorizable_integrity` |

(plus nothing on `taxonomy_entity_types` — its FKs are sufficient. The three
owner constraint triggers of the reference are gone with D1.)

Lock keys (all `pg_advisory_xact_lock`, `hashtextextended(…, 0)`): a **three**
keys per tree move — `category_tree:<tenant_id>:<taxonomy_id>` (kept distinct
from `brand_tree:`), `categorizables:<type>:<id>`. Batch assignment writes in a
deterministic (sorted) order to avoid deadlocks — the reference's §12 note
stands.

---

## 7. API surface (Slim/Fat per `<slim_fat_query_doctrine>`)

All responses in the `{code, msg, data, request_id}` envelope; `{ref}` = public
uuid (preferred) or numeric id (brands pattern); writes under `CurrentUser`,
destructive writes under `TenantAdmin`; every write calls `record_activity`.

| Endpoint | DTO | Notes |
|---|---|---|
| `GET /api/taxonomies` | `TaxonomySlimOut[]` | `load_only`; filters: `status`, `scope=shared\|organization`, `q` |
| `POST /api/taxonomies` | `TaxonomyOut` | `organization_id` from context (`require_organization`-style resolver in `service.py`); slug auto-unique per scope |
| `GET /api/taxonomies/{ref}` | `TaxonomyOut` | Fat: + `entity_types` whitelist (`selectinload`) |
| `PATCH /api/taxonomies/{ref}` | `TaxonomyOut` | `row_version` in body → `_check_version` (brands pattern) |
| `DELETE /api/taxonomies/{ref}` | — | soft delete (TenantAdmin, reason required) |
| `PUT /api/taxonomies/{ref}/entity-types` | `TaxonomyEntityTypeOut[]` | replace whitelist (validated against `GET /api/entities/types`) |
| `GET /api/categories` | `CategorySlimOut[]` | filters: `taxonomy_id`, `parent_id`, `is_active`, `q` (trigram); `view=tree` returns the nested shape (one query via `_lft/_rgt` order) |
| `POST /api/categories` | `CategoryOut` | pre-flight: taxonomy exists, scope rules (a)–(c), `can_have_children`; then `tree.recompute` |
| `GET /api/categories/{ref}` | `CategoryOut` | Fat: + `tags`, `documents` (`selectinload`) |
| `PATCH /api/categories/{ref}` | `CategoryOut` | move (parent change) re-runs guards + `tree.recompute` |
| `DELETE /api/categories/{ref}` | — | soft delete; children promoted? **no** — soft-deleting cascades its assignments' soft-delete and blocks children re-parenting until restored (decide: RESTRICT-with-message if live children exist; simplest safe rule, state it in the service docstring) |
| `GET /api/categorizables` | `CategorizableOut[]` | by `category_id` **or** `categorizable_type+categorizable_id`; `valid_at` param (default now) |
| `POST /api/categorizables` | `CategorizableOut` | assign; inherits `taxonomy_id`/org (D11) |
| `POST /api/categorizables/sync` | `CategorizableOut[]` | replace-set for one (thing, taxonomy) — the `tags.sync_entity_tags` pattern (validate all ids in one query, diff, soft-delete removals, insert additions) |
| `DELETE /api/categorizables/{ref}` | — | unassign = soft delete |

**Slim/Fat split (stated):** every list endpoint returns a Slim DTO backed by
`load_only()` in `crud.py`; every detail endpoint returns the Fat DTO with the
relationship loads named above. Relationships on models are `lazy="raise"`;
the router never touches a relationship without an explicit loader option.

**Error translation:** pre-flight 422/409 (`AppError` subclasses —
`CoreRuleError`-style `CategoryRuleError(code="category_rule_violation")`) for
scope/cycle/whitelist/cardinality violations the service can see; SQLSTATE
translation at COMMIT for the deferred checks (D13).

---

## 8. Registry, config, infra touchpoints

| Touchpoint | Change | Phase |
|---|---|---|
| `alembic/env.py` | one import line (§4) | 1 |
| `app/router.py` | three `include_router` lines | 1 |
| `core.entity_types` seed | extend the migration seed: `('brand', …)`, `('manufacturer', …)` exist; add launch set e.g. `('organization','org_management','organizations')`, `('item','public','zoho_items')` (name per the real mirror table), `('vehicle',…)`, `('hub',…)` — **confirm the launch list (§14 Q4)**. `ON CONFLICT (code) DO NOTHING` | 1 |
| `core.taxonomy_entity_types` starter rows | `seed.py` (documents/seed.py pattern: idempotent, never overwrites) + called from `scripts/seed.py` | 1 |
| `tests/conftest.py` `_TEST_TABLES` | `core.categorizables`, `core.categories`, `core.taxonomy_entity_types`, `core.taxonomies` (children first); `core.entity_types` stays untruncated reference data | 2 |
| `app/common/exception/handlers.py` | `IntegrityError`/`StaleDataError` → envelope (D13) | 0 |
| Debezium `table.include.list` | `core.categories,core.taxonomies,core.categorizables` (precedent: `core.brands` is already listed) | 2 opt. |
| `SEARCH_CDC_TOPICS` + `SearchableEntity("categories", …)` | searchable name/slug/code, filterable taxonomy/status — three-step searchable-entity recipe, nothing more | 2 opt. |
| Infra | **none** — no new extension (`pg_trgm`/`uuidv7` already in use; `ltree` only if D5 upgrades), no new port, no new Redis DB, no new dependency | — |

---

## 9. Migration plan

One migration: `categories_taxonomy_module` (down_revision = head). Structure
copies `b1a2c3d4e5f6`: schema exists-guard → tables (shared column-bundle
helpers in the migration file) → indexes → functions (§6) → triggers → seeds.
Downgrade drops triggers, functions, then tables in FK order.

- **Autogenerate caveat (house checklist):** review partial indexes'
  `postgresql_where` and `postgresql_nulls_not_distinct` by hand after
  `./manage.sh makemig` — autogenerate misses them.
- **Everything the ORM cannot express is in this migration** (D8): the five
  functions, four triggers, generated columns (`name_normalized`), GIN trgm
  index. Verify with `alembic upgrade head` on the scratch DB before calling it
  done (testing doctrine).
- **No backfill** — greenfield tables. The only data writes are idempotent
  registry/whitelist seeds.

---

## 10. Service-layer rule table (docstring contract)

| Rule | Pre-flight (clean 422) | Database (authoritative) |
|---|---|---|
| taxonomy slug unique per scope | service `_unique_slug` | `uq_taxonomies_scope_slug` |
| populated taxonomy cannot change organization | service check | `guard_taxonomy_organization_change` |
| category owner matches owned taxonomy | service check | `guard_category_scope` (a) |
| parent can have children | service check | `guard_category_scope` (b) |
| parent shares tenant+org | service check | `fk_categories_parent_scope` + guard (c) |
| parent in same taxonomy | — | `fk_categories_taxonomy` + `fk_categories_parent` |
| no cycles on move | service ancestor walk (`_validate_parent`, brands pattern) | `guard_category_scope` (d) |
| nested-set bounds coherent | `tree.recompute` (the only writer) | `ck_categories_nested_set_bounds` |
| thing exists | service check (optional) | deferred `assert_entity_exists` |
| assignment type whitelisted per taxonomy | service check | `fk_categorizables_taxonomy_entity_type` |
| assignment org matches owned category | service check | `check_categorizable_integrity` step 4 |
| single-valued taxonomy: one category per thing | service check | `check_categorizable_integrity` steps 5–6 |
| no overlapping windows | service check | `check_categorizable_integrity` step 6 |
| one primary per (thing, taxonomy) | service check | `uq_categorizables_one_primary` |
| concurrent edits don't clobber | `_check_version` (row_version) | `RowVersionMixin` |

---

## 11. Tests (per `<testing_doctrine>`)

**1. Hermetic unit tests** (`tests/test_categories_tree.py`, no DB):
`tree.recompute_bounds` (insert/move/delete cases, depth/path correctness,
root flag), slug generation/dedup helper, `CategoryRecordStatus → CategoryStatus`
mapper translation, route-table smoke (`/api/taxonomies`, `/api/categories`,
`/api/categorizables` present in `app.openapi()["paths"]` — extend
`tests/test_health.py` style).

**2. Mocked-boundary tests**: minimal — the module has no external clients. If
phase-2 stats land, mock the refresh job's inputs with `mocker`.

**3. Integration tests** (`tests/test_categories.py`, scratch Postgres, `db`
fixture + `worlds` for two-tenant isolation): one test per row of the §10 rule
table asserting the **database** rejects what the pre-flight would miss (raw
`session.execute` writes where needed to bypass service checks):
- create owned taxonomy + category happy path; commit-time owner validation;
- global category under owned taxonomy → `check_violation`;
- re-parent to descendant → cycle rejection (two concurrent-ish moves in one
  transaction, ordered to prove the advisory lock serializes);
- `can_have_children=false` parent refuses a child;
- assignment fills `taxonomy_id`/org from category (D11);
- non-whitelisted `categorizable_type` → FK violation;
- unregistered `categorizable_type` → FK violation (registry);
- `categorizable_id` of a missing row → `23503` **at commit** (assert the D13
  envelope translation, not a 500);
- single-valued taxonomy second category → `23P01` at commit;
- overlapping windows → `23P01`; non-overlapping windows on the same category →
  allowed; multi-valued taxonomy two categories at once → allowed;
- `uq_categorizables_one_primary` / `uq_categorizables_category_thing` violations;
- **N+1 regression**: query count on `GET /api/categories` and on a
  `selectinload(Model.categories)` Fat read is constant (SQLAlchemy
  `event`-based counter);
- tenancy: GLOBEX cannot read or write ACME's taxonomies (the `worlds` fixture).

`_TEST_TABLES` extended per §8. `alembic upgrade head` on the scratch DB is the
migration's acceptance test.

---

## 12. Phasing

| Phase | Content | Depends on |
|---|---|---|
| **0** | `IntegrityError`/`StaleDataError` handler (D13) | — |
| **1** | migration (tables + functions + triggers + seeds), `model.py`, `enums.py` | 0 |
| **2** | `tree.py` + `crud.py` + `service.py` + `schema.py` + `api.py` + `mixins.py` + router; integration/unit tests; `_TEST_TABLES` | 1 |
| **3** | `seed.py` starter taxonomies; docs updates (§13) | 2 |
| **4** (optional, separately scoped) | CDC + Meilisearch (`SearchableEntity`), `core.category_stats` + refresh task, adopt `HasCategoriesMixin` on `Brand`/`Vehicle`/… | 3 |

Each phase is a shippable PR. Phase 4 items are opt-in per consumer and must
not block the module.

---

## 13. Docs to update (with the PR that lands phase 3)

- `docs/MODULES.md` — the categories module entry (tables, rules, mixin usage).
- `docs/PROJECT_STRUCTURE.md` — `app/modules/categories/` in the tree.
- `docs/tenancy/README.md` — only if §2's mixin catalogue needs a note (no new
  mixins are added to `app/database/`).
- `docs/ZOHO_SYNC_ENGINE.md` — only if phase 4 CDC lands (and
  `deployment/config/debezium/zoho-mirror-connector.json` in the same PR).

---

## 14. Open questions (defaults assumed in the plan, flagged where they bite)

1. **Legacy Zoho/ONDC column family (D4).** The plan folds `record_*`,
   `noteable_*`, `documents`, `document_id`, `visibility`, `is_bookmarked`, the
   four `icon_*` theme columns and the three cached `*_url` columns
   (`extra_metadata` / derived). If any consumer needs them queryable as typed
   columns, say so before the migration is written. `ondc_category_type` is
   kept provisionally — confirm ONDC is in THPL's scope.
2. **"Global" taxonomies (D1).** The plan makes shared = tenant-wide
   (`organization_id IS NULL`), never cross-tenant. If platform-maintained
   template taxonomies readable by all tenants are a launch requirement, that
   is a scoped design addition (a `is_platform_template` flag + a tenant-filter
   carve-out), not a tweak — raise it now.
3. **Are categories ever Zoho-synced?** The plan treats them as canonical
   app-owned master data (like brands). If Zoho category ingestion is wanted,
   the table gains `ZohoMirrorMixin` fields + an outbox direction — a
   meaningful scope change.
4. **Launch whitelist:** which entity types are categorisable at go-live
   (registry seed + `taxonomy_entity_types` rows)? Plan default: `brand`,
   `manufacturer`, `organization`, `item` (mirror-table name to confirm),
   `vehicle`, `hub`.
5. **`entity_types.status` (D3).** Plan keeps soft-delete semantics. Confirm
   "retired type must keep validating historical rows on unrelated updates" is
   not required.
6. **Tree representation (D5).** Plan: `parent_id` + `_lft/_rgt` recompute +
   text `path`. If subtree search by path-prefix becomes a hot query, switch
   `path` to `ltree` in a follow-up (extension already available).
7. **Delete semantics for a category with live children.** Plan: refuse with a
   clean 409 ("re-parent or delete children first"). Alternative: cascade
   subtree soft-delete — pick one.

---

## 15. Definition of done

- [x] Business columns `nullable=True` where doctrine #3 applies (canonical
      table: nullability follows the business rule — NOT NULLs (`tenant_id`,
      `taxonomy_id`, `depth`, …) have defaults or fill-triggers stated in §5/§6).
- [x] `metadata`-attribute trap avoided (`extra_metadata` / `app_metadata`).
- [x] Uniqueness on soft-deletable tables is partial (`deleted_at IS NULL`),
      with `NULLS NOT DISTINCT` where a NULL owner scope participates.
- [x] Every relationship has a stated loader strategy; every list endpoint has
      a Slim DTO backed by `load_only()`.
- [x] No new HTTP client / rate limiter / circuit breaker / search write path /
      config system — Zero touches to the Zoho core or the search pipeline in
      v1.
- [x] Logging via `structlog.get_logger("app.categories")`, structured kwargs.
- [x] Tests per §11 at all three seams; `_TEST_TABLES` extended.
- [x] No new host port, Redis DB, image, extension or PyPI dependency
      introduced.
- [x] No competing architectural skeleton — the module is plain FBA
      (`api → schema → service → crud → model`).
- [x] Docs named in §13 (updated in phase 3, not deferred past it).
