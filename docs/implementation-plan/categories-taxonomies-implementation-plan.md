# Categories & Taxonomies — Implementation Plan

**Document Reference:** `docs/implementation-plan/categories-taxonomies-implementation-plan.md`
**Status:** DRAFT (Architecture Review) — Rev 2 (locked decisions applied)
**Author:** Principal Enterprise Systems Architect
**Date:** September 2026
**Scope:** new `app/modules/categories/` (backend, incl. a Zoho adapter package);
consumes `app/modules/entities/`, `app/modules/zoho/sync/`, `app/modules/sync/`,
`app/database/mixins.py`, `app/database/tenancy.py`, `app/database/soft_delete.py`,
`app/modules/tags/`, `app/modules/documents/`
**Source design:** the approved *Categories — Architecture & Implementation Guide*
(registry-driven taxonomy tree + `categorizables` M:N; `models.py` / `enums.py` /
`sql/categories_module.sql` companion), reconciled against
`docs/architecture-prompts/master-prompt.md`.

---

## 1. Understanding + locked decisions

Build the **Categories and Taxonomies** module: org-scoped **taxonomy trees**
(`core.taxonomies` → `core.categories`), a per-taxonomy **whitelist of
categorisable entity types** (`core.taxonomy_entity_types`) with a cardinality
switch, and a polymorphic, temporally-windowed **assignment table**
(`core.categorizables`), with registry-validated polymorphic references
(`core.entity_types` + `core.assert_entity_exists`). Categories are **Zoho-synced**.

### 1.1 Locked decisions (from the author, Rev 2)

| # | Decision | Consequence in this plan |
|---|---|---|
| L1 | **Keep `image_url`, `thumbnail_url`, `banner_url`, `record_notes`, `settings`, `metadata`, `extra_attributes`, `is_bookmarked`, `icon_*` (all six), `*_url`** as first-class columns. | No folding into `extra_metadata`, no derived-URL dropping. Full-fidelity typed port of the approved `Category` column set (§5.3). They are queryable and appear on the **list** DTO (`CategorySlimOut` + `load_only`). |
| L2 | **Categories are always organization-scoped.** | All four tables are `OrgEntityMixin` (`tenant_id` + `organization_id` NOT NULL). No shared/tenant-wide/cross-tenant state anywhere. The owner-match rules become **composite FKs** (§3 D1). |
| L3 | **Categories will be synced with Zoho.** | `Category` carries `ZohoIdentityMixin` + `ZohoMirrorMixin` (apply-gate machinery, `zoho_raw`, `custom_fields`), and gets a `categories/zoho/` adapter package (spec/fields/hooks) like `organizations/zoho/`. Sync specifics in §6. |
| L4 | **Launch whitelist / registry seeding is out of scope** — the author makes separate changes. | This plan creates the tables and FKs only. No `entity_types` seed rows, no `taxonomy_entity_types` starter rows, no `seed.py`. §12/§14 drop those items. |

Rev-1 open questions resolved by L1–L4: the legacy/Zoho column family is kept
verbatim (not folded); "global" taxonomies do not exist (org-scoped always);
Zoho sync is in scope (not "canonical app-owned"); launch whitelists are owned
by the author. Remaining open questions are in §14 — the critical one is the
**Zoho Categories API doc**, which is not vendored in `docs/zoho-docs-md/`.

---

## 2. Current state — what already exists (and therefore is NOT built)

The source design assumes a greenfield schema. Most of its machinery already
exists here in mature, tested form. **Do not rebuild any of this:**

| Source-design concept | Already implemented here | Evidence |
|---|---|---|
| `core` schema + `pg_trgm` | created by migration `b1a2c3d4e5f6` | `alembic/versions/20260922_0900_…_core_master_data_brands_manufacturers.py` |
| **`core.entity_types` registry** (`code → target_schema.target_table`) | `app.modules.entities.model.EntityType` + `GET /api/entities/types` | `app/modules/entities/model.py` |
| **`core.assert_entity_exists(type, id)`** — dynamic-SQL polymorphic existence check, `STABLE`, `23503` on failure | `CREATE FUNCTION core.assert_entity_exists(text, bigint)` | migration `b1a2c3d4e5f6` |
| Registry-fed deferred constraint trigger proving a polymorphic target exists | `core.check_entity_alias()` + `ctrg_entity_aliases_integrity` (identical shape to the design's `check_owner_exists`) | same migration |
| Registry-fed orphan detector (`find_orphan_*`) | `core.find_orphan_entity_aliases()` | same migration |
| Cycle-guarded self-referential tree + advisory lock + recursive-CTE cycle check | `core.guard_brand_parent()` + `trg_brands_parent_guard` | same migration |
| No-overlapping-validity-windows deferred trigger (`23P01 exclusion_violation`) | `core.check_brand_manufacturer_overlap()` + `ctrg_brand_manufacturers_overlap` | same migration |
| Timestamps / audit (`*_name` denormalised) / optimistic lock / UUID v7 / soft delete / app meta | `TimestampMixin`, `AuditMixin`, `RowVersionMixin`, `BigIntPKWithUUIDv7Mixin`, `SoftDeleteFilteredMixin`, `AppMetaMixin` | `app/database/mixins.py` |
| **Strict org scoping** (L2's model) incl. DB-enforced org existence | `OrgEntityMixin` (`MultiTenantMixin` bundle: `tenant_id` + `organization_id` NOT NULL + composite FK `(tenant_id, organization_id) → org_management.organizations(tenant_id, id)`) + tenancy runtime | `app/database/mixins.py`, `app/database/tenancy.py`; worked example: `core.brands` |
| **Zoho mirror columns + apply gate** (L3's model) | `ZohoIdentityMixin` (`zoho_id`, `public_id`) + `ZohoMirrorMixin` (`zoho_raw`, `zoho_raw_hash`, `zoho_last_modified_time` monotonic fence, `synced_at`, `sync_source`, `sync_version`, `remote_deleted_at`, `custom_fields` HSTORE) + `ZohoPushableMixin` (push state) | `app/modules/zoho/sync/mixins.py` (note: the v1 `ZohoEntityMixin` is **retired** — compose the split mixins) |
| **The sync engine** — strategies FULL/INCREMENTAL, identity matching by `zoho_id` w/ `include_deleted=True` (revives soft-deleted rows), detail fan-out (`detail_dispatch`), nested upserts | `app/modules/zoho/sync/engine.py` + `config.py` (`resolve_module_config`, `FieldMapping`, `SyncContract`) | `docs/ZOHO_SYNC_ENGINE.md` |
| **Anti-corruption / crosswalk layer** — `SyncContract` (`match_on`, `crosswalk`, `history_raw`, `capture_custom_fields`, `owned_fields`, declarative `ReferenceRule`s), `FieldTranslator` + `FieldSpec as F`, per-module `pre_upsert`/`post_upsert` hooks | `app/modules/sync/{contract,translation}.py` | worked example: `organizations/zoho/{spec,fields,hooks}.py` |
| **The adapter-package shape to copy** — `SPEC = ZohoModuleDefinition(config, model, translator, pre_upsert, tags)`, self-registering on import via `_ADAPTER_PACKAGES` autodiscovery | `app/modules/organizations/zoho/spec.py` | `app/modules/zoho/sync/registry.py` |
| One-line "attach X to any model" mixins (viewonly, async-safe) | `HasTagsMixin`, `HasDocumentsMixin`, `HasMediaMixin` | `app/modules/{tags,documents,media}/mixins.py` |
| Catalog + polymorphic pivot with `sort_order` / `is_primary` / partial uniques / validity windows | documents module (`document_types` + `document_links`) | `app/modules/documents/model.py` |
| Assignment write path (validate ids in one query → sync pivot → activity) | `tags.service.sync_tags_for_entity` | `app/modules/tags/` |
| The module template (scope resolver, rule table docstring, Slim/Fat DTOs, uuid refs, activity log, conflict errors, `lazy="raise"` loaders, trigram index) | brands module | `app/modules/brands/` |
| PL/pgSQL placement convention | SQL lives **inside the Alembic migration** (`op.execute`); no `sql/*.sql` sidecar | migration `b1a2c3d4e5f6` |
| Enum vocabulary → CHECK building (`values(MyEnum)`) | `app/modules/entities/enums.py: values()` | documents, brands |
| Error hierarchy, response envelope, activity recorder, structlog conventions | `app/common/exception/errors.py`, `app/common/response/`, `app/modules/activity/recorder.py` | — |
| Test infra — scratch-Postgres `db` fixture, `_TEST_TABLES`, `worlds` two-tenant fixture, **`FakeZohoClient`** | `tests/conftest.py`, `tests/tenancy_fixtures.py`, `tests/zoho_sync/` | — |
| `uuidv7()` PG18, `pg_trgm`, `ltree` availability | deployment Postgres 18 image | master prompt `<deployment_topology>` |

**Net new surface:** four tables (`category_stats` deferred), 3 new PL/pgSQL
functions + 4 triggers (owner machinery deleted — see D1), the tree-bounds
routine, `HasCategoriesMixin`, the FBA layers, and the Zoho adapter package
(§6) — the last blocked only on the Zoho entity's API doc (§14 Q1).

---

## 3. Design deltas vs. the approved DDL

### D1. Ownership: `owner_type/owner_id` → `OrgEntityMixin` (locked L2) — rules become FKs

The reference models "this belongs to org 42" as a polymorphic pair validated
by `check_owner_exists()` + three constraint triggers + `owner_pair` CHECKs on
three tables. With **always-org-scoped** (L2), `OrgEntityMixin` expresses the
same thing with *more* integrity (existence **and** tenant-membership, proven
immediately by the composite FK `(tenant_id, organization_id) →
org_management.organizations(tenant_id, id)`), and — because every row shares
the same scoping shape — the design's cross-row owner-match rules collapse into
**structural composite FKs**:

| Reference rule | Enforced by here |
|---|---|
| category owner must equal an owned taxonomy's owner (guard (a)) | `fk_categories_taxonomy_scope`: `(tenant_id, organization_id, taxonomy_id) → taxonomies(tenant_id, organization_id, id)` |
| parent must share the child's owner (guard (c)) | `fk_categories_parent_scope`: `(tenant_id, organization_id, parent_id) → categories(tenant_id, organization_id, id)` |
| assignment of an owned category carries that owner (integrity step 4) | `fk_categorizables_category_scope`: `(tenant_id, organization_id, category_id) → categories(tenant_id, organization_id, id)` |
| `owner_type` registered (FK to registry) | not applicable — `organization_id` is a real FK |
| `owner_id` exists (`check_owner_exists`, ×3 constraint triggers) | the composite org FK on every table |
| `find_orphan_owners()` | impossible by construction — dropped |
| populated taxonomy cannot change owner | kept as `guard_taxonomy_organization_change()` for the clean error; the composite FKs above are the hard backstop |

Net: **3 constraint triggers, 1 function, 3 CHECKs and the NULL-scope
complexity (`NULLS NOT DISTINCT`, "global" semantics) all disappear.**

### D2. The categorisable side keeps the registry — reusing the one we have

`categorizable_type`/`categorizable_id` is genuinely polymorphic and gets the
reference's mechanism, served by existing infrastructure: `categorizable_type`
is a **real FK to `core.entity_types.code`** (like `EntityAlias.entity_type`),
`categorizable_id` is proven at COMMIT by a deferred constraint trigger calling
the existing `core.assert_entity_exists()` — byte-for-byte the pattern
`core.check_entity_alias()` runs in production.

### D3. `core.entity_types` needs **no change**

Ours resolves registry rows with `deleted_at IS NULL` (the reference adds
`status` instead). Retiring = soft-deleting the registry row: new writes fail
`23503`, existing rows stay valid (triggers only fire on the validated
columns). FK `ondelete=RESTRICT` prevents hard deletes. (Registry population is
the author's separate change — L4.)

### D4. Category columns: full-fidelity typed port (locked L1)

The approved `Category` column set is ported **verbatim as typed columns** —
including `image_url`/`thumbnail_url`/`banner_url` (stored display caches),
`record_notes`, `settings`, `metadata`, `extra_attributes` (JSONB, queryable),
`is_bookmarked`, and the full `icon_*` family. Nothing is folded, nothing is
derived away. Only two mechanical transforms: the `metadata` attribute trap
(DB column `metadata`, Python attribute `metadata_`), and mixin substitution
where a bundle already provides the identical column (§5.3).

*Nullability note (doctrine #3 vs. the approved DDL):* doctrine #3 exists so a
thin Zoho payload can never fail ingestion on a NOT NULL it cannot fill. Every
approved NOT NULL carries a `server_default` (`depth 0`, `position 0`, flags,
`preview_image 'default.png'`, …), so an omitted payload field falls to the
default instead of violating — the approved nullability is kept as-is, and the
inbound mapper simply never writes explicit NULLs over defaults.

### D5. Zoho sync (locked L3) — new workstream, organizations-shaped

`Category` composes `ZohoIdentityMixin` + `ZohoMirrorMixin` (+ the Zoho-owned-
field edit policy), and a `categories/zoho/` adapter package drives the engine.
Full plan in **§6**. The approved DDL's column set was a Zoho record port to
begin with, so the typed columns map onto a `FIELDS` field-map with no
surprises; `zoho_raw` keeps the full document (doctrine #4) alongside them.

### D6. Tree structure: `parent_id` + `_lft/_rgt` + `depth` + `path`, maintained app-side

Keep the approved columns. Maintenance: **one routine owns the bounds** —
`app/modules/categories/tree.py`, pure functions (`recompute_bounds`,
`ancestors_of`, `subtree_of`) so the algorithm is hermetically unit-testable.
The service recomputes `_lft/_rgt/depth/path` for the whole taxonomy in the
same transaction while holding the per-taxonomy advisory lock
(`pg_advisory_xact_lock(hashtextextended('category_tree:'||tenant_id||':'||taxonomy_id, 0))`).
Category trees are small; a full recompute under an exclusive per-tree lock is
provably correct vs. incremental bound shifts. The Zoho sync path recomputes
via the module's `post_upsert` hook (idempotent per affected taxonomy).
`path` stays a text breadcrumb; `ltree` is the upgrade path if prefix
subtree queries ever become hot (§14 Q4).

### D7. `core.category_stats` — deferred

Inferred even in the reference, and its counters count categorizables that are
not in use at launch. Phase 2 (§12) adds the exact minimal shape
(`category_id` 1:1, `items_count`, `views_count`, `has_active_items`,
`stats_as_of`) + a refresh task.

### D8. Naming: house prefixes for constraints, verbatim names for functions

Function/trigger names are kept verbatim (they fit the house
`guard_*`/`check_*`/`find_orphan_*` convention); constraints/indexes use house
prefixes so `core` stays internally consistent. Full map in §5.4.

### D9. SQL placement: inside the Alembic migration

No `sql/categories_module.sql` sidecar. Functions/triggers go in the one
migration that creates the tables (the `b1a2c3d4e5f6` pattern), downgrade drops
them in reverse order. The reference's §4 DB-role grants do not apply (this
platform's registry protection is: `entity_types` is read-only through the API).

### D10. `check_categorizable_integrity` — kept, minus the owner step

Steps 1–3, 5–6 of the reference survive (tombstone skip, per-thing advisory
lock, `assert_entity_exists`, cardinality lookup, `tstzrange` overlap scan now
tenant-scoped, `23P01` on failure). Step 4 (owner match) is gone — D1's
composite FK owns it. This is the design's genuinely valuable temporal guard
and it mirrors the proven `check_brand_manufacturer_overlap()`.

### D11. `fill_categorizable_defaults` — slims to one line of work

BEFORE INSERT: derive `taxonomy_id` from the category (the only NOT NULL
without a natural default). Scope columns are stamped by the tenancy runtime
and pinned by the composite scope FKs — no inheritance logic needed.

### D12. New: `HasCategoriesMixin`

One-line mixin like `HasTagsMixin`/`HasDocumentsMixin`/`HasMediaMixin`:
viewonly (async-safety rule), `lazy="raise_on_sql"` (the N+1 firewall), join
filtered to live + currently-valid assignments, ordered by
`Categorizable.sort_order`, loaded via explicit `selectinload(Model.categories)`.

### D13. Cross-cutting: translate deferred-trigger failures at COMMIT

Deferred triggers raise at the `session.commit()` inside `get_db`
(`app/database/db.py`), which today falls through to the generic 500 handler.
Add one shared handler in `app/common/exception/handlers.py`: `IntegrityError`
→ envelope mapped by SQLSTATE (`23505`→409, `23503`→422, `23514`→422,
`23P01`→409). Services pre-flight the common cases for clean messages (brands
pattern); the DB stays authoritative.

---

## 4. Module / file plan (FBA layering)

```
app/modules/categories/
├── __init__.py
├── model.py       # Taxonomy, TaxonomyEntityType, Category (Zoho-synced), Categorizable
├── enums.py       # TaxonomyStatus, CategoryStatus, CategoryRecordStatus; values()
├── mixins.py      # HasCategoriesMixin
├── tree.py        # PURE nested-set/path/depth recompute (unit-tested, no I/O)
├── crud.py        # all SQL; load_only Slim queries; no business rules
├── service.py     # rules table in docstring; pre-flight; Zoho-owned-field policy; activity log
├── schema.py      # Slim/Fat Out DTOs + Create/Update DTOs (row_version in updates)
├── api.py         # taxonomies_router, categories_router, categorizables_router
└── zoho/
    ├── __init__.py
    ├── spec.py    # resolve_module_config(...) + SyncContract + SPEC = ZohoModuleDefinition(...)
    ├── fields.py  # FIELDS: list[F] — the F(external, local, codec, direction) map
    └── hooks.py   # pre_upsert (taxonomy placement, code fallbacks), post_upsert (tree recompute)
```

Registration checklist:

1. `alembic/env.py`: `from app.modules.categories import model as _categories_model  # noqa: F401`
2. `app/router.py`: `/api/taxonomies`, `/api/categories`, `/api/categorizables`
   (multi-router module precedent: `geo`).
3. `app/modules/zoho/sync/registry.py`: add `"app.modules.categories.zoho"` to
   `_ADAPTER_PACKAGES`.
4. `tests/conftest.py` `_TEST_TABLES` (children before parents, §9).
5. Debezium / search wiring: phase-2 option (§8).

---

## 5. Schema

### 5.1 Target model shape (sketch)

```python
_LIVE = text("deleted_at IS NULL")

class Taxonomy(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "taxonomies"
    __table_args__ = (
        UniqueConstraint("id", "slug", name="uq_taxonomies_id_slug"),     # FK target for taxonomy_slug
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_taxonomies_scope_id"),
        CheckConstraint(f"status IN ({values(TaxonomyStatus)})", name="ck_taxonomies_status"),
        CheckConstraint("btrim(slug) <> ''", name="ck_taxonomies_slug_not_blank"),
        Index("uq_taxonomies_scope_slug", "tenant_id", "organization_id", "slug",
              unique=True, postgresql_where=_LIVE),                      # org NOT NULL: no NULLS handling
        {"schema": CORE_SCHEMA, "comment": "Named category tree, organization-scoped."},
    )
    slug / name / description ...
    status: Mapped[str]   # redeclared over StatusMixin: server_default 'draft', CHECK TaxonomyStatus
    entity_types: Mapped[list["TaxonomyEntityType"]] = relationship(lazy="selectin", ...)

class TaxonomyEntityType(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "taxonomy_entity_types"
    # (tenant_id, organization_id, taxonomy_id) → taxonomies(tenant_id, organization_id, id)
    # entity_type_code FK → core.entity_types.code (ondelete RESTRICT)
    # allows_multiple: bool | None      # NULL = multi-valued (permissive), false = single-valued
    # UNIQUE (taxonomy_id, entity_type_code) WHERE deleted_at IS NULL

class Category(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, DeactivationMixin,
    ZohoIdentityMixin, ZohoMirrorMixin,           # L3 — zoho_id/public_id + apply-gate columns
    SoftDeleteFilteredMixin, HasTagsMixin, HasDocumentsMixin, Base,
):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("taxonomy_id", "id", name="uq_categories_taxonomy_id_id"),
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_categories_scope_id"),
        ForeignKeyConstraint(["tenant_id", "organization_id", "taxonomy_id"],
                            ["core.taxonomies.tenant_id", "core.taxonomies.organization_id",
                             "core.taxonomies.id"],
                            name="fk_categories_taxonomy_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["taxonomy_id", "taxonomy_slug"],
                            ["core.taxonomies.id", "core.taxonomies.slug"],
                            name="fk_categories_taxonomy_slug", onupdate="CASCADE"),
        ForeignKeyConstraint(["taxonomy_id", "parent_id"],
                            ["core.categories.taxonomy_id", "core.categories.id"],
                            name="fk_categories_parent", ondelete="SET NULL (parent_id)"),
        ForeignKeyConstraint(["tenant_id", "organization_id", "parent_id"],
                            ["core.categories.tenant_id", "core.categories.organization_id",
                             "core.categories.id"],
                            name="fk_categories_parent_scope", ondelete="SET NULL (parent_id)"),
        CheckConstraint("NOT (is_root AND parent_id IS NOT NULL)", name="ck_categories_root_no_parent"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_categories_no_self_parent"),
        CheckConstraint("_rgt >= _lft", name="ck_categories_nested_set_bounds"),
        CheckConstraint("depth >= 0", name="ck_categories_depth_nonneg"),
        CheckConstraint("record_status IN (-1, 0, 1)", name="ck_categories_record_status"),
        CheckConstraint("position >= 0", name="ck_categories_position_nonneg"),
        CheckConstraint("display_order >= 0", name="ck_categories_display_order_nonneg"),
        CheckConstraint("menu_order >= 0", name="ck_categories_menu_order_nonneg"),
        CheckConstraint("num_nulls(noteable_type, noteable_id) IN (0, 2)", name="ck_categories_noteable_pair"),
        CheckConstraint("code IS NULL OR btrim(code) <> ''", name="ck_categories_code_not_blank"),
        CheckConstraint("slug IS NULL OR btrim(slug) <> ''", name="ck_categories_slug_not_blank"),
        # Zoho identity: one live row per Zoho record (house checklist item)
        Index("uq_categories_zoho_id_live", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("uq_categories_scope_code", "tenant_id", "organization_id", "taxonomy_id", "code",
              unique=True, postgresql_where=text("code IS NOT NULL AND deleted_at IS NULL")),
        Index("uq_categories_scope_slug", "tenant_id", "organization_id", "taxonomy_id", "slug",
              unique=True, postgresql_where=text("slug IS NOT NULL AND deleted_at IS NULL")),
        Index("ix_categories_scope_lft_rgt", "tenant_id", "organization_id", "taxonomy_id", "_lft", "_rgt",
              postgresql_where=_LIVE),
        Index("ix_categories_parent_position", "parent_id", "position"),
        Index("ix_categories_is_active", "is_active"),                    # legacy name kept (approved DDL)
        Index("ix_categories_name_trgm", "name_normalized", postgresql_using="gin",
              postgresql_ops={"name_normalized": "gin_trgm_ops"}, postgresql_where=_LIVE),
        {"schema": CORE_SCHEMA, "comment": "Category tree node (nested-set bounds maintained app-side); Zoho-synced."},
    )
    # FULL approved column set, typed — see the complete mapping in §5.3:
    #   identity/display: name (+ Computed name_normalized), category, code, title, sub_title,
    #     slug, short_description, description, type, ondc_category_type
    #   tree: taxonomy_id, taxonomy_slug, parent_id, is_root, can_have_children, depth, path,
    #     lft ("_lft"), rgt ("_rgt"), position, display_order, menu_order, show_in_menu
    #   record_*: record_order, record_previous, record_next, record_status, record_tags (JSONB),
    #     record_notes (JSONB), noteable_type, noteable_id, document_id, documents (JSONB)
    #   SEO: meta_title, meta_description, meta_keywords (JSONB)
    #   media/display: icon, color, icon_color, icon_bg_color, icon_bg_image, icon_border_color,
    #     preview_image, thumbnail, banner, image_url, thumbnail_url, banner_url
    #   flags: is_active, is_verified (StatusMixin), is_blocked, is_featured, is_promoted,
    #     is_sponsored, is_partnered, is_visible, visibility, is_bookmarked
    #   buckets: settings (JSONB), metadata_ ("metadata", JSONB), extra_attributes (JSONB)

class Categorizable(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "categorizables"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "organization_id", "taxonomy_id", "category_id"],
                            ["core.categories.tenant_id", "core.categories.organization_id",
                             "core.categories.taxonomy_id", "core.categories.id"],
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
    is_primary / is_featured / valid_from (server_default now()) / valid_to / metadata_ ("metadata", JSONB)
```

(The single four-column `fk_categorizables_category` replaces the reference's
two-FK dance: it pins the assignment to the category's **scope and taxonomy**
at once. `categories` therefore needs the two unique keys shown.)

**Loader strategy for every relationship (stated):** `Taxonomy.entity_types` →
`selectin`; `Taxonomy.categories` → `lazy="raise"` (tree reads go through
`crud.py` and the nested-set index); `HasCategoriesMixin.categories` →
`lazy="raise_on_sql"` + explicit `selectinload`; `Tag`/`Document` via their
existing viewonly mixins (explicit `selectinload`). No relationship on
`Categorizable` back to the polymorphic target — it cannot have one.

### 5.2 `enums.py`

```python
CORE_SCHEMA = "core"        # re-exported from entities.enums — no second constant
values(enum_cls)            # imported from entities.enums

class TaxonomyStatus(StrEnum):  DRAFT / ACTIVE / RETIRED      # CHECK on taxonomies.status
class CategoryStatus(StrEnum):  ACTIVE / ARCHIVED             # OUR lifecycle (StatusMixin.status on Category)
class CategoryRecordStatus(IntEnum):  DELETED=-1 / NORMAL=0 / ARCHIVED=1
    # the source vocabulary — CHECK on categories.record_status (kept typed per L1);
    # the inbound Zoho mapper may translate it to CategoryStatus at the boundary
```

### 5.3 Full column mapping — reference `Category` → target (locked L1: nothing dropped)

| Reference column | Disposition | Target |
|---|---|---|
| `id`, `uuid` | MIXIN | `BigIntPKWithUUIDv7Mixin` |
| `created_at/updated_at` | MIXIN | `TimestampMixin` |
| `created_by_name` | MIXIN (richer) | `AuditMixin` (`created_by`/`created_by_name`/`updated_by`/`updated_by_name`) |
| `row_version` | MIXIN | `RowVersionMixin` |
| `deleted_*` | MIXIN | `SoftDeleteFilteredMixin` |
| `owner_type/owner_id` | **REPLACED (D1)** | `OrgEntityMixin.tenant_id/organization_id` (NOT NULL) + composite FKs |
| *(new)* `zoho_id`, `public_id`, `zoho_raw`, `zoho_raw_hash`, `zoho_raw_synced_at`, `zoho_last_modified_time`, `synced_at`, `sync_source`, `sync_version`, `remote_deleted_at`, `custom_fields` | **ADDED (D5)** | `ZohoIdentityMixin` + `ZohoMirrorMixin` |
| `taxonomy_id`, `taxonomy_slug` | KEEP | composite FKs (scope + slug-cascade) |
| `parent_id`, `is_root`, `can_have_children` | KEEP | tree structure + CHECKs |
| `depth`, `path`, `_lft`, `_rgt`, `position` | KEEP | maintained by `tree.py` |
| `display_order`, `menu_order`, `show_in_menu` | KEEP | UI ordering |
| `name` | KEEP | + generated `name_normalized` (brands pattern) for trigram search |
| `category`, `code`, `title`, `sub_title`, `slug` | KEEP | identity/display; `code`/`slug` partial-unique per scope |
| `short_description`, `description`, `type`, `ondc_category_type` | KEEP | as approved |
| `record_order`, `record_previous`, `record_next`, `record_status` | KEEP | as approved (`record_status` smallint + CHECK) |
| `record_tags`, `record_notes` | KEEP | JSONB typed columns (queryable via `@>`/`->>`) |
| `noteable_type`, `noteable_id` | KEEP | polymorphic pair + `noteable_pair` CHECK |
| `document_id`, `documents` | KEEP | as approved (`documents` JSONB) |
| `meta_title`, `meta_description`, `meta_keywords` | KEEP | SEO |
| `icon`, `color`, `icon_color`, `icon_bg_color`, `icon_bg_image`, `icon_border_color` | KEEP | all six, typed |
| `preview_image`, `thumbnail`, `banner` | KEEP | storage keys |
| `image_url`, `thumbnail_url`, `banner_url` | KEEP | stored display caches, typed (locked L1 — explicit deviation from the media module's derive-URL doctrine, recorded here as a deliberate decision) |
| `is_active`, `is_blocked`, `is_featured`, `is_promoted`, `is_sponsored`, `is_partnered`, `is_visible`, `visibility`, `is_bookmarked` | KEEP | typed flags; `ix_categories_is_active` kept |
| `is_verified` | MIXIN | `StatusMixin.is_verified` |
| `settings`, `extra_attributes` | KEEP | JSONB typed columns |
| `metadata` | KEEP | DB column `metadata`, Python attribute `metadata_` (the SQLAlchemy trap) |

`Taxonomy`: `slug/name/description/status` KEEP; identity/audit bundles via
mixins. `TaxonomyEntityType`: `taxonomy_id/entity_type_code/allows_multiple`
KEEP verbatim. `Categorizable`: all KEEP except `owner_type/owner_id` → D1 and
`metadata` → attribute `metadata_`.

### 5.4 Approved-DDL name → house-name map

| Approved DDL | House |
|---|---|
| `owner_pair` (×3) | dropped with the owner pair (D1) |
| `code_not_blank` / `slug_not_blank` | `ck_categories_code_not_blank` / `ck_categories_slug_not_blank` (+ taxonomy equivalents) |
| `status` (×2) | `ck_taxonomies_status` / `ck_categories_status` |
| `record_status`, `noteable_pair`, `depth_nonneg`, `root_no_parent`, `no_self_parent`, `nested_set_bounds`, `display_order_nonneg`, `menu_order_nonneg` | `ck_categories_*` |
| `categories_parent_id_foreign` | `fk_categories_parent` + `fk_categories_parent_scope` |
| `fk_categories_taxonomy_id`, `fk_categories_taxonomy_id_slug` | `fk_categories_taxonomy_scope`, `fk_categories_taxonomy_slug` |
| `categorizables_category_id_foreign` | `fk_categorizables_category` (4-column, scope+taxonomy pinning) |
| `categorizable_primary`, `ux_categorizables_primary` | `uq_categorizables_category_thing`, `uq_categorizables_one_primary` |
| `valid_window` | `ck_categorizables_valid_window` |
| functions `guard_taxonomy_owner_change`, `guard_category_scope`, `fill_categorizable_defaults`, `check_categorizable_integrity`, `find_orphan_categorizables` | kept verbatim (`guard_taxonomy_owner_change` renamed `guard_taxonomy_organization_change` for accuracy) |
| triggers `trg_*`/`ctrg_*` | kept verbatim |
| `check_owner_exists` + `ctrg_*_owner` (×3), `find_orphan_owners` | dropped (D1) |
| `assert_entity_exists` | **already exists** — reused as-is |
| `ix_categories_name_trgm`, `categories_is_active_index`, `categories_parent_id_position_index` | kept names |

---

## 6. Zoho sync workstream (locked L3)

Shape: **copy `organizations/zoho/`** — the house worked example. Composition on
the model is `ZohoIdentityMixin + ZohoMirrorMixin` (pulled); add
`ZohoPushableMixin` only if the direction includes push (§14 Q1). The apply
gate, crosswalk (`sync.sync_records`/`sync_payloads`/`pending_references`),
history (`history_raw=True`) and custom-field capture all come from the engine
and `SyncContract` — no new machinery.

### 6.1 `categories/zoho/spec.py`

```python
CATEGORIES_CONFIG = resolve_module_config(
    module="categories",
    endpoint=<FROM THE ZOHO API DOC — §14 Q1>,
    zoho_id_attr=<per the doc>,
    strategy=<FULL | INCREMENTAL — per the doc's last_modified_time support>,
    direction=SyncDirection.INBOUND,          # or BIDIRECTIONAL — §14 Q1
    detail_required=<per the doc's list-row thinness>,
    field_map=FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table="core.categories",
        match_on=("zoho_id",),                # the sync-engine identity rule
        crosswalk=True, history_raw=True, capture_custom_fields=True,
        owned_fields=CATEGORIES_ZHO_OWNED,    # derived from FIELDS (translator.readable)
        references=(...),                     # e.g. parent category via crosswalk — see §14 Q2
    ),
)
SPEC = ZohoModuleDefinition(config=CATEGORIES_CONFIG, model=Category,
                            translator=..., pre_upsert=..., post_upsert=..., tags=["core", "catalog"])
```

`sync_interval_minutes`, `wait_between_calls`, `modified_since_param`,
`sort_column`, `paginated`, `index_then_detail` all follow the entity's API doc
— **do not invent them** (guardrail).

### 6.2 `categories/zoho/fields.py`

`FIELDS: list[F]` mapping the approved column set 1:1 onto the payload fields
(`F(external="name", local="name", codec="str", direction=IN)`, JSON buckets
with `codec="json"`/nested rules per `NestedEntityRule` if the payload nests
them). Direction annotations declare ownership explicitly (the organizations
pattern: a structurally `IN`-only module has an empty outbound payload instead
of a wrong one). Zoho-owned fields are derived, never hand-listed
(`ZOHO_OWNED_CATEGORIES = frozenset(translator.readable)`).

### 6.3 `categories/zoho/hooks.py`

- `pre_upsert(payload, values)`: place the row in its taxonomy (§14 Q2 — a
  designated per-organization Zoho taxonomy resolved by code/slug), `code`/`slug`
  fallbacks, `name_normalized` inputs.
- `post_upsert(row, payload)` (async, after flush — the registry's contract):
  schedule/execute `tree.recompute` for the affected taxonomy (idempotent).
- API policy (in `service.py`, mirrored from organizations): on a linked row
  (`zoho_id IS NOT NULL`), local edits to `ZOHO_OWNED_CATEGORIES` fields are
  refused with a clean 422 naming the sync; structural fields (taxonomy,
  parent, tree position, display flags) remain ours.

### 6.4 Outbound (only if push is chosen)

House rule: every Zoho-bound write runs through the **transactional outbox**
(`sync/outbox.py`) — local write + `zoho_queue_logs` journal in the same DB
transaction, `push_outbound` executes create/update/delete and backfills
`zoho_id`. With `ZohoPushableMixin` the row carries `sync_state`
(`local_only → pending → synced | conflict | failed`). If the module is
INBOUND-only (the organizations precedent), declare `direction=IN` and skip
this entirely.

---

## 7. PL/pgSQL layer (in the migration, `op.execute`)

**Reused:** `core.assert_entity_exists(text, bigint)`, the advisory-lock idiom,
`pg_trgm` GIN.

**New (3 functions + 4 triggers — vs. the reference's 6 + 7):**

```sql
-- 7.1 BEFORE UPDATE OF organization_id ON core.taxonomies — clean error; the composite
--     scope FKs are the hard backstop.
CREATE FUNCTION core.guard_taxonomy_organization_change() RETURNS trigger ... $$
-- IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
--    AND EXISTS (SELECT 1 FROM core.categories c WHERE c.taxonomy_id = OLD.id) THEN
--    RAISE 'taxonomy % has categories; its organization cannot change' USING ERRCODE='check_violation';

-- 7.2 BEFORE INSERT OR UPDATE OF parent_id, taxonomy_id ON core.categories
CREATE FUNCTION core.guard_category_scope() RETURNS trigger ... $$
-- only the cross-row rules the FKs cannot express:
--   (b) parent.can_have_children must be true;
--   (d) on UPDATE: pg_advisory_xact_lock(hashtextextended('category_tree:'||NEW.tenant_id||':'||NEW.taxonomy_id, 0));
--       recursive-CTE ancestor walk; reject if NEW.id appears (23514/check_violation).
--   ((a) scope-match and (c) parent-scope are now composite FKs — D1)

-- 7.3 BEFORE INSERT ON core.categorizables — D11
CREATE FUNCTION core.fill_categorizable_defaults() RETURNS trigger ... $$
-- SELECT c.taxonomy_id INTO c_tax FROM core.categories c WHERE c.id = NEW.category_id;
-- NOT FOUND → RAISE 23503 'category % does not exist';
-- NEW.taxonomy_id := COALESCE(NEW.taxonomy_id, c_tax);   -- caller value still pinned by the FK

-- 7.4 AFTER INSERT OR UPDATE OF category_id, taxonomy_id, categorizable_type, categorizable_id,
--     valid_from, valid_to, deleted_at ON core.categorizables
--     DEFERRABLE INITIALLY DEFERRED — D10
CREATE FUNCTION core.check_categorizable_integrity() RETURNS trigger ... $$
-- 1. tombstone → RETURN NULL
-- 2. pg_advisory_xact_lock(hashtextextended('categorizables:'||type||':'||id, 0))
-- 3. PERFORM core.assert_entity_exists(NEW.categorizable_type, NEW.categorizable_id)
-- 4. v_multi := (tet.allows_multiple IS DISTINCT FROM false)  -- NULL = permissive
--      FROM core.taxonomy_entity_types tet
--      WHERE tet.taxonomy_id = NEW.taxonomy_id AND tet.entity_type_code = NEW.categorizable_type
-- 5. overlap scan over live rows of the same tenant:
--      (x.category_id = NEW.category_id
--       OR (NOT COALESCE(v_multi, true) AND x.taxonomy_id = NEW.taxonomy_id))
--      AND tstzrange(x.valid_from, x.valid_to) && tstzrange(NEW.valid_from, NEW.valid_to)
--    → RAISE 'exclusion_violation' (23P01)

-- 7.5 scheduled safety net — D2 (registry loop, find_orphan_entity_aliases' shape)
CREATE FUNCTION core.find_orphan_categorizables()
RETURNS TABLE (link_id bigint, orphan_type text, orphan_id bigint) ...
```

**Trigger inventory:**

| Table | Trigger | Timing | Function |
|---|---|---|---|
| `taxonomies` | `trg_taxonomies_organization_guard` | BEFORE UPDATE OF organization_id | `guard_taxonomy_organization_change` |
| `categories` | `trg_categories_scope_guard` | BEFORE INSERT/UPDATE OF parent_id, taxonomy_id | `guard_category_scope` |
| `categorizables` | `trg_categorizables_fill_defaults` | BEFORE INSERT | `fill_categorizable_defaults` |
| `categorizables` | `ctrg_categorizables_integrity` | AFTER INSERT/UPDATE, DEFERRED | `check_categorizable_integrity` |

Lock keys: `category_tree:<tenant_id>:<taxonomy_id>` (guard + tree recompute),
`categorizables:<type>:<id>` (integrity). Batch writes in deterministic
(sorted) order — the reference's deadlock note stands.

---

## 8. API surface (Slim/Fat per `<slim_fat_query_doctrine>`)

Envelope responses; `{ref}` = public uuid (or id); writes under `CurrentUser`,
destructive writes under `TenantAdmin`; every write calls `record_activity`.

| Endpoint | DTO | Notes |
|---|---|---|
| `GET /api/taxonomies` | `TaxonomySlimOut[]` | `load_only`; filters `status`, `q` |
| `POST /api/taxonomies` | `TaxonomyOut` | org from context (`require_organization`-style) |
| `GET /api/taxonomies/{ref}` | `TaxonomyOut` | Fat: + `entity_types` whitelist (`selectinload`) |
| `PATCH /api/taxonomies/{ref}` | `TaxonomyOut` | `row_version` → `_check_version` |
| `DELETE /api/taxonomies/{ref}` | — | soft delete (TenantAdmin, reason) |
| `PUT /api/taxonomies/{ref}/entity-types` | `TaxonomyEntityTypeOut[]` | replace whitelist (validated against `GET /api/entities/types`) |
| `GET /api/categories` | `CategorySlimOut[]` | **Slim carries the full tile/display set (L1):** `image_url`, `thumbnail_url`, `banner_url`, `icon`, `color`, `icon_*`, `preview_image`, `thumbnail`, `banner`, `is_bookmarked`, `is_active`, `is_featured`, `show_in_menu`, `menu_order`, `display_order`, `settings`, `metadata`, `extra_attributes`, `record_notes` — backed by `load_only`. Filters: `taxonomy_id`, `parent_id`, `is_active`, `q` (trigram); `view=tree` (one query via `_lft/_rgt` order) |
| `POST /api/categories` | `CategoryOut` | pre-flight scope/parent rules; `tree.recompute` |
| `GET /api/categories/{ref}` | `CategoryOut` | Fat: + `tags`, `documents` (`selectinload`), `zoho_raw` summary |
| `PATCH /api/categories/{ref}` | `CategoryOut` | move re-runs guards + recompute; Zoho-owned fields refused on linked rows (§6.3) |
| `DELETE /api/categories/{ref}` | — | soft delete; refuse with 409 while live children exist (§14 Q5) |
| `GET /api/categorizables` | `CategorizableOut[]` | by `category_id` **or** `categorizable_type+categorizable_id`; `valid_at` param |
| `POST /api/categorizables` | `CategorizableOut` | assign |
| `POST /api/categorizables/sync` | `CategorizableOut[]` | replace-set per (thing, taxonomy) — the `tags.sync_entity_tags` pattern |
| `DELETE /api/categorizables/{ref}` | — | unassign = soft delete |

JSONB buckets are queryable as typed columns (`@>`, `->>`); add a GIN index per
bucket only when a real filter needs it (declaration-time indexing doctrine
applies to columns the FSA/DLP apps filter on — start with `ix_categories_is_active`).

---

## 9. Registry, config, infra touchpoints

| Touchpoint | Change | Phase |
|---|---|---|
| `alembic/env.py` | one import line | 1 |
| `app/router.py` | three `include_router` lines | 2 |
| `app/modules/zoho/sync/registry.py` | `"app.modules.categories.zoho"` in `_ADAPTER_PACKAGES` | 3 |
| `app/common/exception/handlers.py` | `IntegrityError`/`StaleDataError` → envelope (D13) | 0 |
| `tests/conftest.py` `_TEST_TABLES` | `core.categorizables`, `core.categories`, `core.taxonomy_entity_types`, `core.taxonomies` (children first) | 2 |
| entity_types / taxonomy_entity_types seeds | **none — author's separate change (L4)** | — |
| Debezium `table.include.list` | `core.taxonomies,core.categories,core.categorizables` (precedent: `core.brands`) | 2 opt. |
| `SEARCH_CDC_TOPICS` + `SearchableEntity("categories", …)` | three-step searchable recipe (searchable `name`/`slug`/`code`; filterable `tenant_id`/`organization_id`/`taxonomy_id`/`is_active`) | 2 opt. |
| Infra | **none** — no new extension, port, Redis DB, image or PyPI dependency | — |

---

## 10. Migration plan

One migration `categories_taxonomy_module` (down_revision = head), structured
like `b1a2c3d4e5f6`: tables (shared column-bundle helpers) → indexes →
functions (§7) → triggers → **no seeds (L4)**. Downgrade drops
triggers/functions/tables in reverse order. No backfill (greenfield).

- Autogenerate caveats (house checklist): hand-verify partial indexes'
  `postgresql_where` and the generated `name_normalized` column after
  `./manage.sh makemig`.
- `ZohoIdentityMixin`/`ZohoMirrorMixin` columns are autogenerate-visible
  (models import them); verify `zoho_raw_hash` (LargeBinary) and `custom_fields`
  (HSTORE) survive review.
- Acceptance: `alembic upgrade head` on the scratch DB.

---

## 11. Service-layer rule table (docstring contract)

| Rule | Pre-flight (clean 422) | Database (authoritative) |
|---|---|---|
| taxonomy slug unique per org | `_unique_slug` | `uq_taxonomies_scope_slug` |
| populated taxonomy cannot change organization | service check | `guard_taxonomy_organization_change` + composite FKs |
| category shares taxonomy's scope | — | `fk_categories_taxonomy_scope` |
| parent shares child's scope | — | `fk_categories_parent_scope` |
| parent in same taxonomy | — | `fk_categories_parent` |
| parent can have children | service check | `guard_category_scope` (b) |
| no cycles on move | service ancestor walk (brands `_validate_parent` pattern) | `guard_category_scope` (d) |
| nested-set bounds coherent | `tree.recompute` (the only writer) | `ck_categories_nested_set_bounds` |
| Zoho-owned fields immutable on linked rows | service check (§6.3) | — (inbound sync overwrites anyway) |
| thing exists | service check (optional) | deferred `assert_entity_exists` |
| assignment type whitelisted per taxonomy | service check | `fk_categorizables_taxonomy_entity_type` |
| assignment shares category's scope/taxonomy | service check | `fk_categorizables_category` |
| single-valued taxonomy: one category per thing | service check | `check_categorizable_integrity` 4–5 |
| no overlapping windows | service check | `check_categorizable_integrity` 5 |
| one primary per (thing, taxonomy) | service check | `uq_categorizables_one_primary` |
| concurrent edits don't clobber | `_check_version` | `RowVersionMixin` |

---

## 12. Tests (per `<testing_doctrine>`)

**1. Hermetic unit tests** — `tree.recompute_bounds` (insert/move/delete, depth
and path correctness), slug generation/dedup, `CategoryRecordStatus →
CategoryStatus` translation, Zoho `FIELDS` ↔ model attribute resolution (every
`F.local` exists on `Category` — the registry-test pattern that turns a typo
into a build failure), route-table smoke in the `test_health.py` style.

**2. Mocked-boundary tests** — the Zoho adapter hooks with `mocker`
(`pre_upsert`/`post_upsert` are pure-ish and get direct tests); no external
clients in the FBA layers.

**3. Integration tests** (`tests/test_categories.py` + `tests/zoho_sync/`
extension):

- one test per §11 row asserting the **database** rejects what pre-flight
  misses (raw `session.execute` writes where needed): scope FKs, cycle guard,
  `can_have_children`, whitelist FK, unregistered/missing
  `categorizable_type`/`categorizable_id` (`23503` **at commit** — assert the
  D13 envelope, not a 500), single-valued second category and overlapping
  windows (`23P01` at commit), the two `uq_categorizables_*` uniques,
  `guard_taxonomy_organization_change`;
- **sync-engine minimum coverage** (mandatory for a sync module): mapper field
  extraction (`FakeZohoClient`, never the real API), identity matching — create
  vs. revive-soft-deleted on `zoho_id` re-sync, `zoho_raw` provenance (thin list
  row never overwrites a detail document), post-upsert tree recompute;
- **N+1 regression**: constant query count on `GET /api/categories` and on a
  `selectinload(Model.categories)` Fat read;
- tenancy: GLOBEX cannot read/write ACME's categories (the `worlds` fixture);
- migration acceptance: `alembic upgrade head` on the scratch DB.

`_TEST_TABLES` extended per §9.

---

## 13. Phasing

| Phase | Content | Depends on |
|---|---|---|
| **0** | `IntegrityError`/`StaleDataError` handler (D13) | — |
| **1** | migration (tables + functions + triggers, no seeds), `model.py`, `enums.py` | 0 |
| **2** | `tree.py`, `crud.py`, `service.py`, `schema.py`, `api.py`, `mixins.py`, router, tests, `_TEST_TABLES` | 1 |
| **3** | Zoho adapter (`categories/zoho/` + `_ADAPTER_PACKAGES`) + sync tests + Zoho-owned-field policy | 2 + **the Zoho API doc (§14 Q1)** |
| **4** (optional) | CDC + Meilisearch wiring; `core.category_stats` + refresh task; adopt `HasCategoriesMixin` on consumers | 2 |

Phases 0–2 ship without Zoho (the mirror columns are nullable). Phase 3 is the
only one blocked externally.

---

## 14. Open questions (Rev 2)

1. **The Zoho Categories API doc is not vendored** (`docs/zoho-docs-md/` has no
   categories entity doc). Per the guardrails I will not invent the endpoint,
   `zoho_id` field name, pagination, `last_modified_time` support, or payload
   shape. Needed before phase 3: which Zoho product/module this is (Books
   categories? Inventory item groups? a custom module?), the entity doc, and
   the **direction** (INBOUND like organizations, or BIDIRECTIONAL with
   `ZohoPushableMixin` + outbox). If push: which fields are ours to write.
2. **Taxonomy home for Zoho-imported categories.** Plan default: a designated
   per-organization taxonomy (slug `zoho`, created idempotently by the adapter's
   `pre_upsert`), so imported rows satisfy `fk_categories_taxonomy_scope`.
   Alternatively Zoho's hierarchy maps 1:1 onto parent/child within one
   taxonomy (preferred if the payload has parents — `ReferenceRule` resolves
   them via the crosswalk). Confirm.
3. **Zoho-owned field split** — which category fields Zoho owns vs. locally
   editable (the `owned_fields` policy refuses local edits on linked rows).
   Derived automatically from `FIELDS` once Q1 lands; confirm the intent.
4. **Tree representation** — `parent_id` + `_lft/_rgt` recompute + text `path`
   (plan default). `ltree` upgrade path if prefix-subtree search gets hot.
5. **Delete semantics for a category with live children** — plan: refuse with
   409 until children are re-parented/deleted. Alternative: subtree
   soft-delete. Pick one.
6. **`category_stats`** timing (deferred by default, D7).

---

## 15. Definition of done

- [x] Full-fidelity column port per L1 — every approved column typed and on
      the list DTO; `metadata` trap avoided (`metadata_` attribute).
- [x] All four tables `OrgEntityMixin` (L2); owner machinery deleted in favour
      of composite FKs (D1).
- [x] Zoho identity/mirror columns + `uq_categories_zoho_id_live` partial
      unique on the mirror table (checklist item).
- [x] Uniqueness on soft-deletable tables is partial (`deleted_at IS NULL`).
- [x] Every relationship has a stated loader strategy; every list endpoint has
      a Slim DTO backed by `load_only()`.
- [x] Zoho HTTP only through `zoho_client`/`zoho_sync_client`; sync writes
      journaled (crosswalk/history via `SyncContract`; outbox in the same
      transaction if push is chosen); no new rate limiter / circuit breaker.
- [x] Logging via `structlog.get_logger("app.categories")` / `"app.zoho.categories"`,
      structured kwargs.
- [x] Tests per §12 at all three seams (incl. sync-module minimum coverage);
      `_TEST_TABLES` extended.
- [x] No new host port, Redis DB, image, extension or PyPI dependency.
- [x] No competing architectural skeleton — plain FBA
      (`api → schema → service → crud → model`) + the house adapter-package shape.
- [x] Docs named in §16 (updated with the PRs, not deferred).
- [x] Launch whitelist/registry seeding explicitly out of scope (L4).

---

## 16. Docs to update

- `docs/MODULES.md` — categories module entry (tables, rules, mixin usage).
- `docs/PROJECT_STRUCTURE.md` — `app/modules/categories/` in the tree.
- `docs/ZOHO_SYNC_ENGINE.md` — the categories adapter (with phase 3).
- `docs/PROJECT_STRUCTURE.md`/connector config — only if phase 4 CDC lands
  (`deployment/config/debezium/zoho-mirror-connector.json` in the same PR).
