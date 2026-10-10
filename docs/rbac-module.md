# Teams, Departments & RBAC — analysis and build plan

**Status:** ✅ **implemented 2026-09-26** (Phases 0–5 + 7; Phase 6 data scope is *designed, not built* — see §12).
**Read §12 first:** it records the decisions you made, what was built, and where the build deliberately deviates from
the sections below. Sections 0–11 are the analysis and plan as written before the build ·
**Revision 2:** 2026-09-26 (first draft the same day; see §0.1 for what changed after reading the existing modules) ·
**Input:** the pasted SQL "Teams, Organizational Hierarchy & RBAC Architecture Module" (14 tables, schemas `teams` + `rbac`) ·
**Builds on:** [tenancy](tenancy/README.md) · [location hub](geo/README.md) · `app/modules/{roles,users,hr,hubs,geo,categories,entities,custom_fields}` ·
**Closes:** tenancy open items #1 (enforce permissions) and #4 (assign a role to a user)

Everything under §1 was read out of the code, not inferred from docs. Where a claim is a judgement rather than
a fact, it says so.

---

## 0. Summary

**What you asked for:** teams, departments, job titles and a role/permission system, all scoped to a tenant and
an organization, on top of the `roles` and `users` modules that already exist.

**What I recommend:**

1. **Treat the pasted SQL as a functional spec, not as the deliverable.** It is a good statement of *what* to
   model, but as DDL it would bypass our models/Alembic/conformance tests, let one tenant's row point at
   another tenant's row, duplicate things we already have, and carry real bugs (§2.3). It has to be
   re-expressed with our mixins and composite FKs.
2. **Two new modules, one extended module, and almost no new machinery.** `app/modules/rbac` (permission
   catalogue, evaluator, guards) and `app/modules/teams` (departments, job titles, teams, memberships).
   `app/modules/roles` is **extended, not replaced**. Trees, addresses, custom fields, tags and documents all
   reuse what `geo`, `categories`, `entities` and the capability mixins already provide (§0.1, §3.5).
3. **Nine of the pasted 14 tables get built; five do not** — `rbac.roles` (evolve `public.roles`),
   `team_role_permissions` (second path to the same result), `team_external_identities` (sync crosswalk's job),
   `user_organization_profiles` (merged into `hr.employment_records`), `department_locations` (an address is
   `geo`'s job).
4. **Fix a live security hole first (Phase 0).** Today any signed-in user can `PUT /api/users/{id}` with a
   `role_id`, and can list every user in their tenant including medical history, PAN and bank details
   (§1.5, F1–F2). This does not need RBAC to close and should not wait for it.
5. **Roll RBAC out in shadow mode** before enforcing, because "branch admin ⇒ tenant admin" becomes "admin of
   that organization subtree" and that can lock people out (§7.3).

**Rough size** (one developer who knows this codebase; ideal days, not calendar): Phase 0 ≈ 1 · Phase 1 ≈ 5 ·
Phase 2 ≈ 3 · Phase 3 ≈ 5 · Phase 4 ≈ 5 · Phase 5 ≈ 5 · Phase 6 ≈ 5 · Phase 7 ≈ 3 → **≈ 32 days**. Phases 0–3
(a working, enforced RBAC) are ≈ 14 and stand alone. Reuse saved roughly what the newly discovered gap
(`hr` has no service or API at all, §5.5) cost.

**What I need from you:** the 13 decisions in §10. Each has a recommendation; if you agree with all of them,
say "go with the recommendations" and Phase 0 can start immediately.

### 0.1 What changed after re-reading the existing modules (revision 2)

| # | Revision 1 said | Reading `geo`, `categories`, `entities`, `custom_fields`, `hr`, `tags`, `documents` showed | Change |
|---|---|---|---|
| R1 | Keep a thin `workplaces` table (floor/room, HQ flag) over `geo.places` | `geo.places.kind` already has **`office`** and `place_links.link_type` has **`office`**; the address book is polymorphic by `owner_type` and its docstring names `OWNER_TYPES` as the extension point; floor/room fit the link's `custom_attributes`/`attention` | **Drop the table.** Departments/teams get addresses through `/api/addresses` with `owner_type='department'\|'team'` (§5.6). −1 table, −1 API, −1 scope. |
| R2 | "Nested set is a legacy artefact, nothing queries `_lft/_rgt`; drop it (D8)"; keep DB cycle triggers | **Wrong.** `categories` keeps `_lft/_rgt/depth/path` and maintains them with one tested pure routine, `categories/tree.py::recompute_bounds`, as a full recompute under a per-tree advisory lock; cycles are refused in Python (`TreeError`) plus a `parent <> id` CHECK. The DB triggers this repo does use guard *scope consistency*, not cycles; `geo` and `hubs` have none for cycles either | **Keep `_lft/_rgt` (you asked for them preserved), reuse the routine** (moved to `app/common/tree.py`, categories re-exports it), **drop the recursive cycle triggers.** D8 reversed. |
| R3 | Permission catalogue synced by a startup/CLI task that also reconciles role permissions | House seeding is *insert-missing, never overwrite* (`custom_fields/seed.py` uses `on_conflict_do_nothing`), run by the migration and `scripts/seed.py`; role/permission overwrites would fight operator edits | Seeder follows that pattern. **`owner` and `admin` become computed grant modes** (all / all-but-`owner_only`) — no rows to sync per organization per release (§4.9). |
| R4 | Cache in Redis with an epoch | `users.service` already has an L1 in-process + L2 Redis cache for *reference data*. L1 is wrong for per-user grants (each worker would go stale independently) | Redis-only, no L1; TTL clipped to the next validity boundary so a grant expiring mid-cache is not honoured late (§4.6). |
| R5 | "`PATCH /api/hr/employment/{id}` extends hr" | `hr`, `kyc` and `compliance` contain **models only — no service, no API, no router**. Nothing creates an employment record today | Phase 4 must **build** a small employment service/API (§5.5). Cheaper alternative noted (D4b). |
| R6 | 14 pasted columns kept as-is | Several have no defined behaviour (`permissions_summary`, `parent_role_id`, `primary_region_id`, `display_order` beside `sort_order`) | Column trims (§3.6). |
| R7 | Defects were numbered D1–D10, decisions D1–D12 | Two different things sharing labels | Pasted-SQL bugs are now **B1–B10**; **D#** is decisions only. |
| R8 | (not covered) | New modules must follow the house anatomy and registration checklist (lang catalogues, `ResponseModel.ok(module=, msg_key=)`, alembic env imports, `.importlinter`, conftest table list, compose env passing) | New §3.5 checklist. |
| R9 | Opt-in capabilities not considered | `core.entity_types` is the shared registry that custom fields, categories, aliases and taxes key on; `HasCustomFieldsMixin` / `HasTagsMixin` / `HasDocumentsMixin` are one-line opt-ins | Register `department`, `team` (and `job_title`) as entity types; opt in to custom fields/tags (§3.5). Almost free, and it is where users will ask for it next. |
| R10 | Escalation guard only compared permissions | `roles` will carry `hierarchy_level` anyway | Also refuse assigning a role whose level ≥ the actor's own (§4.8) — a cheap second wall. |
| R11 | Test plan used the two-tenant `worlds` fixture | `build_world` makes **one flat organization** per tenant; scope tests need a tree | Add a 3-level `tree_world` fixture (§9). |
| R12 | Platform-admin behaviour unstated | `TenantAdmin` lets a platform admin through everything | Stated explicitly (§4.9): same bypass, audited. |

---

## 1. What exists today (verified)

### 1.1 Tenancy — the rules every new table must follow

| Fact | Source |
|---|---|
| `org_management.tenants` (global root) → `org_management.organizations` (tree: holding / legal_entity / branch / solo; text materialized path of UUIDs *including the node itself*, `depth`) | `organizations/model.py` |
| Every table is **ENTITY**, **LEDGER** or an explained **GLOBAL**; enforced by `test_every_table_is_entity_ledger_or_an_explained_global` | `tests/test_tenancy.py:192` |
| ORM reads are filtered by **tenant only** (`with_loader_criteria(TenantBound …)`). **Organization is not filtered on reads** — it is stamped on writes and chosen by `X-Organization-Code` | `database/tenancy.py:220` |
| `MultiTenantMixin`/`OrgEntityMixin` = `organization_id NOT NULL` + auto composite FK `(tenant_id, organization_id) → organizations(tenant_id, id)` + auto index `ix_<table>_tenant_org`. `TenantScopedMixin`/`TenantEntityMixin` = same but `organization_id` nullable (NULL = tenant-wide) | `database/mixins.py` |
| One resolver decides a write's tenant+organization (`app/database/scope.py`): header code → header uuid → user's own → tenant's only org → deployment default → 422 `organization_required`. Modules keep a thin wrapper only for their own error code (`geo.scope.require_organization`, `entities.scope`) | memory: org-scope-resolution |
| Optimistic locking: `row_version` + 409 with `current_row_version`; soft delete with who/when/why; `created_by*/updated_by*` are plain BigIntegers (**no FK**, so they survive user deletion) | mixins |
| Tenant-safe references use **composite FKs** to `(tenant_id, id)` — `place_links → places`, `places.parent_location`, `hubs.parent_hub`, `users → roles` — each target having a `UniqueConstraint(tenant_id, id)` | `geo/model`, `hubs/model.py` |
| Schemas in use: `org_management, geo, currency, sync, tax, core, extfields` (registered in `alembic/env.py::_OWNED_SCHEMAS`) | `alembic/env.py` |

### 1.2 Roles (`app/modules/roles`, table `public.roles`)

* `Role(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin)` — **organization-owned**. Columns: `code`, `name`,
  `description`, `permissions JSONB` (a list of free strings, **never validated and never read**), `is_system`.
* `uq_roles_tenant_org_id (tenant_id, organization_id, id)` is the target of `users`' composite FK
  `(tenant_id, organization_id, role_id)` — a user can only hold a role **of their own organization**.
* Live-unique `(tenant_id, organization_id, code)`; `status IN ('active','inactive')`; code pattern
  `^[a-z][a-z0-9_]{1,49}$` (lower snake case).
* System roles `owner / admin / member` are seeded **per organization** by `seed_system_roles` (called from
  `organizations.service` and `tenants/seed.py`) and cannot be deleted; a role still held cannot be deleted.
* API `/api/roles`: read = any signed-in user; write = `TenantAdmin`. Debezium already streams `public.roles`.

### 1.3 Users (`app/modules/users`)

* `users.role_id` → the **single** base role. `users.organization_id NOT NULL` (home org).
  `uq_users_tenant_id (tenant_id, id)` already exists — the target for tenant-safe FKs *to* users.
* Legacy free-text `users.department`, `users.designation`, `users.date_of_joining`, `company_*`
  (`hr.employment_records` carries `department`, `designation` as text too).
* JWT claims carry `role_id` and `user_type` at issue time. Authorization does **not** read them (it reads the
  DB), so they can be stale but are not a security input today.
* Self-registration and Authentik JIT create users with `role_id = NULL` in the default org.
  `POST /auth/dev-token` (DEBUG only) creates a user with no role.

### 1.4 Authorization today

| Guard | Rule | Used by |
|---|---|---|
| `CurrentUser` | any valid token; binds tenant + org | everything |
| `TenantAdmin` | platform admin **or** the user's role **code** ∈ {`admin`,`owner`} — *in their tenant, regardless of which org owns that role* | custom_fields, fleet_partners, geo (+geocoding), manufacturers, brands, taxes (assignments), entities, vehicles, roles, documents, categories, currencies, organizations, hubs |
| `PlatformAdmin` | email ∈ `PLATFORM_ADMIN_EMAILS`; **list empty ⇒ anyone if `DEBUG`** | tenants |
| `ZohoOperator` | email ∈ `ZOHO_OPERATOR_EMAILS`; list empty ⇒ anyone if `DEBUG` | zoho admin |

The code itself says these are interim. An earlier plan
(`docs/implementation-plan/users-update-implementation-plan.md`, decision #6) explicitly put RBAC out of scope;
this document reverses that decision.

### 1.5 Findings that matter before any design work

| # | Finding | Evidence | Severity |
|---|---|---|---|
| **F1** | **User management is not authorized.** `POST /users`, `PUT /users/{id}`, `DELETE /users/{id}?hard=true`, `restore`, `ban/unban/throttle/unthrottle` take only `CurrentUser`. `UserUpdate` includes `role_id`, `status`, `user_type`, `is_deactivated`. Any signed-in user can promote themselves (or anyone in the tenant) to `admin`, deactivate the real admins, or hard-delete them. The tenant filter is the only wall. | `users/api.py` (`create_user`…`unthrottle_user`), `users/schema.py` (`UserUpdate`) | **High** |
| **F2** | **Sensitive fields leak to every signed-in user.** `GET /users` and `/users/{id}` return `UserOut` = `UserProfileBase` + read-only fields: `medical_history`, `insurance_details`, `pan`, `gstin`, `emergency_contact`, `family_details`, **`bank_details`, `payment_details`**, `billing_address`, … Nothing redacts by viewer. (Read from the schema and `user_outs`; not exploit-tested.) | `users/schema.py`, `users/service.py::user_outs` | **High** (DPDP exposure) |
| F3 | `TenantAdmin` is tenant-wide by construction: an `admin` of a *branch* passes every `TenantAdmin` route for the whole tenant. Roles are org-scoped as data but not as authority. | `tenants/deps.py` | Medium |
| F4 | "empty allow-list + `DEBUG=true` ⇒ anyone is platform admin / Zoho operator". Safe only while prod runs `DEBUG=false` *and* the lists are set. `.env.prod.example` ships both lists empty. | `tenants/deps.py`, `zoho/admin/deps.py`, `deployment/.env.prod.example` | Medium — **verify prod** |
| F5 | `roles.permissions` accepts arbitrary strings; a typo is silently a no-op forever. | `roles/schema.py` | Low |
| F6 | Reads are tenant-filtered but not org-filtered, so "org-scoped" today means *written by* an org, not *visible only to* it. RBAC as planned decides **who may act**; it does not change read visibility (that is the optional Phase 6). | `database/tenancy.py` | Design fact |
| F7 | A role-less user (self-registered, SSO JIT) can call every `CurrentUser` endpoint, including reads of reference data. Enforcing permissions on *reads* would break these users, so Phase 3 gates **writes and sensitive reads only**. | — | Design fact |
| F8 | `hr`, `kyc`, `compliance` have **models only** — no service, API or router. `employment_records` is never written by the application today. | `app/modules/{hr,kyc,compliance}` | Design fact |

**Recommendation: do Phase 0 (F1, F2, F4 check) now, independent of the rest.** It is a few lines per route
using the guard that already exists (`TenantAdmin`) plus a narrower response model for non-admin viewers.

### 1.6 Machinery already in the repo that this plan reuses

| Need | Existing piece | Where |
|---|---|---|
| Hierarchy with bounds/depth/path, cycle refusal | `recompute_bounds`, `ancestors_of`, `subtree_of`, `TreeError` — pure, hermetically tested | `categories/tree.py`, `tests/test_categories_tree.py` |
| Per-tree write lock | `pg_advisory_xact_lock(hashtextextended(key,0))` in `_lock_tree` | `categories/service.py` |
| Move a subtree by materialized path | one `UPDATE … concat(new_path, substr(...))` with explicit `row_version` bump | `organizations/service.py::move_organization` |
| Tenant-safe self/parent FK + `parent <> id` CHECK | `places.parent_location`, `hubs.parent_hub` | `geo/model/place.py`, `hubs/model.py` |
| Polymorphic address for any owner | `geo.place_links` (`owner_type`, `link_type`, effective dating, `custom_attributes`) + `PlaceKind.OFFICE` | `geo/model`, `geo/enums.py` |
| Shared entity-type registry | `core.entity_types` (`code → schema.table`) | `entities/model.py` |
| One-line capabilities | `HasCustomFieldsMixin`, `HasTagsMixin`, `HasDocumentsMixin`, `HasCategoriesMixin` | each module's `mixins.py` |
| Insert-missing seeding used by migrations and `scripts/seed.py` | `seed_data_types` (Core table, never overwrites) | `custom_fields/seed.py` |
| DB scope guards where a composite FK is not enough | `core.guard_category_scope()` trigger | categories migration |
| Localized messages | `ResponseModel.ok(module="geo", msg_key="place_created", name=…)` + `modules/<m>/lang/en.py::MESSAGES` | `common/response`, `geo/lang` |
| Module error with its own code | `GeoRuleError(AppError) 422 geo_rule_violation` | `geo/scope.py` |
| Audit | `record_activity` (savepoint-isolated, best effort) | `activity/recorder.py` |
| Searchable entity | `SEARCHABLE_ENTITIES` registry + Debezium include list | `search/registry.py` |

---

## 2. The pasted design, table by table

### 2.1 Verdicts

| # | Pasted table | Verdict | Why |
|---|---|---|---|
| 1 | `teams.department_locations` | **Drop → `geo` (R1)** | Its only additions over `geo.places` are floor/room and an HQ flag. A place of `kind='office'` linked to a department/team with `link_type='office'` covers it; floor/room go in the link's `custom_attributes`. No new table, and no third thing called "locations" next to `/api/locations` and `/api/zoho/locations`. |
| 2 | `teams.departments` | **Keep** | Nothing equivalent exists. Hierarchical, org-owned. |
| 3 | `teams.job_titles` | **Keep** | Replaces free-text `users.designation` / `employment_records.designation`. |
| 4 | `teams.team_types` | **Keep** | |
| 5 | `teams.team_roles` | **Keep** | Roles *within a team* (lead, member, coordinator). Distinct from RBAC roles; linked by `rbac_role_id`. |
| 6 | `teams.teams` | **Keep** | |
| 7 | `teams.user_teams` | **Keep, redesign uniqueness** | Membership with validity + approval. As written, an ended or soft-deleted membership blocks re-joining (B3). |
| 8 | `teams.user_organization_profiles` | **Merge into `hr.employment_records` (D4)** | A second copy of `employment_records`: `is_current` + one-current-per-user, start/probation/confirmation/end dates, `reporting_manager_user_id`, department, designation, type/status. Two "authoritative" employment tables will drift. Add `department_id` and `job_title_id` to the existing table. |
| 9 | `rbac.roles` | **Drop — evolve `public.roles` (D1)** | A second roles table forks `users.role_id`, CDC, seeding, the API, `TenantAdmin` and every test fixture. |
| 10 | `rbac.permissions` | **Keep as GLOBAL** | Platform-wide catalogue, like `countries`/`document_types`; needs a reasoned entry in `GLOBAL_TABLES`. Owned by code (§4.2). |
| 11 | `rbac.role_permissions` | **Keep (scoped-config shape)** | Replaces the unvalidated `roles.permissions` JSONB. |
| 12 | `rbac.user_roles` | **Keep, restructure scope** | Contextual grants. `scope_id` without an FK is an orphan factory; replace with typed, tenant-safe scope columns (§3.3). |
| 13 | `teams.team_role_permissions` | **Drop** | Second path to the same result as `team_roles.rbac_role_id`; a team role needing special permissions maps to a (custom) RBAC role. |
| 14 | `teams.team_external_identities` | **Drop** | References `integration.connections`, which does not exist. External ids are the sync crosswalk's job (`app/modules/sync`); register `team`/`department` as crosswalk entities when a real external source (Authentik group, Zoho People) exists. |

### 2.2 Structural mismatches (apply to every kept table)

| # | Pasted | House rule | Consequence |
|---|---|---|---|
| M1 | Raw SQL file | SQLAlchemy models are the source of truth; migrations are hand-written Alembic; conformance/cycle tests walk `Base.metadata` | Re-express as models + one migration each. |
| M2 | Column `metadata jsonb` | `metadata` is a **reserved attribute name** in SQLAlchemy Declarative (collides with `Base.metadata`) — the model would fail to import | Use the mixin's `app_metadata` (or a domain name such as `attributes`). |
| M3 | `tenant_id → tenants ON DELETE CASCADE` **and** a single-column `organization_id → organizations(id)` **and** a composite FK | `OrgEntityMixin` already adds the tenant FK and the composite FK | Drop the extras. |
| M4 | Every intra-module FK is single-column (`parent_department_id → departments(id)`, `team_type_id`, `head_of_department_user_id → users(id)`, …) | Tenant-safe **composite** FKs `(tenant_id, x_id) → parent(tenant_id, id)` | As pasted, nothing in the database stops a team of tenant A from pointing at tenant B's team type. Each target needs `UniqueConstraint(tenant_id, id)`; hierarchy and membership FKs use `(tenant_id, organization_id, id)` like `users → roles`. |
| M5 | `created_by/updated_by/deleted_by` **FK to users ON DELETE NO ACTION** | `AuditMixin` deliberately has no FK (survives user deletion) | With those FKs, `DELETE /users/{id}?hard=true` fails for anyone who ever created a team. Drop the FKs. |
| M6 | Table-level `UNIQUE (tenant, org, code)` | Live-only partial unique index `WHERE deleted_at IS NULL` | A soft-deleted department's code can never be reused. (Same class of bug as `uq_place_links_dedupe`, fixed on 2026-09-26: history must not participate in uniqueness.) |
| M7 | `ix_*_tenant_org` on every table, plus indexes on `status`, `sort_order`, `hierarchy_level`, `display_order` | The mixin already creates `ix_<table>_tenant_org` and `ix_<table>_tenant_id`; low-cardinality single-column indexes are noise | Keep only indexes that serve a named query. |
| M8 | Nested set **and** path/depth **and** recursive-CTE cycle triggers | `categories` keeps bounds + path + depth with one tested routine under an advisory lock, and refuses cycles in Python + a CHECK (R2) | Keep the pasted `_lft/_rgt/depth/path`; maintain them with the shared routine; **drop the recursive triggers.** |
| M9 | Hand-typed `CHECK (status IN (...))` strings | Module `enums.py` + `values(Enum)` helper so code and constraint cannot drift | Follow `geo/enums.py`. |
| M10 | Audit columns lack `updated_by_name`, `app_version`, `app_metadata`, `row_version`, `status`, `is_verified`, `deleted_reason` | The conformance test fails a table that has `row_version` but not the full ENTITY set | Use `OrgEntityMixin`/`TenantEntityMixin` + `SoftDeleteFilteredMixin`. |
| M11 | `uuidv7()` on **every** table | `BigIntPKWithUUIDv7Mixin` exists (tax, core, categories use it) but a public uuid is only for rows an API addresses | uuid on `departments`, `job_titles`, `team_*`, `teams`, `user_teams`, `user_roles`; **not** on `role_permissions` or the global `permissions` (addressed by `code`). |
| M12 | Comments cite "Hard Rule 9 / PD-2", "Lens 2", "AP20", "AP4", "P2" | These labels are from another project's spec; they do not resolve anywhere in this repo (the only `R12` here is unrelated) | Translated into concrete rules in this document instead. |

### 2.3 Bugs in the pasted SQL (regardless of architecture)

| # | Where | Problem | Effect |
|---|---|---|---|
| **B1** | Seed `role_permissions` | `… OR (r.role_code = 'ORG_ADMIN' AND p.permission_code LIKE 'teams:%' OR p.permission_code LIKE 'departments:%') OR …` — `AND` binds tighter than `OR`, so `OR p.permission_code LIKE 'departments:%'` applies to **every role** | `TEAM_MEMBER` and `AUDITOR` receive `departments:delete`. Also `ORG_ADMIN` gets no `rbac:*`. |
| B2 | `rbac.permissions` | `CHECK action_name IN (...)` **plus** a free-text `permission_code` with no tie to `(module, resource, action)`. Seeded codes are inconsistent: `teams:create` (2 segments) vs `rbac:roles:manage` (3 segments); `teams:assign_members` has `action_name='assign'` | The code can disagree with its own parts; the closed action list needs a migration to add an action. |
| B3 | `user_teams` | `UNIQUE (tenant, user, team, role)` ignores `deleted_at`/validity; `user_id` and `team_id` are **nullable**; `uq_user_teams_one_primary_active (user_id)` ignores tenant, `status`, `valid_until` | A member who leaves cannot rejoin with the same role; an *expired* primary membership blocks a new primary; a row with `user_id NULL` is legal. |
| B4 | `team_types`, `teams`, `team_roles` | `type_code`/`team_code`/`role_code` are nullable **and** unique `NULLS NOT DISTINCT` — at most one row per org may have no code | Almost certainly meant `NOT NULL`. |
| B5 | `rbac.roles` | Global "system" roles have `tenant_id NULL`; our tenant filter is `tenant_id = :t`, so such rows are invisible to every tenant. Codes are `UPPER_CASE` but our role-code pattern is lower snake | Unusable as-is; the pattern check rejects them. |
| B6 | `rbac.user_roles` | `scope_type` + `scope_id` polymorphic with no FK; unique index ignores `deleted_at`/`status` | Dangling scopes; a revoked grant blocks re-granting. |
| B7 | `user_organization_profiles.start_date` | `NOT NULL DEFAULT CURRENT_DATE` | A backfilled historical hire silently gets *today* as their start date. |
| B8 | `team_roles` vs `team_role_permissions` | Two ways to bind a team role to permissions | Ambiguous source of truth. |
| B9 | `set_updated_at()` lives in schema `teams` but is used by `rbac.*` triggers; `TimestampMixin` already sets `updated_at` in the ORM | Cross-schema coupling; two writers of `updated_at` | Use the ORM path only. |
| B10 | `chk_user_org_profiles_not_self_report` duplicates the trigger's self-check | — | Harmless; keep the CHECK (house style), drop the trigger. |

---

## 3. Target architecture

### 3.1 Shape

```
                       org_management.tenants  ·  org_management.organizations (tree)
                                    ▲                          ▲
                        every table below: tenant_id  +  organization_id (composite FK)
                                    │
  public.roles  (extended)          │                    teams.*                            hr.employment_records (extended)
  ├─ role_permissions ──────────────┼─► rbac.permissions   departments ◄─ parent (self)      ├─ department_id ──► departments
  │   (rbac schema)                 │     (GLOBAL, code-owned)  job_titles                    ├─ job_title_id  ──► job_titles
  └─ users.role_id (base role)      │                          team_types ◄─ parent           └─ reporting_manager_user_id (exists)
                                    │                          team_roles ──► rbac_role_id ──► public.roles
  rbac.user_roles ── contextual     │                          teams ◄─ parent (self)
   grants at tenant / org /         │                          user_teams  (membership: validity + approval)
   department / team scope          │
                                    │        addresses:  geo.place_links  (owner_type = department | team)  ──► geo.places (kind = office)
                                    │        entity registry: core.entity_types += department, team, job_title
```

Effective permissions of a user =
**base role** (`users.role_id`) ∪ **contextual assignments** (`rbac.user_roles`) ∪ **team-role grants**
(approved, in-window `user_teams` → `team_roles.rbac_role_id`), each carrying its own **scope**. Additive only
in v1 — no deny rules.

### 3.2 Modules and import layering

| Module | Owns | Notes |
|---|---|---|
| `app/modules/roles` *(extended)* | `public.roles` | gains `hierarchy_level`, `is_assignable`, `grant_mode`; `permissions` JSONB is migrated then dropped; `RoleOut.permissions` stays (computed) so clients do not break |
| `app/modules/rbac` *(new)* | schema `rbac`: `permissions`, `role_permissions`, `user_roles`; catalogue registry + seeder; evaluator; cache; FastAPI guards; `/api/permissions`, `/api/me/permissions`, `/api/users/{id}/roles` | must sit **in the tenancy-core layer** — every feature module imports its guard |
| `app/modules/teams` *(new)* | schema `teams`: departments, job_titles, team_types, team_roles, teams, user_teams | depends on users, organizations, geo, rbac |
| `app/modules/hr` *(extended)* | two FK columns on `employment_records` **plus a new minimal service + API** (there is none — F8) | |
| `app/common/tree.py` *(moved)* | `recompute_bounds` & friends, generalised error text | `categories/tree.py` becomes a re-export so `tests/test_categories_tree.py` and `categories` are untouched |

`.importlinter`: `rbac` may import `users.deps`/`tenants`/`organizations`, **never a feature module**; feature
modules import only `rbac.deps`. `users.api` will import `rbac.deps`; `rbac.deps` imports `users.deps` (auth) —
no cycle because `deps` and `api` are different modules, but `tests/test_import_cycles.py` must be run after
wiring it. `teams` and `categories` stay independent (both import `app.common.tree`, not each other).

### 3.3 Table catalogue (final)

Class = tenancy table class from `tenancy/README.md` §3. "Scoped config" = the fourth legitimate shape
(`MultiTenantMixin` + `AuditMixin` + `AppMetaMixin` + `TimestampMixin` + soft delete, no `status`/`row_version`).

| Table | Class | Scope | Key constraints (partial unique = `WHERE deleted_at IS NULL`) |
|---|---|---|---|
| `rbac.permissions` | GLOBAL | — | `UNIQUE (permission_code)`; `permission_code` is a **generated column** = `module.resource:action`; format-regex CHECK; `is_system`, `owner_only`, `deprecated_at`. No uuid |
| `rbac.role_permissions` | scoped config | org (= the role's org) | composite FK `(tenant_id, organization_id, role_id) → roles`; FK `permission_id`; live `UNIQUE (role_id, permission_id)`. No uuid |
| `public.roles` *(existing)* | ENTITY | org | + `hierarchy_level`, `is_assignable`, `grant_mode IN ('explicit','all','all_but_owner_only')`; status CHECK += `deprecated`; **new** `UNIQUE (tenant_id, id)` (target for `team_roles.rbac_role_id`) |
| `rbac.user_roles` | ENTITY | tenant **or** org (`TenantEntityMixin`; `organization_id NULL` = tenant-wide) | `(tenant_id, user_id) → users`; role composite FK; typed scope columns `department_id`, `team_id` (composite FKs, MATCH SIMPLE); `scope_type IN ('tenant','organization','department','team')` with a CHECK that exactly the matching column is set; `include_descendants`; `valid_from/valid_to`; live unique `(user, role, scope_type, organization_id, department_id, team_id)` NULLS NOT DISTINCT while open; `EXCLUDE` no overlapping window (like `place_links_no_overlap`) |
| `teams.departments` | ENTITY | org | live unique `(tenant, org, department_code)`; self composite FK `(tenant_id, organization_id, parent_department_id)` RESTRICT; CHECK `parent <> id`; `head_of_department_user_id` composite FK to users; tree columns `_lft/_rgt/depth/path/position` maintained by `app/common/tree.py` |
| `teams.job_titles` | ENTITY | org | live unique `(tenant, org, job_code)`; optional `department_id` composite FK |
| `teams.team_types` | ENTITY | org | live unique code; self FK; tree columns; `default_team_role_id` FK added after `team_roles` |
| `teams.team_roles` | ENTITY | org | live unique `(tenant, org, role_code, team_type_id)` NULLS NOT DISTINCT; `rbac_role_id` → `roles (tenant_id, id)` |
| `teams.teams` | ENTITY | org | live unique code; `team_type_id` composite FK **RESTRICT**; self FK; optional `department_id`, `team_lead_user_id`; tree columns |
| `teams.user_teams` | ENTITY | org (= the team's org, enforced by composite FK `(tenant_id, organization_id, team_id)`) | `user_id`, `team_id` **NOT NULL**; `team_role_id` composite FK; live unique on **open** memberships `(tenant, user, team, team_role) WHERE valid_until IS NULL`; one primary per user `(tenant, user) WHERE is_primary AND status='active' AND valid_until IS NULL`; `EXCLUDE` no overlapping window for the same `(user, team, role)`; `approval_status`, `approved_by/at` |
| `hr.employment_records` *(existing)* | ENTITY | org | + `department_id`, `job_title_id` (composite FKs, nullable); CHECK `reporting_manager_user_id <> user_id` |

### 3.4 Scoping rules (how "org and tenant scoped" is guaranteed)

1. **Every table** has `tenant_id NOT NULL`; the automatic ORM filter applies with no code in the module.
2. **Every operational table** (departments, teams, memberships, …) is org-owned (`organization_id NOT NULL`);
   the composite FK makes a cross-tenant organization impossible even in raw SQL.
3. **Every reference between tenant tables is a composite FK** including `tenant_id` (M4): the database, not
   only the ORM, refuses `team.team_type` from another tenant.
4. **Hierarchy and membership FKs also pin the organization** — `(tenant_id, organization_id, id)`, as
   `users → roles` does — so a team cannot sit under another org's team or use another org's team type.
   (`geo`/`hubs` parents pin only the tenant; teams pin the org too because tree bounds are computed per
   organization.) Cross-org reuse is an explicit feature (D2), not an accident.
5. **Grants are scoped separately from data**: an assignment has its own scope (§4.4). A grant scoped to org X
   does nothing in org Y even though both are in the tenant.
6. **Deletes**: soft delete everywhere; hard delete forbidden for these tables; a department/team with live
   children or members cannot be archived (service check, like organization delete "leaves only").
7. **`ON DELETE SET NULL` on a composite FK would null `tenant_id` too.** Use `RESTRICT` (the house default for
   `places`/`hubs`) or PostgreSQL 15+'s column-list form `SET NULL (col)`; verify what Alembic renders in the
   migration rehearsal before relying on it.
8. **Test DB:** the permission catalogue is reference data seeded by its migration (like `document_types`) and
   must **not** be in `_TEST_TABLES`; the new scoped tables **must** be added there (children first).

### 3.5 Implementation checklist — follow the house anatomy

Every new module mirrors `geo`/`categories`, so a reviewer already knows where things are:

| Piece | Convention (verified in `geo`) |
|---|---|
| Files | `api.py` (several `APIRouter`s if several prefixes) · `service.py` · `schema.py` · `enums.py` (`values(Enum)` for CHECKs) · `model.py` or `model/` · `scope.py` only if a module-specific error code is wanted · `seed.py` · `permissions.py` · `lang/en.py` |
| Errors | `class TeamsRuleError(AppError): status_code = 422; code = "teams_rule_violation"` (likewise `rbac_rule_violation`); organization resolution through `app.database.scope`, never a sixth private copy |
| Responses | `ResponseModel.ok(data=…, module="teams", msg_key="team_created", name=…)`; every key in `lang/en.py::MESSAGES`; list endpoints use `PageModel` (as `/users`) rather than `geo`'s bare lists |
| Refs | `{ref}` = uuid (preferred) \| code \| numeric id |
| Updates | body carries `row_version`; mismatch → 409 `current_row_version`; soft delete needs `?reason=` |
| Audit | `record_activity(...)` in every mutating service function, before/after via `_jsonable` |
| Registration | `app/router.py` (`include_router`); model import in `alembic/env.py`; `_OWNED_SCHEMAS += {"teams","rbac"}`; `.importlinter` contracts; `tests/conftest.py::_TEST_TABLES`; `search/registry.py` + Debezium `table.include.list` if searchable |
| Config | new settings (e.g. `RBAC_ENFORCEMENT`) go in `core/conf.py`, `.env.example`, **and explicitly in `deployment/docker-compose.yml`'s `environment:` block** — compose does not pass unlisted variables (the `DEFAULT_TENANT_CODE` incident) |
| Capabilities | `Department`/`Team` opt into `HasCustomFieldsMixin` (`custom_fields_owner_type = "department"`) and `HasTagsMixin`; register `department`, `team`, `job_title` in `core.entity_types` in the migration (same way `brands` did) |
| Docs | this file becomes `docs/rbac/README.md` when built, alongside `docs/tenancy` and `docs/geo` |

### 3.6 Column trims (no defined behaviour ⇒ not shipped in v1)

| Pasted column | Decision | Reason |
|---|---|---|
| `team_roles.permissions_summary` | drop | display text that will drift from the real permission set; derive it |
| `team_roles.parent_role_id` | drop | no evaluator semantics for role inheritance; `hierarchy_level` covers ordering |
| `teams.primary_region_id` | drop | untyped, no referent; add a real FK when a region entity exists |
| `team_types.display_order` beside `sort_order` | one column, `position` (as `categories`) | two orderings of the same list |
| `teams.achievement_ratio`, `performance_last_*`, `has_targets`, `has_incentives`, `user_teams.individual_achievement_ratio`, `has_individual_targets`, `has_custom_incentives` | **keep as nullable, read-only, no logic** (D6) | you asked for columns to be preserved; they are display caches for an engine that does not exist |
| `hierarchy_path` (text) | keep as `path` from the shared routine (`/code/code/`, a breadcrumb) | authority for containment is `_lft/_rgt`, not the string (renames rewrite paths) |
| `icon_class`, `color_code` | keep | cheap UI hints |

---

## 4. The RBAC engine

### 4.1 Vocabulary

* **Permission** — one atomic capability, `module.resource:action`, e.g. `teams.team:create`.
* **Role** — a named set of permissions **owned by an organization**.
* **Grant** — (role, scope, validity, source). A user's effective permissions are the union of their grants.
* **Scope** — where a grant applies: `tenant`, `organization` (± descendants), `department` (± subtree),
  `team` (± subtree).

### 4.2 Permission catalogue — owned by code

The pasted design seeds 12 permissions by SQL. The platform has ~25 modules and needs a few hundred; hand
maintained rows drift, and F5 shows what a free-text permission is worth. So:

* Each module declares its permissions in `app/modules/<m>/permissions.py`:
  `PERMISSIONS = [Permission("teams", "team", "create", "Create teams"), …]`.
* `rbac/catalog.py` collects them. **`seed_permissions(conn)`** follows the house seed pattern
  (`custom_fields/seed.py`): a Core-table insert of the rows that are **missing**, never overwriting an existing
  row, callable from a migration and from `scripts/seed.py`. Codes that leave the registry get `deprecated_at`
  set (never deleted; grants stay readable).
* **Boot check:** at startup the app compares the registry with the table and **inserts missing catalogue rows**
  (advisory-locked, catalogue only — it never touches role grants). Forgetting to seed can therefore not become a
  permanent 403; and because `owner`/`admin` are computed (§4.9), new permissions reach them automatically.
* **Format:** `module.resource:action`; `permission_code` is a *generated column* of the three parts so it cannot
  disagree with them (B2). Actions: `create read update delete manage assign approve export` (+ new ones by
  code; the DB `CHECK` is a format regex, not a closed list).
* **`manage` implies `create/read/update/delete`** on the same resource (expanded when grants are loaded, so
  the DB stays a plain set of rows). It does **not** imply `assign/approve/export`.
* **Static route check:** a test walks every `Perm("…")` used by a route and asserts it exists in the registry.
  A typo becomes a red test, not a permanent 403.

### 4.3 Grant sources (all additive)

| Source | Data | Scope |
|---|---|---|
| Base role | `users.role_id` → the role's permissions (explicit rows, or computed by `grant_mode`) | the user's **home organization and its descendants** (D3). This reproduces today's practical behavior for a single-tree tenant (a root-org admin is admin of the tree) while ending F3 for siblings. |
| Assignment | `rbac.user_roles` (active, in window, not deleted) | the row's own scope |
| Team role | approved, in-window `user_teams` → `team_roles.rbac_role_id` | the **team** (± child teams). Leaving the team ends the grant automatically — no materialized rows to clean up. |

Not a source in v1 (D7): being `head_of_department` or `team_lead` does not by itself grant anything; those
columns are organizational facts (routing, display). Permission always comes from a role.

### 4.4 Scope semantics

Evaluation is always against a **target**: `(organization_id, department_id?, team_id?)`. The default target
organization is the request's bound organization (`X-Organization-Code`, else the user's own — already resolved
by `deps._bind_tenancy`).

| Grant scope | Matches when |
|---|---|
| `tenant` | always (inside the user's tenant — the tenant filter is a separate wall) |
| `organization` (o, include_descendants) | `target.org == o`, or descendants on and `target.org.hierarchy_path` starts with `o.hierarchy_path` |
| `department` (d, subtree) | the endpoint supplies a department and it is in the **expanded id set** of `d` (below) |
| `team` (t, subtree) | likewise for teams |

Department/team scopes are **expanded to id sets when grants are loaded** (`_lft/_rgt` range → ids of the subtree,
one query per scoped grant, usually zero or one). Matching is then a set lookup, and a tree change simply bumps
the epoch (§4.6) — no bounds are cached that a renumbering could invalidate.

A department/team-scoped grant with **no** department/team in the target does not match (fail closed). List
endpoints for such users need row filtering, which is the Phase 6 data-scope work; until then those endpoints
require an org- or tenant-scoped grant.

### 4.5 Evaluation

```text
allowed(user, code, target):
    grants = load_grants(user)                      # cached, §4.6
    for g in grants:
        if code in g.permissions and g.scope.covers(target): return True
    return False                                     # deny by default
```

* `load_grants` = one query per source, then expanded (`manage` → CRUD; `grant_mode` → the catalogue) and grouped
  **per scope** so the cache entry is small: `[{scope: …, perms: [codes…]}, …]`.
* Scope organizations are resolved to `(id, hierarchy_path)` with one `IN` query per request, memoised on the
  request; comparison is a string prefix, no recursion.
* No N+1: guards call `allowed` once per request; batch endpoints reuse the loaded grants.

### 4.6 Caching and invalidation

Redis only (the shared `redis_client`); failures fall open to the DB — an optional cache must never cause a 500
(`docs/REDIS_ARCHITECTURE.md`). **No L1 in-process layer**: the reference-data cache in `users.service` can
afford one because countries barely change, but per-user grants cached per worker would each go stale
independently after a revoke.

* Key `rbac:grants:{tenant}:{user}:{epoch}`; value = the compact grant list.
* **TTL = min(5 min, seconds until the earliest `valid_from`/`valid_to` boundary among the loaded grants)** — a
  grant that expires (or starts) while cached is not honoured (or ignored) late, and no expiry job is needed.
* `epoch` = `rbac:epoch:{tenant}` (an integer). **Bumped** on: role permission edit, role delete, organization
  move/archive (paths change), department/team tree change (id sets change), catalogue change.
  One bump invalidates every user's entry.
* Per-user **delete** on: assignment create/revoke, membership create/end/approve, `users.role_id` change.
* Nothing is written into the JWT (claims are frozen at issue time; `role_id` already is).

### 4.7 FastAPI surface

```python
from app.modules.rbac.deps import Perm

@router.post("", response_model=...)
async def create_team(user: Annotated[User, Perm("teams.team:create")], ...): ...

# resource-scoped: the target is derived from the loaded row
await rbac.require(db, user, "teams.team:update", team=team)
```

* `Perm(code)` → an `Annotated[User, Depends(...)]` (same style as `TenantAdmin`): `CurrentUser` + `allowed(…)`;
  raises `ForbiddenError` (403) with `data={"permission": code, "organization": <code>}` so a client can tell
  *which* permission is missing.
* `GET /api/me/permissions` → `{ base_role, grants: [{scope, permissions}], teams: [...] }` for UI gating.
* `TenantAdmin` **keeps its name** for the migration (§7.2); its implementation becomes
  `Perm("org.settings:manage")` once shadow mode has agreed with the old rule.

### 4.8 Guardrails (where RBAC systems become exploits)

| Rule | Enforced in |
|---|---|
| **No privilege escalation**: granting role R at scope S requires the actor to hold *every* permission of R at a scope covering S, plus `rbac.assignment:assign`. | `rbac.service.assign_role` |
| **Level check (R10):** the actor's highest `hierarchy_level` must exceed the level of the role being granted; only an `owner` grants/revokes `owner`. | same |
| **Never remove the last active owner** of an organization (also on delete/deactivate/ban of that user). | assign/revoke + `users.moderation` + `delete_user` |
| A user cannot change their **own** grants or base role. | assign/revoke, `update_user` |
| **System roles' permission sets are read-only through the API** — to customise, clone into a custom role. | roles API |
| `users.role_id` changes need `users.user:assign_role` and the same escalation check; the field is **removed from `UserUpdate`** and moves to a dedicated endpoint. | Phase 0/2 |
| A role's `organization_id` must be an ancestor-or-self of the assignment's scope org (a role owned by org X may be used within X's subtree). | `assign_role` |
| Suspended tenant ⇒ no grants (already refused in `_bind_tenancy`). | existing |
| Every grant/revoke/role-permission edit writes `record_activity` with before/after. | services |

### 4.9 System roles, grant modes and templates (replaces the pasted seed — B1 fixed)

`roles.grant_mode`:

| Mode | Meaning | Roles |
|---|---|---|
| `all` | every catalogue permission, **computed at evaluation** | `owner` |
| `all_but_owner_only` | every permission not flagged `owner_only` (tenant settings, deleting an organization, granting `owner`) | `admin` |
| `explicit` | exactly the rows in `role_permissions` | everything else, including all custom roles |

Why computed rather than seeded rows (R3): with rows, every release that adds a permission must re-sync every
organization's `owner` and `admin`, and every sync competes with operator edits. Computed, they are always
current; and it preserves today's behavior, where `admin` and `owner` are interchangeable to `TenantAdmin`.

Explicit template roles are seeded per organization by the existing `seed_system_roles` (its `SYSTEM_ROLES`
grows from 3 to 6 entries), **additive only** — a template permission missing from an organization's copy is
added by `scripts/seed.py rbac`; nothing is ever removed unless `--prune` is passed. Codes are lower snake case
(B5).

| Template | Was in paste | Grants (illustrative; matrix in Appendix B) |
|---|---|---|
| `owner` | `SUPER_ADMIN`* | `all` |
| `admin` | `ORG_ADMIN` | `all_but_owner_only` |
| `department_head` | `DEPARTMENT_HEAD` | `teams.department:read/update`, `teams.team:read`, `teams.membership:assign/approve` |
| `team_manager` | `TEAM_MANAGER` | `teams.team:read/update`, `teams.membership:assign/approve` |
| `auditor` | `AUDITOR` | every `:read`, `activity.log:read/export`, nothing else |
| `member` | `TEAM_MEMBER` (existing role kept) | `teams.team:read`, `teams.department:read` |

\* `SUPER_ADMIN` in the paste means "platform-wide". That is **not a tenant role** — it stays
`PLATFORM_ADMIN_EMAILS` (`PlatformAdmin`), outside this schema. A platform admin keeps today's `TenantAdmin`
bypass on `Perm` routes (R12): platform staff act inside a tenant's context; every such call is audited with
`actor_type` visible in `activity_logs`.

---

## 5. Teams and organizational structure

### 5.1 Departments
Org-owned tree. `head_of_department_user_id` is a tenant-safe FK to users. Tree columns
(`_lft/_rgt/depth/path/position`) are written **only** by `teams.service._recompute_tree(kind, org)`, which takes
`pg_advisory_xact_lock(hashtextextended('dept_tree:{tenant}:{org}',0))`, loads that organization's rows and calls
`app.common.tree.recompute_bounds` — exactly `categories._recompute_tree`. A `TreeError` becomes
`TeamsRuleError`. `move` = set `parent_id` then recompute (no bespoke path rewrite needed at these sizes; if a tree
ever exceeds a few thousand nodes, switch to `organizations.move_organization`'s single-`UPDATE` approach).
Cost centre stays a plain code column.

### 5.2 Job titles
Org-owned catalogue, optionally tied to a department, `band_level`, `is_management`. Replaces free-text
`designation`. A one-off backfill script (§7.4) proposes titles/departments from the distinct existing strings; a
human reviews it before it writes.

### 5.3 Team types, team roles, teams
* `team_types` — a classification tree (e.g. *Delivery → Last-mile*), same tree routine. `default_team_role_id`
  is added after `team_roles` exists (circular FK; nullable).
* `team_roles` — what a member *is* in a team (lead, coordinator). `rbac_role_id` optionally maps it to an RBAC
  role **whose permissions apply to that team** — the single mechanism (B8).
* `teams` — org-owned, hierarchical, optional department/lead. `team_type_id` is `RESTRICT`.

### 5.4 Membership lifecycle (`user_teams`)
```
pending ──approve──► approved ──(valid_until reached / end)──► ended
   └──reject/cancel──► rejected / cancelled
```
* A membership grants nothing until `approval_status = 'approved'` **and** `status = 'active'` **and** now ∈
  `[valid_from, valid_until)`. Enforced in the grant loader, not by cleanup jobs.
* Joining/leaving is history: leaving closes `valid_until`; rejoining inserts a new row (the open-membership
  unique index and the no-overlap `EXCLUDE` allow it — the lesson of B3, and of the `place_links` dedupe bug).
* One **primary** team per user at a time (partial unique, tenant-scoped, open rows only).
* Cross-org membership within a tenant is allowed (D11): the membership's org is the **team's** org (composite
  FK); it is visible/grantable only to actors whose scope covers that org.
* `approved_by` must differ from the member (no self-approval) and hold `teams.membership:approve` in scope.

### 5.5 Reporting lines and employment (D4)
Reuse `hr.employment_records`; do not add `user_organization_profiles`.

| Pasted column | Existing home |
|---|---|
| `user_id`, `is_current` (one current) | `employment_records.user_id`, `is_current`, `uq_employment_records_one_current` |
| `start_date` / `end_date` | `date_of_joining` / `date_of_exit` (+ `chk_employment_dates`) |
| `probation_end_date` / `confirmation_date` | `probation_period_days` / `date_of_confirmation` |
| `reports_to_user_id` | `reporting_manager_user_id` |
| `employment_type/status` | `employment_type/status` (hr enums are richer than the paste's) |
| `department_id`, `job_title_id` | **new columns** (the only additions) |
| `department_location_id` | none — `hub_id` (ops staff) or an office `place_link` on the user |

**New work this implies (F8):** `hr` has no service or API, and nothing writes `employment_records`. Phase 4
therefore includes a small `hr/service.py` + `hr/api.py`: create/end an employment stint, set placement
(department, job title, manager), read the org chart. That is real scope — it is why Phase 4 is 5 days, not 4.

**Cheaper alternative (D4b):** put `department_id`, `job_title_id` (and a manager) directly on `users`. It works
without an employment record and is ~1 day less, but it is the wrong shape (it puts history-less HR facts on the
authentication hot row and duplicates `employment_records`), so I do not recommend it.

Caveats: `employment_records.employee_code` is `NOT NULL`, so people with no employment (customers, some
partners) simply have no row — team membership does not require one. Reporting cycles are refused in the service
(walk up the manager chain, capped at 100) with a `reporting_manager_user_id <> user_id` CHECK; no trigger.
"Manager sees their reports" needs a reporting closure; that is a **query** (recursive CTE) with the same
cache as grants, not another materialized table — deferred to Phase 6.

Legacy `users.department` / `users.designation` become read-through from the current employment record, then are
dropped in Phase 7.

### 5.6 Where departments and teams sit (addresses) — R1
No table. A department or team's location is a `geo.place_links` row:

* `owner_type = 'department' | 'team'` (add both to `geo.model.link.OWNER_TYPES` and the CHECK
  `chk_place_link_owner_type` in the migration — the extension point `geo`'s docstring describes; that CHECK has
  never been altered since it was created, so the migration drops and re-creates it);
* `link_type = 'office'` (or `site`), the place `kind = 'office'` (both values already exist);
* floor / room / desk in the link's `custom_attributes`; a contact in `attention`;
* via the existing `/api/addresses` — no new endpoint, and it automatically gets effective dating, snapshots and
  the duplicate-place reuse.

An employee's work location is `employment_records.hub_id` for operations staff, or an `office` link on the user.

### 5.7 Capabilities that come for free (R9)
Register `department`, `team`, `job_title` in `core.entity_types` (the migration inserts the rows, as the brands
migration did). That immediately lets custom fields, categories/taxonomies, aliases and tax assignments attach to
them, with the registry's existence checks. `Department`/`Team` add `HasCustomFieldsMixin` (with
`custom_fields_owner_type`) and `HasTagsMixin` — one line each, no schema change.

---

## 6. API surface (proposed)

Conventions per §3.5. Only *writes and sensitive reads* are permission-gated in Phase 3 (F7); reference-data
reads stay `CurrentUser`.

| Route | Purpose | Permission |
|---|---|---|
| `GET /api/permissions` | the catalogue (grouped by module) | `rbac.role:read` |
| `GET /api/roles`, `/{ref}` | *(exists)* now with computed `permissions` | any signed-in / `rbac.role:read` |
| `PUT /api/roles/{ref}/permissions` | replace a **custom** role's permission set (diff-applied, audited) | `rbac.role:manage` |
| `POST /api/roles/{ref}/clone` | copy a system role into a custom one (optionally into a child org) | `rbac.role:create` |
| `GET/POST /api/users/{id}/roles`, `DELETE …/{assignment}` | contextual assignments | `rbac.assignment:assign` (+ §4.8) |
| `PUT /api/users/{id}/base-role` | change `users.role_id` (replaces `role_id` in `UserUpdate`) | `users.user:assign_role` |
| `GET /api/me/permissions` | effective grants for the UI | any signed-in |
| `GET/POST/PATCH/DELETE /api/departments`, `/tree`, `/{ref}/children`, `POST /{ref}/move` | departments | `teams.department:*` |
| `…/api/job-titles` | job titles | `teams.job_title:*` |
| `…/api/team-types`, `…/api/team-roles` | classification and roles | `teams.team_type:*`, `teams.team_role:*` |
| `…/api/teams`, `/tree`, `/{ref}/children`, `POST /{ref}/move` | teams | `teams.team:*` |
| `GET/POST /api/teams/{ref}/members`, `PATCH/DELETE …/{id}`, `POST …/{id}/approve\|reject` | membership | `teams.membership:*` |
| `GET /api/me/teams` | my memberships | any signed-in |
| `POST /api/hr/employment`, `PATCH /api/hr/employment/{id}`, `GET /api/hr/org-chart` *(new hr API)* | stint, placement, chart | `hr.employment:*` |
| `/api/addresses` with `owner_type=department\|team` *(exists)* | where a department/team sits | `geo.address:*` |

---

## 7. Migration and rollout

### 7.1 Alembic migrations (hand-written; reversible except where noted)

| Rev | Content |
|---|---|
| **M1** `rbac_catalogue` | `CREATE SCHEMA rbac`; `permissions` (GLOBAL); `role_permissions`; `roles`: + `hierarchy_level`, `is_assignable`, `grant_mode`, `uq_roles_tenant_id`, status CHECK += `deprecated`; `seed_permissions`; set `grant_mode` on existing `owner`/`admin` rows; **backfill** `role_permissions` from `roles.permissions` JSON where the code is in the catalogue (unknown codes kept in `app_metadata.legacy_permissions` and logged); explicit template rows for existing organizations |
| **M2** `teams_structure` | `CREATE SCHEMA teams`; `departments`, `job_titles`; `OWNER_TYPES` CHECK re-created with `department`,`team`; `core.entity_types` rows |
| **M3** `teams_teams` | `team_types`, `team_roles`, `teams`, `user_teams`; deferred FK `team_types.default_team_role_id`; `EXCLUDE` constraints (needs `btree_gist`, already installed for `place_links`) |
| **M4** `rbac_assignments` | `rbac.user_roles` |
| **M5** `employment_links` | `employment_records` + `department_id`, `job_title_id`, CHECK; backfill *proposals* are **not** part of the migration |
| **M6** *(Phase 7, irreversible data step)* | drop `roles.permissions`; drop `users.department/designation`; back up first (same warning as the tenancy migration) |

No functions or triggers in M2–M4 (R2) — everything else is plain DDL, which keeps `alembic revision
--autogenerate` drift checks useful. Add `teams`, `rbac` to `alembic/env.py::_OWNED_SCHEMAS`; add the new tables to
`tests/conftest.py::_TEST_TABLES`; Debezium/search only where Phase 7 needs them.

### 7.2 Compatibility contract while rolling out
* `TenantAdmin`, `PlatformAdmin`, `ZohoOperator` keep their names and import paths for the whole migration.
* `RoleOut.permissions` keeps its shape.
* `worlds`/`build_world` fixtures keep working: `acme.admin` holds the `admin` role, whose `all_but_owner_only`
  mode needs no rows — so **no fixture change** (a reason for R3).
* `dev-token` user (DEBUG only): assigned the `owner` role of the default org so local development still works
  once enforcement is on.
* Self-registered users: **D12** — assign `member` in the default org on registration (today they get NULL).

### 7.3 Shadow mode (the safety net)
`RBAC_ENFORCEMENT = off | shadow | enforce` (setting in `core/conf.py`, `.env.example` **and** the compose
`environment:` block — §3.5).
* `shadow`: every guarded route runs **both** the old rule and `allowed(…)`; the old rule decides; a
  disagreement logs `rbac_shadow_mismatch` (user, route, permission, old, new) and increments a counter.
* Promote a module to `enforce` only after a period with zero unexplained mismatches.
* Expected, *explainable* mismatches: a branch admin who used to pass tenant-wide `TenantAdmin` routes now fails
  outside their subtree (the intended fix for F3); role-less users.

### 7.4 Backfill scripts (dry-run first, human-reviewed)
1. `department`/`designation` strings from `users` + `employment_records` → proposed `departments` / `job_titles`
   per organization → link `employment_records`.
2. Existing `owner`/`admin`/`member` holders keep their base role — no data change.
3. Report of users with `role_id IS NULL` (they will hold no grants).

---

## 8. Phased plan

| Phase | Deliverable | Acceptance | Size |
|---|---|---|---|
| **0 — Close the hole** | Gate `POST/PUT/DELETE /users*`, restore, ban/unban/throttle/unthrottle with `TenantAdmin`; remove `role_id/status/user_type/is_deactivated` from the self-reachable path (`UserUpdate` → `UserAdminUpdate`); tiered output: `UserPublicOut` (id, name, avatar) for peers, full `UserOut` for self/admin; verify prod `DEBUG=false` and set `PLATFORM_ADMIN_EMAILS`/`ZOHO_OPERATOR_EMAILS` | a non-admin gets 403 on every mutation; `GET /users` as a member returns no `medical_history`/`pan`/`bank_details`; tests for both | S |
| **1 — Catalogue & engine** | `rbac.permissions`, `role_permissions`, registry + `seed_permissions` + boot check, `roles` columns + `grant_mode`, evaluator (**tenant + organization scopes**), Redis cache + epoch + TTL clipping, `Perm`, `/api/me/permissions`, `/api/permissions`, role-permission edit API, explicit templates, static route-check test, `lang/en.py` | scope-matching/`manage`/`grant_mode`/cache tests; catalogue migration up-down-up; conformance green; **no behavior change** (`off`) | L |
| **2 — Assignments & guardrails** | `rbac.user_roles`, assign/revoke API, base-role endpoint, all §4.8 rules, audit | escalation, level check, last-owner, self-edit, cross-tenant tests | M |
| **3 — Enforcement rollout** | `shadow` → `enforce` per module using Appendix A; `TenantAdmin` reimplemented on `Perm`; `ZohoOperator` → `zoho.integration:manage`; `dev-token`/registration role policy | shadow mismatch report clean; every module's tests pass under `enforce`; branch-admin-outside-subtree test | L |
| **4 — Org structure** | move `tree.py` to `app/common`; `departments`, `job_titles`; `hr` employment service + API; `employment_records` links; department scope in the evaluator; `OWNER_TYPES` extension; entity-type registration; backfill script | tenant isolation + composite-FK tests; tree recompute/cycle tests; department-scoped grant test; an address attached to a department | L |
| **5 — Teams** | `team_types`, `team_roles`, `teams`, `user_teams` + approval, team scope in the evaluator, `/api/me/teams` | membership history/rejoin, no self-approval, expiry, primary-team uniqueness, team-role grant appears and disappears with membership | M |
| **6 — Data scope (optional)** | `data_scope` on `role_permissions` (`own / team / department / org / org_tree / tenant`) + a `scope_filter()` helper modules apply to list queries; reporting closure | list endpoints honor scope; perf test on the closure query | L |
| **7 — Hardening** | search/CDC registration, drop legacy columns (M6), docs (`tenancy/README.md` §6/§9 → `docs/rbac/README.md`), frontend contract, runbook | docs updated; open items #1/#4 closed | M |

Phases 1→2→3 are strictly ordered; 4 and 5 can proceed in parallel after 1 (department and team scopes are added
to an evaluator that already handles tenant/org).

---

## 9. Testing strategy

**Unit** — scope matching (org exact/descendant/sibling, tenant, department/team id-set, fail-closed on missing
target); `manage` expansion; `grant_mode`; window/approval logic and **cache TTL clipping**; escalation and level
guards; permission-code generation and format; the moved tree routine (the existing
`tests/test_categories_tree.py` must pass unchanged through the re-export).

**Integration** — `worlds` (two tenants) for isolation: for **every** new endpoint, tenant B cannot see, edit or
reference tenant A's row (404, plus a raw composite-FK violation attempt). Add a **`tree_world`** fixture (R11):
one tenant with holding → branch A / branch B and an admin at each level, because `build_world` builds a single
flat organization and cannot express "a branch admin cannot act on a sibling branch" or "a holding admin
reaches both". `X-Organization-Code` must not widen authority. `TenantAdmin` decisions unchanged in `off`/`shadow`.

**Database** — composite FK refuses cross-tenant and cross-org parents; live-unique indexes allow code reuse after
soft delete; membership/assignment history allows re-join; `EXCLUDE` refuses overlapping windows; migration up →
down → up on the scratch DB (start it on a port outside Windows' reserved range — 55428–55527 is reserved on the
dev machine, which is why `.dev_scratch.sh`'s 55432 fails to publish).

**Conformance / static** — new tables pass `test_every_table_is_entity_ledger_or_an_explained_global` (with the
`rbac.permissions` GLOBAL entry and its reason); import contracts and cycles; every `Perm(...)` code exists in
the registry.

**Regression** — full suite under `RBAC_ENFORCEMENT=enforce` before flipping the default. Test-DB hygiene per the
existing rule: reference data comes from migrations only; never seed the pytest DB.

---

## 10. Decisions needed (recommendation first)

| # | Decision | Recommendation | Alternative and its cost |
|---|---|---|---|
| **D1** | Roles table | **Evolve `public.roles`** | New `rbac.roles`: forks `users.role_id`, CDC, seeding, API and every fixture |
| **D2** | Who owns a role definition | **Organization-owned (as today)**, usable within that org's subtree; "clone to child org" as a convenience | Tenant-level templates with NULL org: `roles.organization_id` becomes nullable, breaking the `users → roles` composite FK invariant |
| **D3** | Scope of the *base* role | **Home organization + descendants** | Home org only (safer, but a holding admin loses the branches); whole tenant (today's behavior, keeps F3) |
| **D4** | Employment/reporting | **Extend `hr.employment_records` and build its missing API** | D4b: columns on `users` (−1 day, wrong shape); or a new `user_organization_profiles` (two authoritative employment tables) |
| **D5** | Department locations | **No table — `geo` office places + `place_links` with `owner_type` department/team** (R1) | Keep a thin `workplaces` table: +1 table/API, a third "locations" concept |
| **D6** | Target/incentive cache columns | **Keep, nullable, read-only, no logic** | Omit until the engine exists |
| **D7** | Does being department head / team lead grant a role? | **No** — roles only | Auto-grant rule (`auto_grant_role_id`) later |
| **D8** | Nested set `_lft/_rgt` | **Keep, maintained by the shared `recompute_bounds`; no cycle triggers** (reverses my first draft) | Path only: fewer columns, but you asked for them preserved and the routine already exists |
| **D9** | Enforcement rollout | **Shadow first, then per-module enforce** | Big-bang: fastest, but a lockout risk |
| **D10** | Row-level data scope (Phase 6) | **Later, hook designed now** (`data_scope` column reserved) | Include now: +5 days, touches every list query |
| **D11** | Cross-org team membership in a tenant | **Allowed**; membership org = team org | Same-org only: simpler; blocks matrix teams |
| **D12** | Default role on self-registration | **`member` in the default org** | NULL as today: zero grants, but reads of gated data break for them |
| **D13** | `owner`/`admin` as computed grant modes; catalogue seeded insert-missing with a boot check | **Yes** (R3) | Seed rows per organization per release: more sync code, fights operator edits |

Also confirm: moving `categories/tree.py` to `app/common/tree.py` with a re-export shim (touches `categories`
imports only); and that Phase 0 may start immediately.

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| Lock-out of legitimate admins at enforcement | Shadow mode (§7.3); the last-owner invariant; a break-glass CLI to grant `owner` |
| Semantic change "branch admin ⇒ tenant admin" | Intended (F3); surfaced explicitly in shadow logs; D3 chooses how much authority a holding-level role keeps |
| Grant cache staleness | Epoch bump on every structural change + TTL clipped to validity boundaries; per-user delete on assignment/membership changes; DB fallback |
| Organization move / tree change under cached scopes | Epoch bump in `organizations.move`/archive and in the department/team recompute |
| Full-recompute tree cost | Per-(tenant, org) trees are small; `categories` runs the same design; escape hatch is the single-`UPDATE` move used by organizations |
| Permission catalogue drift / typos | Code-owned registry, boot insert-missing, static route test |
| Wide mechanical change in Phase 3 (14 modules) | Per-module PRs behind `shadow`; Appendix A is the checklist |
| SSO (Authentik JIT) users arrive with `role_id NULL` | Zero grants until mapped; future work: Authentik group → role mapping (there is none today) |
| Scope creep from the pasted target/incentive columns | D6 — columns only, no logic |
| Building `hr` service/API surfaces unknown requirements (onboarding stages, statutory fields) | Phase 4 exposes only placement + stint lifecycle; statutory/onboarding stay out |
| Migration on production data | Rehearse on a copy (as the tenancy migration was); M6 is the only irreversible step and is last |

---

## Appendix A — `TenantAdmin` call sites → proposed permissions

Modules that import `TenantAdmin` today (verified by grep). Per-route assignment is done in Phase 3; the
module-level mapping below is the starting checklist.

| Module | Today | Proposed (writes) |
|---|---|---|
| roles | `TenantAdmin` | `rbac.role:create/update/delete/manage` |
| organizations | `TenantAdmin` | `org.organization:create/update/delete/manage` (`move`, `status` = `manage`) |
| custom_fields | `TenantAdmin` | `extfields.definition:manage` |
| geo (+ geocoding) | `TenantAdmin` | `geo.place:*`, `geo.address:*`, `geo.geofence:*`, `geo.geocoding:manage` |
| currencies | `TenantAdmin` | `currency.currency:manage` |
| taxes (assignments) | `TenantAdmin` | `tax.assignment:manage` |
| accounting *(new, 2026-10-08)* | — | `accounting.account:create/update/delete`, `accounting.assignment:manage` |
| resolution policies *(new, 2026-10-08)* | — | `resolution.policy:manage` |
| brands / manufacturers / categories / entities | `TenantAdmin` | `core.<resource>:create/update/delete` |
| documents (verify, request resubmission) | `TenantAdmin` | `documents.document:verify` |
| hubs / fleet_partners / vehicles | `TenantAdmin` | `hubs.hub:*`, `fleet.partner:*`, `fleet.vehicle:*` |
| users *(unguarded today — F1)* | `CurrentUser` | `users.user:create/update/delete/restore`, `users.user:assign_role`, `users.moderation:manage` |
| zoho admin | `ZohoOperator` | `zoho.integration:manage` |
| tenants | `PlatformAdmin` | **stays** `PlatformAdmin` (platform level, outside RBAC) |
| activity / hr / kyc (sensitive reads) | `CurrentUser` | `activity.log:read`, `hr.employment:read`, `kyc.profile:read` |

## Appendix B — role × permission matrix (teams / rbac subset, corrected from the paste)

`✔` granted · `–` not granted · `∗` computed by `grant_mode` (no rows). (`manage` = create/read/update/delete.)

| Permission | owner | admin | department_head | team_manager | auditor | member |
|---|---|---|---|---|---|---|
| `teams.team:manage` | ✔∗ | ✔∗ | – | – | – | – |
| `teams.team:read` | ✔∗ | ✔∗ | ✔ | ✔ | ✔ | ✔ |
| `teams.team:update` | ✔∗ | ✔∗ | – | ✔ | – | – |
| `teams.membership:assign` | ✔∗ | ✔∗ | ✔ | ✔ | – | – |
| `teams.membership:approve` | ✔∗ | ✔∗ | ✔ | ✔ | – | – |
| `teams.department:manage` | ✔∗ | ✔∗ | – | – | – | – |
| `teams.department:read` | ✔∗ | ✔∗ | ✔ | – | ✔ | ✔ |
| `teams.department:update` | ✔∗ | ✔∗ | ✔ | – | – | – |
| `rbac.role:manage` | ✔∗ | ✔∗ | – | – | – | – |
| `rbac.assignment:assign` | ✔∗ | ✔∗ | – | – | – | – |
| `org.settings:manage` (`owner_only`) | ✔∗ | – | – | – | – | – |

(In the paste, `departments:*` was granted to every role by the precedence bug — B1.)

## Appendix C — sketches (illustrative, not final)

```python
class Department(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasCustomFieldsMixin, HasTagsMixin,
                 SoftDeleteFilteredMixin, Base):
    __tablename__ = "departments"
    custom_fields_owner_type = "department"          # a row in core.entity_types
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_departments_tenant_org_id"),
        Index("uq_departments_code_live", "tenant_id", "organization_id", "department_code",
              unique=True, postgresql_where=text("deleted_at IS NULL")),
        ForeignKeyConstraint(                       # a parent must be in the same tenant AND organization
            ["tenant_id", "organization_id", "parent_id"],
            ["teams.departments.tenant_id", "teams.departments.organization_id", "teams.departments.id"],
            name="fk_departments_parent", ondelete="RESTRICT"),
        ForeignKeyConstraint(                       # users has uq_users_tenant_id
            ["tenant_id", "head_of_department_user_id"], ["users.tenant_id", "users.id"],
            name="fk_departments_head", ondelete="RESTRICT"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="chk_departments_not_own_parent"),
        CheckConstraint("_rgt >= _lft", name="ck_departments_nested_set_bounds"),
        Index("ix_departments_scope_lft_rgt", "tenant_id", "organization_id", "_lft", "_rgt",
              postgresql_where=text("deleted_at IS NULL")),
        {"schema": "teams"},
    )
    department_code: Mapped[str] = mapped_column(String(50), nullable=False)
    department_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(BigInteger)
    head_of_department_user_id: Mapped[int | None] = mapped_column(BigInteger)
    # tree columns — written ONLY by teams.service._recompute_tree (app/common/tree.py)
    is_root: ...; depth: ...; path: ...; lft = mapped_column("_lft", Integer, ...); rgt = mapped_column("_rgt", ...); position: ...
```

```python
# rbac/catalog.py — the registry modules feed
@dataclass(frozen=True)
class Permission:
    module: str; resource: str; action: str; description: str = ""; owner_only: bool = False
    @property
    def code(self) -> str: return f"{self.module}.{self.resource}:{self.action}"
```

```python
# teams/service.py — the only writer of tree columns (mirrors categories._recompute_tree)
async def _recompute_tree(db, model, *, tenant_id, organization_id, kind) -> None:
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                     {"k": f"{kind}_tree:{tenant_id}:{organization_id}"})
    rows = await crud.live_rows(db, model, organization_id)
    try:
        tree.recompute_bounds(rows)                 # app.common.tree
    except tree.TreeError as exc:
        raise TeamsRuleError(str(exc)) from exc
    await db.flush()
```

---

## 12. Implementation status (2026-09-26)

**Migration** `807ccba816ef` (reversible; run `alembic upgrade head`). **Code:** `app/modules/{rbac,teams}` (new),
`roles` and `hr` (extended), `app/common/tree.py` (moved from categories). **Tests:** `test_rbac_engine`,
`test_rbac_api`, `test_teams_api`, `test_rbac_routes`, `test_rbac_context`, `test_tenant_bootstrap`.

### 12.1 Decisions taken

| # | Decision | Outcome |
|---|---|---|
| D1 | roles table | `public.roles` extended (`grant_mode`, `hierarchy_level`, `is_assignable`); the `permissions` JSONB was backfilled into `rbac.role_permissions` and dropped |
| D2 | who owns a role | the organization; usable in its subtree |
| D3 | base role reach | home organization + descendants |
| D4 | employment | `hr.employment_records` + a new `hr` service/API (`/api/hr/employment`, `/org-chart`) |
| D5 | department/team locations | `geo.place_links` (`owner_type` `department` / `team`, `kind='office'`, floor/room in `custom_attributes`) — no table |
| D6 | target/incentive fields | kept, nullable, **output-only**, no logic |
| D7 | head/lead grants | no — permissions come from roles only |
| D8 | nested set | kept; maintained by `app/common/tree.py`, no cycle triggers |
| D9 | shadow mode | **not built** (you decided against it): RBAC is enforced on every module |
| D10 | data scope | designed, **not implemented** (§12.4) |
| D11 | cross-org membership | allowed; the membership's organization is the team's |
| D12 | self-registered role | `member` |
| D13 | owner/admin | computed `grant_mode`; catalogue seeded insert-missing (migration + boot check) |

### 12.2 Beyond the plan — issues raised in review, and how they were closed

| Issue | Resolution |
|---|---|
| **Two guard paradigms** (declarative `Perm` vs imperative `require`) | There is now ONE: `Perm(code[, target=…])`. Resource-level checks are declarative too — `target=` names a dependency that loads the row named in the path and returns the `Target` (organization/department/team) the permission is judged at. `org_of("module:Model", …)` builds one for any model; teams, roles, organizations, users and hr have dedicated ones. `tests/test_rbac_routes.py` fails the build if a mutating route has no `Perm` (and is not on the reasoned allow-list), or if a row-level route has no `target=`. A `Perm` with an unknown code refuses to import. |
| **Circular FK** `team_types.default_team_role_id` ↔ `team_roles.team_type_id` | Removed: `team_roles.is_default` (one per team type, partial unique) replaces the column. No deferred FK, no cascade lock. |
| **Background tasks / consumers** | `rbac/context.py`. Services never authorize (the HTTP edge does). System jobs run as `system:<component>` (`system_scope`), unevaluated and trusted. User-initiated jobs carry the **actor's id** (never credentials, never a permission decision) and re-evaluate at **execution time** with `acting_as` / `check_actor` — a grant revoked while the job queued stops the job. Kafka/FastStream consumers are system actors; a message asking for something a user is entitled to do goes through `check_actor`. |
| **Bulk / batch operations** | A bulk call is a batch of the SAME declared permission, authorized **per item against that item's own target** (`Grants.allows_many` / `require_all`). Default all-or-nothing (any denied item → 403 listing `denied_indexes`, nothing written); `?partial=true` applies the permitted items and reports `denied` and per-item `errors`. Batches are capped (`BULK_LIMIT` = 200). Reference: `POST /api/teams/members/bulk`. |
| **Authentik/SSO users locked out on day 1** | Decided up front: `provision_from_authentik` gives the same default `member` role as registration; the migration also backfilled every existing role-less user to `member` of their organization. (Authentik-group → role mapping is future work.) |

### 12.3 Deviations from §0–11

* The permission catalogue is **one audited file** (`rbac/catalogue.py`), not a list per module.
* `TenantAdmin` remains as a deprecated alias for `Perm("org.organization:manage")`; `ZohoOperator` for `zoho.integration:manage`; the `ZOHO_OPERATOR_EMAILS` allow-list is retired. `PlatformAdmin` stays outside tenant RBAC (still: empty list + `DEBUG` = anyone — **check prod `DEBUG=false`**).
* Tree bounds are written with a Core `UPDATE` that does **not** bump `row_version`, so adding a sibling never makes a client's copy of another node stale.
* Creating a tenant **always** creates its root organization, seeds that organization's roles and creates an initial administrator: an `owner` of the organization **and** the tenant-wide owner (may create further organizations, including new roots). `POST /api/tenants` accepts `admin_email` / `admin_name` / `admin_password`; without a password a strong temporary one is generated and returned **once**.
* Creating an organization is judged at its **parent**; a new **root** organization is a tenant-level act (`Target(tenant_level=True)`) that only a tenant-wide grant covers; moving needs authority over both the node and the destination.
* Sensitive **reads** are gated, not only writes (users' full record, activity log, documents, emails, hr, Zoho admin). Reference-data reads stay open to any signed-in user. `GET /api/users` is two-tier: the directory (`UserPublicOut`) for `users.directory:read`, the full record for `users.user:read` or your own.
* A user's role can no longer be set through `PUT /users/{id}` / `POST /users` (422); use `PUT /api/users/{id}/base-role`.

### 12.4 Not implemented — documented on purpose

| Item | State |
|---|---|
| **Row-level data scope** (Phase 6: `own / team / department / org / org_tree / tenant` filters on list endpoints; the reporting-line closure) | Not built. Permissions decide *whether you may act*; **reads remain tenant-wide** (organization is stamped on writes, not filtered on reads — tenancy doc F6). Consequence today: a holder of `teams.team:read` sees every team in the tenant, and documents/emails/users' full record are gated by permission but not by ownership (a member cannot read even their own documents — self-service reads of own rows need this phase). **Design hook:** `Target` already carries organization/department/team; add a `data_scope` column on `rbac.role_permissions` and a `scope_filter()` helper that list queries apply. |
| Field planning permissions (2026-10-06) | `fieldops.shift:create` (schedule shifts), `fieldops.visit:create` (plan stops), `fieldops.shift_template:*`, `hubs.assignment:read/manage` (the hub of the day), `users.session:read/delete` (see and end a user's sign-in sessions). `team_manager` and `department_head` gained the planning set (`shift:create/update`, `visit:create/update`, `shift_template:read`, `hubs.assignment:*`) — migration `c3d9a7e2f415` grants it to existing system roles. `fieldops.policy:*` now governs policy layers. |
| Field operations' interim scope (2026-09-29) | Location data could not wait for data scope: `app/modules/fieldops/scope.py` narrows managers' reads of shifts, visits, tracks and the live map to the organizations / teams their grant of the permission covers, plus their direct reports. It reads the same `Grants` the guard used, so it is the natural first consumer to replace with `scope_filter()`. Catalogue additions: `fieldops.field_work:use` (member), `fieldops.telephonic_visit:create` (no template — granted per organization role), `fieldops.shift/visit:*` and `fieldops.anomaly:read/approve` (team_manager, department_head: read + approve), `fieldops.policy:*`; `team_manager` and `department_head` also gained `users.location:read`. |
| Authentik group → role mapping | future |
| Postgres row-level security (tenancy open item #5) | future |
| `hr` statutory/payroll/onboarding endpoints | out of scope; the employment API exposes placement and stint lifecycle only |
| Search/CDC registration of departments/teams | not registered (add to `search/registry.py` and Debezium `table.include.list` when needed) |
| Frontend contract for `/api/me/permissions` | backend only |

### 12.5 Operating notes

* **Deploy:** `alembic upgrade head`. New env var `RBAC_CACHE_TTL_SECONDS` (default 300; 0 disables) is in `core/conf.py`, `.env.example`, `.env.prod.example` and — because compose passes variables explicitly — `deployment/docker-compose.yml`.
* **Cache:** grants live in Redis (`rbac:grants:{tenant}:{user}`), invalidated by a per-tenant epoch bumped on every role/permission/tree/status change and per-user on assignment/membership change; TTL is clipped to the next grant start/expiry. Redis down → falls open to the database.
* **Lock-out recovery:** the break-glass is a platform administrator (`PLATFORM_ADMIN_EMAILS`), who passes every check; grant `owner` from there. The last active owner of an organization cannot be demoted, banned, deactivated or deleted.
* **Known behaviour change:** an `admin` of a branch is no longer an administrator of the whole tenant (finding F3).
