# Tenancy — tenants, organizations, roles, and how every table is scoped

**Status:** ✅ live · **Migration:** `7c2e91d4b0a8` (irreversible — back up first) ·
**Code:** `app/database/mixins.py`, `app/database/tenancy.py`, `app/modules/{tenants,organizations,roles}/` ·
**Tests:** `tests/test_tenancy.py`, `test_organizations_api.py`, `test_tenants_roles_api.py`,
`tests/zoho_core/test_masters_e2e.py`

---

## 1. Model

```
org_management.tenants (root, GLOBAL)          a customer account: code, status trial/active/suspended/cancelled
└── org_management.organizations (tree)        holding → legal entities → branches (+ standalone "solo")
      tenant_id + parent_id, materialized path /uuid/uuid/, depth
every tenant table                             tenant_id NOT NULL  +  organization_id NULL (= tenant-wide)
```

* A tenant can have **many** organizations (many roots, many trees).
* **Isolation lives in the database**, not only in the app:
  * `tenant_id` → `tenants(id)` RESTRICT;
  * composite FK `(tenant_id, organization_id)` → `organizations(tenant_id, id)`: a row can
    never point at another tenant's organization, even through raw SQL;
  * the tree uses the same trick for `(tenant_id, parent_id)`;
  * users hold roles through `(tenant_id, role_id)` → `roles(tenant_id, id)`.
* A **Zoho organization is a node** of this tree: a root legal entity with `zoho_id`, created
  by the Zoho organizations sync. It replaces the v1 `zoho_organizations` mirror, whose rows
  the migration moved.

## 2. Mixins (`app/database/mixins.py`)

| Mixin | Columns | Notes |
|---|---|---|
| `TenantScopedMixin` | `tenant_id`, `organization_id` (+ composite FK and index added per table) | stamped and filtered by tenancy.py; `organization_id` NULL = tenant-wide |
| `MultiTenantMixin` | the same, but `organization_id` **NOT NULL** (and `ondelete=CASCADE`) | strict scope: the composite FK is checked on every row instead of being skipped on NULL. Used by the [location hub](../geo/README.md); callers resolve the organization with `require_organization` so the failure is a 422, not an IntegrityError |
| `VerificationMixin` | `verification_status`, `verification_method`, `verification_data`, `verified_by`, `verified_at` | the nuance `is_verified` cannot carry — `geocoded_only` is not `field_verified` |
| `AuditMixin` | `created_by`, `created_by_name`, `updated_by`, `updated_by_name` | `*_name` is denormalised (history reads without a join, survives the user being deleted); system writers use `created_by = NULL`, `created_by_name = 'system:<component>'`. `updated_by` and `updated_by_name` are stamped together and only when a user is acting, so a system write never leaves the pair disagreeing |
| `StatusMixin` | `status` (default `active`), `is_verified` | tables add a CHECK for their values; a Zoho-owned status is mirrored as `zoho_status` |
| `RowVersionMixin` | `row_version` | SQLAlchemy optimistic lock + `eager_defaults` (see §4) |
| `SoftDeleteMixin` / `SoftDeleteFilteredMixin` | `deleted_at`, `deleted_by`, `deleted_reason` | `soft_delete(reason=, by=)`, `restore()` |
| `AppMetaMixin` | `app_version`, `app_metadata` (JSONB) | `app_version` stamped from `settings.VERSION` on every write |
| `DeactivationMixin` | `deactivation_date`, `deactivation_reason`, `deactivated_by` | reversible, distinct from delete; on users, organizations, currencies, taxes, places, addresses, geofences. `deactivation_date IS NULL` is the single source of truth — there is deliberately no `is_active` boolean beside it (see below) |
| `PolymorphicOwnerMixin` | `owner_type` (String 50), `owner_id` (BigInteger), both NOT NULL, **no FK** | "this row belongs to some entity": addresses, notes, attachments, contacts. `owner_ref` → `(type, id)`. The database no longer checks the owner, so each table adds a CHECK over its closed set of types and a composite index `(tenant_id, owner_type, owner_id)`. No per-column indexes (see below). Worked example (same two columns, declared by hand before the mixin existed): `geo.place_links` and its `OWNER_TYPES` |
| `HashGuardMixin` | `content_hash` (String 64, sha256 hex, nullable) | hash-guarded upsert: an unchanged record writes nothing — no `updated_at`, no `row_version` bump, no CDC event. `HashGuardMixin.hash_content(payload, exclude=…)` builds the hash; the `ON CONFLICT` recipe is in the class docstring and `tests/test_mixins.py` |
| `TenantEntityMixin` | Tenant + Audit + Status + RowVersion + AppMeta + Timestamp | the entity bundle (add a soft-delete mixin) |
| `OrgEntityMixin` | the same on `MultiTenantMixin` | the entity bundle for organization-owned data |
| `LedgerMixin` | Tenant + AppMeta | append-only / operational rows |

Also here, no columns of their own: `IntPKMixin` (`id` BigInteger, internal only),
`BigIntPKWithUUIDMixin` (adds the public `uuid`), `TimestampMixin` (`created_at`,
`updated_at`, DB-authoritative). Doctrine: mixins carry columns and tiny pure helpers only —
never listeners, relationships or I/O; behaviour lives in `tenancy.py` and the services.

### Using the opt-in mixins

Bundles are chosen by table class (§3); these are added on top only where a table needs them.

```python
class Note(BigIntPKWithUUIDMixin, OrgEntityMixin, PolymorphicOwnerMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "notes"
    __table_args__ = (
        CheckConstraint(f"owner_type IN ({OWNER_TYPES_SQL})", name="chk_note_owner_type"),
        Index("ix_notes_owner", "tenant_id", "owner_type", "owner_id",
              postgresql_where=text("deleted_at IS NULL")),
    )
```

* **Order:** most-specific first, `Base` last.
* **`PolymorphicOwnerMixin`** — keep `owner_type` (WHO owns the row) apart from any "kind" column
  (`link_type`, `note_type`); one column carrying both is how "shipping" becomes an entity class.
  `owner_id` is the owner's internal BigInteger id, never its UUID. The mixin does not index the
  columns individually: `owner_type` has a dozen values, and every real read is "this owner's
  rows", which only the composite serves.
* **`HashGuardMixin`** — hash the *business* fields only; exclude timestamps, cursors and anything
  else that changes without the record changing. Compare with `IS DISTINCT FROM`, not `!=`, so a
  row whose hash is still NULL is rewritten once rather than skipped forever. Not indexed: the
  guard compares against the row the conflict key already found. Zoho mirrors keep using
  `zoho_raw_hash` (bytes, with the apply gate's provenance rules).
* **Core `insert()` / `on_conflict_do_update`** bypasses the ORM stamping (§4): set
  `tenant_id`, `updated_at` (and `updated_by*` if wanted) in `set_` yourself.

### Names from other codebases

Mixin sets copied in from other projects use different names. Do not add aliases — use ours:

| Other name | Use here | Why ours is different |
|---|---|---|
| `PrimaryKeyUUIDMixin` | `BigIntPKWithUUIDMixin` | same shape; `uuid` is NOT NULL |
| `TenantMixin` (`String(64)` ids, no FK) | `TenantScopedMixin` (`TenantMixin` is kept as its v1 alias) | BigInteger, FK to `tenants`, composite FK `(tenant_id, organization_id)` so a row can never point at another tenant's organization |
| `AuditColumnsMixin` | `AuditMixin` | now includes `updated_by_name` |
| `AppMetadataMixin` | `AppMetaMixin` | `app_version` is stamped automatically; JSONB has a server default |
| `RowVersionMixin` | `RowVersionMixin` | also wires `version_id_col` — the ORM refuses stale updates itself |
| `VerificationMixin` (with `is_verified`) | `StatusMixin.is_verified` + `VerificationMixin` | the fast boolean lives in the status bundle; the mixin adds who/when/how/evidence plus `mark_verified()` / `mark_unverified()`. Default status is `unverified`, not `pending` |
| `DeactivationMixin` (with `is_active`) | `DeactivationMixin` | no `is_active` column: with `status` and `deactivation_date` already present a third flag would be a second source of truth that can disagree. Filter `deactivation_date IS NULL`; `deactivate()` / `reactivate()` keep the three columns in step. Column is `deactivation_reason` |

## 3. Table classes (enforced by `test_every_table_is_entity_ledger_or_an_explained_global`)

| Class | Gets | Tables |
|---|---|---|
| **ENTITY** | everything in §2 | users, user_profiles, roles, documents, document_files, document_links, files, media, tags, favorites, emails, zoho_currencies, zoho_taxes, zoho_locations, zoho_users, organizations (its `parent_id` replaces `organization_id`), geo.places, geo.place_links, geo.geofences, geo.place_relationships |
| **LEDGER** | tenant_id, organization_id, app_version, app_metadata | activity_logs, email_events, email_links, taggables, password_reset_tokens, login_otp_tokens, zoho_sync_events/runs/cursors, zoho_quota_days, zoho_queue_logs, zoho_sync_stats, zoho_sync_state, zoho_oauth_credentials, geo.geocode_api_calls, document_verification_logs |
| **GLOBAL** | none (each has a written reason in the test) | tenants, countries, timezones, country_timezones, system_modules, setting_groups/definitions/values/audit_logs, zoho_retention_policies, document_types, geo.admin_boundaries |

Why ledgers don't get everything: `row_version` on rows that are never updated is noise, and
**an audit trail must never be soft-deleted**. `status` on an event row duplicates the event
itself. Moving a table to ENTITY is a one-line change plus a migration if that ever changes.

## 4. Runtime (`app/database/tenancy.py`)

| When | What happens |
|---|---|
| authenticated request | `get_current_user` → refuses users of a suspended or cancelled tenant (403) → `bind_user`: tenant = the user's, organization = `X-Organization-Id` (uuid, must belong to the tenant) or the user's own, actor = the user |
| every ORM SELECT / UPDATE / DELETE on a tenant table | `tenant_id = :current` added automatically. Escape hatch for platform code: `.execution_options(all_tenants=True)` |
| every INSERT | `tenant_id` ← context (or the **default tenant** when there is no context), `organization_id` ← context, `created_by`/`created_by_name` ← actor, `app_version` |
| every UPDATE | `updated_by` + `updated_by_name` (only when a user is acting), `app_version`; `row_version` checked and incremented |
| writing another tenant's row while a context is active | `TenancyError` before any SQL is sent |
| Zoho sync (Celery, CLI) | runs in `zoho_scope`: tenant `ZOHO_TENANT_CODE` (or default), organization = the node with `zoho_id = ZOHO_ORGANIZATION_ID`, actor `system:zoho-sync` |
| Core `insert()` / raw SQL | must set `tenant_id` itself (`await write_tenant_id(db)`); stamping only runs on ORM flushes |
| search | the Meilisearch index holds every tenant (CDC), so the search API always adds `tenant_id = :current`; Postgres hydration is filtered too |

**Optimistic locking.** API updates send the `row_version` they loaded and get 409 with
`current_row_version` if it changed. The ORM also refuses stale updates (`StaleDataError`).
Trade-off: asyncpg reports no per-row rowcount for batched UPDATEs, so versioned UPDATEs go
one row at a time. The Zoho page apply still does one preload query per page and writes only
changed rows.

**Email stays globally unique** so sign-in needs no tenant picker; the tenant comes from the
user.

## 5. Organizations API — `/api/organizations`

| Route | Who | Notes |
|---|---|---|
| `GET ""`, `/tree`, `/{ref}`, `/{ref}/children`, `/subtree`, `/ancestors` | member | `ref` = uuid (preferred), org_code or id |
| `POST ""` | tenant admin | `parent` = parent uuid |
| `PATCH /{ref}` | tenant admin | `row_version` required; Zoho-owned fields refused on Zoho-linked nodes |
| `POST /{ref}/move` | tenant admin | rewrites the whole subtree's path/depth in one UPDATE; cycles refused |
| `POST /{ref}/status` | tenant admin | active ↔ suspended → archived; reason required; fills/clears the deactivation fields; archive only when all children are archived |
| `DELETE /{ref}?reason=` | tenant admin | leaves only; Zoho-linked nodes are archived, not deleted |
| `POST /sync` | tenant admin | pull the Zoho organization(s) now |

Placement rules (`ALLOWED_PARENTS`):

| Type | May sit under |
|---|---|
| holding | root, holding |
| legal_entity | root, holding |
| branch | holding, legal_entity, branch |
| solo | root only, and no children |

`fiscal_year_start_month` accepts `0–11` or a month name (`"april"`) both from Zoho and from
API clients.

## 6. Tenants — `/api/tenants` · Roles — `/api/roles`

| Route | Who |
|---|---|
| `GET /tenants/current` | any signed-in user |
| `GET/POST /tenants`, `GET/PATCH /tenants/{ref}`, `POST /tenants/{ref}/status` | platform admin (`PLATFORM_ADMIN_EMAILS`; with the list empty, anyone when `DEBUG=true`) |
| `GET /roles`, `GET /roles/{ref}` | member |
| `POST/PATCH/DELETE /roles…` | tenant admin (role code `admin` or `owner`, or a platform admin) |

* Creating a tenant can also create its root organization (`root_organization_name`).
* The system roles `owner`, `admin` and `member` are seeded per tenant and cannot be deleted.
* A role still held by users cannot be deleted.
* `permissions` is stored for the coming RBAC work; today only the `admin` / `owner` codes
  carry meaning.

## 7. Settings

| Setting | Default | Meaning |
|---|---|---|
| `DEFAULT_TENANT_CODE` | `default` | the tenant the migration creates; rows written without a context go here |
| `PLATFORM_ADMIN_EMAILS` | "" | who manages tenants |
| `ZOHO_TENANT_CODE` | "" (= default) | the tenant that owns the Zoho connection |

## 8. Deploying

1. **Back up Postgres** — the migration is irreversible.
2. `dc up -d --build` → `dc exec backend alembic upgrade head`. Rehearsed on a copy shaped like
   the dev DB:
   * the Tarrina org became root node `ZOHO-60015628348`;
   * mirrors were attached to it;
   * `role_id = -1` was cleared;
   * no NULL `tenant_id` remained.
3. Rename the default tenant's display name with `PATCH /api/tenants/default` (as a platform
   admin; send its `row_version`). The **code** is a stable key and not editable through the
   API. To use e.g. `THPL`, run `UPDATE org_management.tenants SET tenant_code='THPL' WHERE
   tenant_code='default'` and set `DEFAULT_TENANT_CODE=THPL` (and `ZOHO_TENANT_CODE`) in the
   same deploy.
4. Give yourself a role:
   `UPDATE users SET role_id = (SELECT id FROM roles WHERE code='owner') WHERE email = …`,
   or set `PLATFORM_ADMIN_EMAILS`.
5. Re-register Debezium (`bash scripts/register-debezium.sh`). The include list now has
   `org_management.tenants`, `org_management.organizations` and `roles`. The search topic is
   `zoho-mirror.org_management.organizations` and the index is `organizations`, so
   **re-index search**.
6. Frontend: the Search component's default index is now `organizations`; the old
   `/api/zoho/organizations` routes are gone (use `/api/organizations`).

## 9. Open items

| # | Item |
|---|---|
| 1 | RBAC: enforce `roles.permissions` (today: admin/owner codes only) |
| 2 | Per-tenant Zoho connections (credentials, governor pool, planner keys per tenant); today one connection per deployment, owned by `ZOHO_TENANT_CODE` |
| 3 | Tenant resolution for unauthenticated flows by domain (`tenants.domain`); registration goes to the default tenant today |
| 4 | Users API: assign a role / primary organization (columns and FKs exist) |
| 5 | Postgres Row-Level Security as a third wall (policies on `tenant_id` with `SET app.tenant_id`) |
