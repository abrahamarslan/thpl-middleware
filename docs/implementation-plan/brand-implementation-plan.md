# Brands & Manufacturers — Implementation Plan (target-schema reconciliation)

**Document Reference:** `docs/implementation-plan/brand-implementation-plan.md`
**Status:** DRAFT (Architecture Review)
**Author:** Principal Enterprise Systems Architect
**Date:** September 2026
**Scope:** `app/modules/{brands,manufacturers,entities}/`, the `core` schema, migration `b1a2c3d4e5f6`, its downstream consumers (API, search registry, Debezium, tests)
**Source design:** the pasted *Block 1–8* target schema — nullable polymorphic `owner_type`/`owner_id` (NULL = global) FK'd to `core.entity_types`, registry-validated via `check_owner_exists()`, plus `guard_master_owner_change()` / `brand_manufacturer_scope()` / `manufacturer_child_owner_sync()` guards
**Related:** [`categories-taxonomies-implementation-plan.md`](categories-taxonomies-implementation-plan.md) (deferred), [`../MODULES.md`](../MODULES.md), [`../tenancy/README.md`](../tenancy/README.md), [`../geo/README.md`](../geo/README.md), `../architecture-prompts/master-prompt.md`

---

## 0. Verdict — is the new schema implemented?

**Yes, substantially — roughly 90% of Blocks 2–6 already exists** in
`alembic/versions/20260922_0900_b1a2c3d4e5f6_core_master_data_brands_manufacturers.py`
and `app/modules/{brands,manufacturers,entities}/`. That migration's own docstring
(lines 12–26) says it built the reference design *and names the exact deviations*.

There is **one substantive divergence**, and it is deliberate: **ownership/scoping**.

| | Proposed schema (Blocks 1–8) | Implemented today |
|---|---|---|
| Master scope | `(owner_type, owner_id)` nullable; `NULL` = global/shared; `owner_type` FK → `core.entity_types(code)` | `tenant_id` + `organization_id` **NOT NULL** (`OrgEntityMixin`) + `owner_type/owner_id` as the **provenance pair** (`PolymorphicOwnerMixin`, closed `MasterOwnerType` CHECK, **no FK**) |
| Cross-org integrity | deferred `check_owner_exists()` + three scope/sync triggers | composite FKs `(tenant_id, organization_id, x_id)` — proven immediately, no trigger |
| Global rows | `owner_type/owner_id` NULL | not supported; every row is org-scoped (`OrgEntityMixin`) |
| Owner-change guard | `guard_master_owner_change()` | **missing** (the one real gap) |

**Functions (Block 1):** 5 of the 9 named objects already exist —
`assert_entity_exists()`, `check_entity_alias()`, `find_orphan_entity_aliases()`,
`guard_brand_parent()`, `check_brand_manufacturer_overlap()`.
Four do not — `check_owner_exists()`, `guard_master_owner_change()`,
`brand_manufacturer_scope()`, `manufacturer_child_owner_sync()` — but **three of those
four are made unnecessary by the composite FKs**, and the migration/`MODULES.md` say so.
Only `guard_master_owner_change()` is a genuine, closable gap.

**Categories dependency:** none for brands. `assert_entity_exists()` already ships in
migration `b1a2c3d4e5f6` (not the future categories module). `check_owner_exists()` is
only needed by the *non-adopted* owner model. **The brands module is not blocked by
categories.**

**Blocks 7–8:** Block 7 (comments/seed) is reflected via `comment=` on the models and the
`entity_types` seed inside the migration; Block 8's `ALTER TABLE … ADD COLUMN` is **not
applicable** — the tables were created greenfield in this shape, there is no pre-existing
`brands`/`manufacturers` table to migrate.

**Recommendation:** **keep the current architecture** (Option A, §4), close the one gap
(`guard_master_owner_change`, §5 G1), and descope "global/shared masters" to a separately
decided feature (§15 Q1). Adopting the proposed owner model (Option B) is a
platform-wide tenancy change, not a brand-module change, and should not be done silently.

---

## 1. Understanding (what was asked)

The task is to (a) say whether the pasted target schema is already implemented, and
(b) produce a full implementation plan for the brand/manufacturer work, reconciled
against the existing architecture, with categories deferred.

The pasted schema is a **reference design** with a registry-driven polymorphic owner
pair. This repository already adopted that design family — `core.entity_types` is a
registry, `assert_entity_exists()` proves polymorphic targets, deferred constraint
triggers guard aliases and validity windows — but chose **tenancy columns over the
polymorphic owner pair** for scoping, exactly as the categories plan also chose
(its delta D1). This document reconciles the two, states what is done, and specifies
the remaining work.

Open questions are in §15. The only one that changes the schema is whether
"global/shared" masters are a launch requirement (Q1).

---

## 2. Implementation status matrix

### 2.1 Tables and columns

Every business column the target schema names already exists. The deltas are names
and the ownership pair.

| Target object | Status | Evidence / note |
|---|---|---|
| `core.entity_types` (+ seed `brand`,`manufacturer`) | **DONE** | `entities/model.py:49`; migration `b1a2c3d4e5f6` (table + seed lines 629–634) |
| `core.brands` | **DONE** | `brands/model.py:71`; migration lines 165–227 |
| `core.manufacturers` | **DONE** | `manufacturers/model.py:71`; migration lines 230–286 |
| `core.brand_manufacturers` | **DONE** | `brands/model.py:154`; migration lines 289–348 |
| `core.manufacturer_identifiers` | **DONE** | `manufacturers/model.py:139`; migration lines 351–409 |
| `core.entity_aliases` | **DONE** | `entities/model.py:80`; migration lines 412–469 |
| `brands.name_normalized` STORED generated | **DONE** | `brands/model.py:124` |
| `manufacturers.name_normalized` STORED generated | **DONE** | `manufacturers/model.py:115` |
| `manufacturer_identifiers.value_normalized` STORED | **DONE** | `manufacturers/model.py:179` |
| `entity_aliases.alias_normalized` STORED | **DONE** | `entities/model.py:116` |
| `brands.code/kind/parent_id/country_code/description/website_url/logo_storage_key` | **DONE** | `brands/model.py:117–135` |
| `manufacturers.legal_name/code/country_code/website_url/*verified*` | **DONE** | `manufacturers/model.py:111–125` + `VerificationMixin` |
| `brand_manufacturers.kind/is_default/valid_from/valid_to` | **DONE** | `brands/model.py:201–213` |
| `manufacturer_identifiers.kind/value/issuing_authority/issued_on/expires_on` | **DONE** | `manufacturers/model.py:175–185` |
| `entity_aliases.kind/language_code` | **DONE** | `entities/model.py:120–123` |
| `owner_type`/`owner_id` **columns** | **DONE, different semantics** | present on brands/manufacturers (`PolymorphicOwnerMixin`); **NOT NULL + closed CHECK**, not nullable/global; absent on child/link tables |
| `created_by_id` / `updated_by_id` / `deleted_by_id` | **RENAMED** | house names `created_by` / `updated_by` / `deleted_by` (`AuditMixin`, `SoftDeleteMixin`) — keep house |
| `verified_by_id` | **RENAMED** | house name `verified_by` (`VerificationMixin`) — keep house |
| `row_version`, `updated_at`, `created_at`, `uuid` | **DONE** | mixins (`RowVersionMixin`, `TimestampMixin`, `BigIntPKWithUUIDv7Mixin`) |
| `is_verified` | **DONE (richer)** | `StatusMixin` boolean + `VerificationMixin.verification_status` for the tri-state nuance (§3 D3) |
| `brands.slug` / `manufacturers.slug` | **EXTRA — KEEP** | target omits them; current uses them in API, tests, and `search/registry.py` |
| `tenant_id` / `organization_id` | **EXTRA — KEEP** | tenancy isolation; the target omits them, which is the divergence (§4) |
| `deactivation_*`, `app_version`, `app_metadata` | **EXTRA — KEEP** | mixin bundle; not in target, harmless |

### 2.2 Constraints and indexes

| Target object | Status | Evidence |
|---|---|---|
| `uq_brands_uuid` etc. | **DONE** | unique index on `uuid` (mixin) |
| `fk_brands_owner_type` → `entity_types(code)` | **REPLACED** | closed `MasterOwnerType` CHECK instead (`brands/model.py:84`) |
| `fk_brands_parent_id` (self FK) | **DONE, stronger** | composite `(tenant_id, organization_id, parent_id)` FK (`brands/model.py:91`) so a sub-brand cannot cross org |
| `ck_brands_owner_pair` (`num_nulls IN (0,2)`) | **N/A** | owner pair is NOT NULL; not needed |
| `ck_brands_name_not_blank`, `code_not_blank`, `status`, `kind`, `country_code`, `website_url`, `no_self_parent` | **DONE** | `brands/model.py:82–89` |
| `uq_brands_scope_name/code` partial uniques | **DONE** | `brands/model.py:98–101` (scoped by tenant+org; no `NULLS NOT DISTINCT` needed) |
| `ix_brands_owner_scope_name`, `ix_brands_name_trgm`, `ix_brands_parent_id` | **DONE** | `brands/model.py:104–107` |
| `ck_manufacturers_*`, `uq_manufacturers_scope_*`, `ix_manufacturers_*` | **DONE** | `manufacturers/model.py:81–101` |
| `brand_manufacturers` partial uniques (`uq_*_current`, `ux_*_default`) | **DONE** | `brands/model.py:184–192` (scoped by tenant+org, `NULLS NOT DISTINCT`) |
| `manufacturer_identifiers` uniques + lookup + statutory-format CHECK | **DONE** | `manufacturers/model.py:152–169` |
| `entity_aliases` uniques + trigram | **DONE, scoped by tenant** | `entities/model.py:87–104` |
| `ix_*_owner_scope` on child/link tables | **N/A** | no owner pair on children; scope via FK |

### 2.3 Functions and triggers (Block 1)

| Target object | Status | Where / why |
|---|---|---|
| `core.assert_entity_exists(text,bigint)` | **DONE** | migration lines 474–504; `entities/model.py:11` |
| `core.check_entity_alias()` + `ctrg_entity_aliases_integrity` | **DONE** | migration lines 506–521 |
| `core.find_orphan_entity_aliases()` | **DONE** | migration lines 523–543 |
| `core.guard_brand_parent()` + `trg_brands_parent_guard` | **DONE** | migration lines 548–589 (advisory lock, owner-pair check, recursive cycle guard) |
| `core.check_brand_manufacturer_overlap()` + `ctrg_brand_manufacturers_overlap` | **DONE** | migration lines 592–626 |
| `core.check_owner_exists()` | **NOT NEEDED under Option A** | the org composite FK proves owner existence immediately; `owner_type` is a closed vocabulary, not a registry code. Under Option B it belongs to categories (deferred) |
| `core.guard_master_owner_change()` | **GAP** | no guard today (§5 G1) |
| `core.brand_manufacturer_scope()` | **REPLACED** | composite FKs `fk_brand_manufacturers_brand/manufacturer` + service check (`brands/service.py:214–218`) |
| `core.manufacturer_child_owner_sync()` | **REPLACED** | composite FK `fk_manufacturer_identifiers_manufacturer` |
| `trg_brands_owner_change_guard` / `trg_manufacturers_owner_change_guard` | **GAP** | depend on the guard above |
| `ctrg_*_owner` (×3) | **REPLACED** | composite FKs |

### 2.4 Application layers

| Layer | Status |
|---|---|
| `model.py` (3 modules) | **DONE** |
| `enums.py` (`BrandStatus`, `BrandKind`, `BrandManufacturerKind`, `ManufacturerStatus`, `ManufacturerIdentifierKind`, `EntityAliasKind`, `MasterOwnerType`, `values()`) | **DONE** |
| `schema.py` (Slim/Fat Out + Create/Update, `row_version` on updates) | **DONE** |
| `crud.py` (`load_only` Slim, `selectinload` Fat, `lazy="raise"` models) | **DONE** |
| `service.py` (rule tables, activity log, conflict errors, cycle walk) | **DONE** |
| `api.py` (`/api/brands`, `/api/manufacturers`, `/api/entities`) | **DONE** |
| Search registry (`brands`, `manufacturers`) | **DONE** (`search/registry.py:84–99`) |
| Debezium `table.include.list` | **DONE** (`core.brands`, `core.manufacturers`) |
| Tests | **DONE** (`tests/test_core_master.py`) |
| Docs | **DONE** (`MODULES.md`, `PROJECT_STRUCTURE.md`) |

---

## 3. Design deltas

Each delta replaces a hand-rolled mechanism of the reference with an established house
pattern, mirroring what migration `b1a2c3d4e5f6` already did and what the categories plan
does in its own D1–D13.

### D1. Ownership: polymorphic `owner_type/owner_id` → tenancy columns
The single largest delta, **already in force**. The reference models "this brand belongs to
org 42" as `(owner_type='organization', owner_id=42)` validated by a deferred
`check_owner_exists()`. Here it is `organization_id` (FK-proven by the composite FK to
`org_management.organizations(tenant_id, id)`), which proves existence *immediately* and
also proves tenant membership — something the polymorphic pair cannot check at all. The
`owner_type/owner_id` pair survives as **provenance** (a closed `MasterOwnerType`
vocabulary, no FK), set to the owning organization at create
(`brands/service.py:129–134`, `manufacturers/service.py:122–127`).

### D2. Child scope: `*_owner_sync`/`*_scope` triggers → composite FKs
`brand_manufacturer_scope()` and `manufacturer_child_owner_sync()` are replaced by the
composite FKs `(tenant_id, organization_id, x_id)`. A link can never pair a brand and
manufacturer of two organizations, and an identifier can never belong to another org's
manufacturer. The service adds a clean pre-flight 422 for the common case
(`brands/service.py:214–218`) so callers do not see a raw FK error.

### D3. Verification: nullable tri-state `is_verified` → boolean + `verification_status`
The reference's "`is_verified boolean, NULL = unknown" is served by the established pair:
`StatusMixin.is_verified` (NOT NULL, default false — the flag every filter uses) plus
`VerificationMixin.verification_status/method/data/verified_by/verified_at` (the nuance a
boolean cannot carry: `unverified` vs `verified` vs `rejected`). No schema change; use
`verification_status` when "unknown" must be distinguished.

### D4. Naming: `*_id` suffixes and `verified_by_id`
Constraint/index names already follow house prefixes (`ck_*`, `uq_*`, `ix_*`, `fk_*`).
Audit columns keep house names `created_by`/`updated_by`/`deleted_by`, and the verifier is
`verified_by`. The approved-name → house-name map is §2 and is intentionally not renamed
back: renaming would touch every model, service, schema, test, and search attribute for no
behavioural gain.

### D5. `slug` is kept
The target schema omits `slug`; it is load-bearing here (`BrandSlimOut.slug`,
`service._unique_slug`, `test_core_master.py:96`, `search/registry.py:88`). Keep it and
treat "no slug" as a reference-design gap, not a target.

### D6. "Global"/shared masters are not implemented
`OrgEntityMixin` makes `organization_id` NOT NULL. The reference's `NULL` = global is a new
capability, not a missing column. It is a separate product decision (§15 Q1) with a real
tenancy cost (§4).

### D7. SQL placement
All PL/pgSQL lives **inside the Alembic migration** (`op.execute`), downgrade drops
functions/triggers in reverse order. There is no `sql/*.sql` sidecar in this repo. New
functions follow the same rule (§10).

### D8. Comments
House style is `comment=` on the mapped column/table, already present. The reference's
`COMMENT ON …` block is not re-run as a separate migration.

---

## 4. Decision: ownership model (the crux)

### Option A — keep tenancy columns (recommended)
Every master row belongs to one tenant and one organization (`OrgEntityMixin`); the owner
pair stays provenance. Composite FKs keep cross-org pairing impossible.

- **Pros:** tenant isolation is guaranteed and test-enforced
  (`test_every_table_is_entity_ledger_or_an_explained_global`); the tenancy runtime
  auto-filters and auto-stamps; all existing API/search/CDC/tests keep working; **no
  categories dependency**.
- **Cons:** no true cross-tenant global brand; "shared" is only organisation-scoped.

### Option B — adopt the reference's nullable polymorphic owner
`owner_type/owner_id` become nullable (NULL = global), FK to `entity_types`, with a
deferred `check_owner_exists()`; child tables grow an owner pair too.

- **Pros:** matches the pasted schema verbatim; allows platform/global masters and
  non-org owners (`connection`, `system`).
- **Cons / hard conflicts:**
  1. **Breaks tenant isolation.** A row with NULL owner has no `tenant_id`, so it is
     invisible to the tenancy runtime's filter and must join the `GLOBAL_TABLES`
     allow-list with a written reason — a deliberate weakening of the platform's
     non-negotiable isolation (`docs/tenancy/README.md §3`).
  2. **`owner_type` FK → `core.entity_types` is semantically wrong as written.** The seed
     registers `brand`/`manufacturer`, not `organization`/`tenant`. Option B must first
     register owner types (`organization`, `tenant`, `connection`, `system`) in
     `entity_types` and teach `check_owner_exists()` to resolve them.
  3. **`check_owner_exists()` is categories-scoped and deferred.** With categories
     deferred, Option B would block brands — the opposite of the stated goal.
  4. Rewrites six tables, every service, every test, the search registry, and the
     Debezium config.

**Recommendation: Option A.** If cross-tenant global masters are genuinely required, do
not bend the brand module — introduce an explicit, reviewed "platform template master"
feature (a `is_platform_template` flag plus a tenancy-filter carve-out, or a reserved
system organization) as its own scoped design, the way the categories plan defers
cross-tenant taxonomies (its §14 Q2).

---

## 5. Gap-closure plan (the actual remaining work)

### G1. `core.guard_master_owner_change()` + two triggers (the one real gap)
Closes the target schema's `guard_master_owner_change` intent, adapted to Option A.

Nuance worth stating: changing `organization_id` on a referenced master is **already**
blocked by the composite FKs (they have no `ON UPDATE CASCADE`), so the DB rejects it.
The genuine hole is the **owner pair** (`owner_type`/`owner_id`), which is in no FK. The
guard freezes both the owner pair and (belt-and-braces) `organization_id` once anything
references the row.

```sql
-- BEFORE UPDATE OF owner_type, owner_id, organization_id ON core.brands / core.manufacturers
CREATE FUNCTION core.guard_master_owner_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_used boolean;
BEGIN
    IF ROW(NEW.owner_type, NEW.owner_id) IS NOT DISTINCT FROM ROW(OLD.owner_type, OLD.owner_id)
       AND NEW.organization_id IS NOT DISTINCT FROM OLD.organization_id THEN
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'brands' THEN
        v_used := EXISTS (SELECT 1 FROM core.brand_manufacturers l WHERE l.brand_id = OLD.id)
               OR EXISTS (SELECT 1 FROM core.brands c WHERE c.parent_id = OLD.id);
    ELSE
        v_used := EXISTS (SELECT 1 FROM core.brand_manufacturers l WHERE l.manufacturer_id = OLD.id)
               OR EXISTS (SELECT 1 FROM core.manufacturer_identifiers i WHERE i.manufacturer_id = OLD.id);
    END IF;

    IF v_used THEN
        RAISE EXCEPTION '% % is referenced; its owner cannot change', TG_TABLE_NAME, OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
```

Triggers:
`trg_brands_owner_change_guard` and `trg_manufacturers_owner_change_guard`, both
`BEFORE UPDATE OF owner_type, owner_id, organization_id … FOR EACH ROW`.

Also add a `DISTINCT FROM` guard for `tenant_id` (never movable).

### G2. Optional — tenant-shared masters (`organization_id IS NULL`) — DECISION ONLY
If "shared within the tenant" is required but not cross-tenant: switch `Brand` /
`Manufacturer` from `OrgEntityMixin` to `TenantEntityMixin` (nullable `organization_id`),
make the unique indexes `NULLS NOT DISTINCT`, and adjust `link_manufacturer` / identifier
scope checks to allow a NULL org on either side. **Do not start this before §15 Q1 is
answered** — it is a behaviour change, not a gap fill.

### G3. Decide `entity_aliases` scope (document, no code)
The target gives `entity_aliases` an owner pair; today it is `TenantScopedMixin`
(`tenant_id` NOT NULL, `organization_id` nullable). Under Option A this is already the
better shape — a tenant-wide alias is `organization_id IS NULL`. No change; record the
decision.

### G4. Document the reconciliation (no code)
Add a short "Reference design reconciliation" note to `brands/model.py` and
`manufacturers/model.py` docstrings pointing at this document, so the next reader knows
why `check_owner_exists`/scope/sync triggers are absent. `MODULES.md` already carries the
core-master entry; extend it with the owner-change guard once G1 lands.

### G5. Tests for G1
Add the integration tests in §12. If G2 is approved, its own tests.

---

## 6. PL/pgSQL layer (in the migration)

### 6.1 Reused — no work
`core.assert_entity_exists`, `core.check_entity_alias`,
`core.find_orphan_entity_aliases`, `core.guard_brand_parent`,
`core.check_brand_manufacturer_overlap`, `pg_trgm`, the
`pg_advisory_xact_lock(hashtextextended(…, 0))` idiom.

### 6.2 New — only G1
One function, two triggers (§5). `check_owner_exists` is **not** added under Option A.

### 6.3 Deliberately absent — with reasons
`brand_manufacturer_scope`, `manufacturer_child_owner_sync` (composite FKs),
`ctrg_*_owner` (composite FKs), `check_owner_exists` (closed owner vocabulary + org FK).
Record the reasons in the migration docstring and the model docstrings (G4).

---

## 7. Module / file plan

Almost nothing changes structurally. G1 touches two files plus a migration.

```
apps/core-platform/backend/
├── alembic/versions/<new>_core_owner_change_guard.py   # G1: function + 2 triggers
├── app/modules/brands/model.py                          # G4: docstring note
├── app/modules/manufacturers/model.py                   # G4: docstring note
└── tests/test_core_master.py                            # G5: guard tests
```

If G2 is approved it is a larger change: `brands/model.py`, `manufacturers/model.py`,
`brands/service.py`, `manufacturers/service.py`, `entities/model.py` (alias org filter),
the migration, and tests. Scope it separately.

---

## 8. API surface

No new endpoints are required by the target schema; the requested surface already exists.

| Endpoint | Exists | Notes |
|---|---|---|
| `GET/POST /api/brands`, `GET/PATCH/DELETE /api/brands/{ref}` | yes | Slim list / Fat detail; `row_version` → 409; TenantAdmin deletes |
| `GET/POST/DELETE /api/brands/{ref}/manufacturers[/{link_ref}]` | yes | link/unlink with validity window |
| `GET/POST /api/manufacturers`, `…/{ref}` | yes | |
| `GET/POST/DELETE /api/manufacturers/{ref}/identifiers[/{identifier_ref}]` | yes | statutory-format 422 |
| `GET /api/entities/types`, `GET/POST/DELETE /api/entities/aliases` | yes | registry + polymorphic aliases |
| `GET /api/search/brands`, `GET /api/search/manufacturers` | yes | via `search/registry.py` |

**Optional follow-ups (not required, low priority):** a `GET /api/brands/{ref}/aliases`
convenience read (today aliases are queried via `/api/entities/aliases`), and
`GET /api/manufacturers/{ref}/brands` (reverse lookup). Both are thin reads over existing
tables and can be added without schema change.

---

## 9. Registry / config / infra touchpoints

| Touchpoint | State |
|---|---|
| `alembic/env.py` model imports | **DONE** (`entities`, `brands`, `manufacturers`) |
| `app/router.py` includes | **DONE** (`/brands`, `/manufacturers`, `/entities`) |
| `tests/conftest.py` `_TEST_TABLES` | **DONE** (children before parents; `core.entity_types` untruncated) |
| Search registry (`brands`, `manufacturers`) | **DONE** |
| Debezium `table.include.list` | **DONE** (`core.brands`, `core.manufacturers`) |
| New extension / dependency / port / Redis DB / image | **NONE** — `pg_trgm` and `uuidv7()` already in use |
| `pgvector` dedup on names (target schema silent) | **not in scope**; a later Contacts-style feature if wanted (§15 Q3) |

---

## 10. Migration plan

One small additive migration for G1:

- `down_revision = <current head>`; `revision = <new>`;
  name `core_owner_change_guard`.
- `upgrade()`: `CREATE FUNCTION core.guard_master_owner_change()` then the two
  `CREATE TRIGGER`s (mirrors the function/trigger block in `b1a2c3d4e5f6`).
- `downgrade()`: drop the two triggers, then the function, in reverse.
- No table rewrite, no backfill, no index rebuild — cheap and reversible.

If G2 is approved, a separate migration makes `organization_id` nullable on
`core.brands`/`core.manufacturers`, recreates the scope indexes with
`postgresql_nulls_not_distinct=True`, and re-validates the composite FKs' `MATCH SIMPLE`
behaviour (nullable org skips the check, which is correct for a shared row). That migration
is **not** written until Q1 is answered.

---

## 11. Service-layer rule table (docstring contract)

| Rule | Pre-flight (clean 422/409) | Database (authoritative) |
|---|---|---|
| brand/manufacturer belongs to one org | `require_organization` | `OrgEntityMixin` + composite FK |
| one live name / code / slug per org | `_normalize_name`, `find_by_*`, `_unique_slug` | `uq_*_scope_name/code/slug` |
| a sub-brand shares its parent's org | `_validate_parent` | `fk_brands_parent` |
| a brand cannot be its own ancestor | `_validate_parent` walk | `guard_brand_parent` |
| a link never spans two orgs | `link_manufacturer` check | composite FKs |
| no overlapping windows | `current_link` check | `check_brand_manufacturer_overlap` |
| identifier format | `_validate_format` | `ck_manufacturer_identifiers_format` |
| alias target exists | registry lookup (`entities/service.py:49`) | `check_entity_alias` |
| **owner/org frozen once referenced** | **new:** service never changes it | **new:** `guard_master_owner_change` |
| concurrent edits don't clobber | `_check_version` | `RowVersionMixin` |

---

## 12. Tests

Existing coverage in `tests/test_core_master.py` is good: schema shape, generated columns,
partial uniqueness, closed vocabularies, registry attributes, CRUD, cycle rejection, stale
`row_version` 409, tenancy isolation, link duplicate/overlap, statutory formats, alias
target existence, and the installed guard functions/triggers.

**Add for G1 (integration, scratch Postgres, `worlds` fixture):**

1. Update `test_the_guard_functions_and_triggers_are_installed` to include
   `guard_master_owner_change`, `trg_brands_owner_change_guard`,
   `trg_manufacturers_owner_change_guard`.
2. An unreferenced brand **may** change `owner_type/owner_id` (guard passes).
3. A brand with a child brand **cannot** change its owner pair → `check_violation`.
4. A brand with a manufacturer link **cannot** change its owner pair → `check_violation`.
5. A manufacturer with an identifier (or link) **cannot** change its owner pair →
   `check_violation`.
6. Changing `organization_id` on a referenced master is refused (composite FK or guard).
7. Assert the SQLSTATE surfaces as a clean envelope response (not a 500) once the shared
   `IntegrityError` handler from the categories plan D13 lands — until then, assert the
   `IntegrityError` at commit, as the existing overlap test does
   (`test_core_master.py:188–204`).

**Do not** add `check_owner_exists` tests — the function is not part of Option A.

---

## 13. Phasing

| Phase | Content | Depends on |
|---|---|---|
| **0** | Resolve §15 Q1 (global masters?) and Q2 (alias scope confirmation) | — |
| **1** | G1 migration (function + 2 triggers) + G5 tests + G4 docstrings | 0 |
| **2** (optional, separate scope) | G2 tenant-shared masters, if Q1 says yes | 0, 1 |
| **3** (optional, separate scope) | Convenience alias/brand reverse-lookup endpoints, pgvector name dedup | 1 |
| **deferred** | Categories module (owner-based world, only if Option B ever chosen) | its own plan |

Phase 1 is a self-contained PR. **Brands and manufacturers are effectively complete
today; Phase 1 is the only work this target schema actually requires.**

---

## 14. Docs to update (with the Phase 1 PR)

- `docs/MODULES.md` — add `core.guard_master_owner_change()` to the core-master
  "Database-owned guards" list (line ~277).
- `docs/PROJECT_STRUCTURE.md` — mention the new migration alongside `b1a2c3d4e5f6`
  (line ~60).
- `docs/implementation-plan/brand-implementation-plan.md` — this document (mark status
  FINAL when Phase 1 lands).
- No Debezium/search/tenancy docs change (nothing new there).

---

## 15. Open questions

1. **Are cross-tenant "global/shared" masters a launch requirement?** Default: **no**
   (Option A). If yes, it is an explicit tenancy carve-out (Option B / G2) with an
   `GLOBAL_TABLES` reason and a categories dependency — decide before any code is written.
2. **`entity_aliases` owner scope:** confirm tenant-scoped (`tenant_id` + nullable
   `organization_id`) is correct and the target's owner pair is not required. Default:
   confirm current.
3. **Name embedding dedup (pgvector):** not in the target schema; if wanted, flag the
   embedding model/dimension and inline-vs-Celery as the master prompt requires. Default:
   out of scope.
4. **Verification tri-state:** confirm `verification_status` is sufficient and no
   `is_verified IS NULL` column is required. Default: sufficient.
5. **`slug`:** confirm it stays (target omits it). Default: stays — it is in the API
   contract and search index.

---

## 16. Definition of done

- [ ] §15 Q1 answered (global masters in or out); if out, G2 explicitly descoped.
- [ ] G1 function + two triggers in a reviewed migration; `alembic upgrade head` on the
      scratch DB passed; downgrade reverses cleanly.
- [ ] G5 tests added and green; existing `tests/test_core_master.py` still green.
- [ ] G4 reconciliation note in both model docstrings.
- [ ] `docs/MODULES.md` and `docs/PROJECT_STRUCTURE.md` updated.
- [ ] No change to tenancy isolation (`test_tenancy.py` green).
- [ ] No new extension/dependency/port/Redis DB/image.
- [ ] No `check_owner_exists`, `brand_manufacturer_scope`, or `manufacturer_child_owner_sync`
      added — their absence is documented with a reason.
- [ ] Declaration in the PR: "the target schema was already ~90% implemented; this PR closes
      the single owner-change guard and records the ownership reconciliation."