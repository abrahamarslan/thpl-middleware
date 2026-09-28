# Cross-Cutting Modules

The shared building blocks implemented from `docs/modules-to-implement/`.
Each follows the FBA 5-layer pattern (api → schema → service → crud → model)
and registers exactly once in `app/router.py`.

| Module | Mount | Source spec |
|---|---|---|
| Soft delete (global filter) | — (infrastructure) | soft-delete.md |
| Tags | `/api/tags` | tags.md |
| Documents (attachments) | `/api/documents` | document.md |
| Media (galleries + conversions) | `/api/media` | media.md |
| Emails (Resend) | `/api/emails` | email.md |
| Favorites (collections) | `/api/favorites` | favorite.md |
| Search (Meilisearch CDC) | standalone indexer + `ScoutBuilder` | meilisearch.md |
| Custom fields (`extfields`) | `/api/custom-fields` | ExtFields — Architecture & Implementation Guide |
| Circuit breaker (ZSET window) | `zoho/core/circuit_breaker.py` | circuit-breaker.md |

---

## Soft delete — `app/database/soft_delete.py`

`SoftDeleteFilteredMixin` (inherit INSTEAD of `SoftDeleteMixin`) adds
`soft_delete()` / `restore()` and opts the model into a global
`do_orm_execute` listener that injects `deleted_at IS NULL` into every
SELECT (including relationship loads). Escape hatch:

```python
select(Model).execution_options(include_deleted=True)
await db.get(Model, id, execution_options={"include_deleted": True})
```

**Opt-in by design**: legacy modules (users, files, favorites) filter
explicitly and have restore flows — flipping the default under them would
break those. New models should use the filtered mixin + **partial unique
indexes** (`postgresql_where=text("deleted_at IS NULL")`) so ghosts never
block re-creation. Never call `session.delete()` on soft-deletable rows —
soft delete is an UPDATE, which keeps FKs and children intact.

## Tags — `app/modules/tags/`

Multilingual (`name`/`slug` are JSONB locale maps), namespaced (`type`),
polymorphic via the `taggables` pivot (composite PK; String `taggable_id`
so Integer-PK and UUID-PK entities coexist).

- Read path: inherit `HasTagsMixin`, query with `selectinload(Model.tags)`
  — one extra query per result set, zero N+1.
- Write path: `POST /api/tags/sync` (replace-set semantics, idempotent) or
  `tags.crud.sync_entity_tags`. The relationship is `viewonly` — mutating a
  secondary relationship in async SQLAlchemy dies with `MissingGreenlet`.

## Documents — `app/modules/documents/`

Two concerns in one module:

1. **PDF rendering** (pre-existing): `POST /render` → Celery → Gotenberg.
2. **Polymorphic attachments** (new): the `documents` table (UUID PK — no
   id enumeration) with `documentable_type/id`. Any model inherits
   `HasDocumentsMixin` for an eager-loadable `.documents` list.
   - `POST /api/documents` registers a record after the bytes hit S3.
   - `POST /api/documents/attach` points existing documents at an owner
     (per-document metadata like inline CID rides in `metadata`).
   - No `*_formatted` columns: `file_size_formatted` / `is_processable` are
     Pydantic `@computed_field`s — presentation can never drift from data.
   - Taggable (`HasTagsMixin`), soft-deleted with the global filter.

## Media — `app/modules/media/`

Spatie-MediaLibrary-style galleries:

- `HasMediaMixin` + declarative conversions on the owning model:
  `__media_conversions__ = {"thumb": (150, 150)}`. The relationship uses
  `lazy="raise_on_sql"` — forgetting `selectinload(Model.media)` raises
  instead of silently N+1-ing.
- Storage is a strategy (`storage.py`): `local` today, S3 by implementing
  four methods and setting `MEDIA_STORAGE_DRIVER=s3`. URLs are derived,
  never stored.
- Pillow conversions run in Celery (`app/tasks/media.py`, documents queue);
  the upload request returns instantly with conversion statuses `pending`.

## Emails — `app/modules/emails/`

Transactional email built as a reusable layer, not a one-off Resend call:

- **Provider adapter** (`provider.py`) — callers hand an `OutboundEmail` value
  object to `get_email_provider()` and get a `ProviderResult`; the Resend
  adapter is registered in a provider registry, so a new provider is one
  registration, never a branch in caller code. `EMAIL_PROVIDER` selects it.
  `get_email_provider()` is a lazy factory (the test patch point).
- **Template registry** (`templates.py`) — one entry per transactional email
  (subject + html/optional text, locale fallback to `EMAIL_DEFAULT_LOCALE`,
  `required_context` validation). The environment uses a `ChoiceLoader` across
  **every registered module's template directory**, so each feature owns its
  templates (auth's live in `app/modules/users/templates/`). `POST
  /api/emails/send-template` renders + queues; feature code calls
  `service.send_template_email(...)` and never builds an HTML string.
- `POST /api/emails/send` persists first (`emails` row, JSONB recipient
  arrays + deduped `all_recipients` for "ever emailed x@y?" queries),
  attaches existing Documents (single source of file truth), then queues
  `app/tasks/emails.send_email` (integrations queue). Scheduling via
  `scheduled_at` → Celery `eta`.
- **Sender provenance** — `emails.actor_id` / `source_ip` / `request_id`
  (from request context) answer *who queued it, from where, when*; the
  provider side (`email_events`) answers *when/where/who opened or clicked*.
- The worker speaks only the provider-neutral layer, honours
  `attempts/max_attempts` under Celery backoff, and respects
  `EMAIL_ENABLED` (off ⇒ rows are `suppressed`) and `EMAIL_LOG_ONLY`
  (dev: persist + mark sent without a provider call).
- `POST /api/emails/webhooks/resend` (svix-signature-verified when
  `RESEND_WEBHOOK_SECRET` is set) appends `email_events` rows and maintains
  aggregates: delivered/bounced status, open/click counts, first/last
  timestamps. Unknown messages are acknowledged, never retry-stormed.
- `GET /api/emails/stats` aggregates totals/rates over a window for the
  analytics dashboards; `email_events`/`email_links` are in Debezium's
  `table.include.list` for ClickHouse/Grafana. `emails` itself is
  deliberately *not* CDC'd (message bodies are not analytics data).

Settings: `EMAIL_PROVIDER`, `EMAIL_ENABLED`, `EMAIL_LOG_ONLY`,
`RESEND_API_KEY`, `RESEND_API_URL`, `RESEND_DEFAULT_FROM`,
`RESEND_DEFAULT_REPLY_TO`, `RESEND_WEBHOOK_SECRET`, `EMAIL_MAX_ATTEMPTS`,
`EMAIL_COMPANY_NAME`, `EMAIL_SUPPORT_EMAIL`, `EMAIL_SITE_URL`,
`EMAIL_COMPANY_ADDRESS`, `FRONTEND_URL`.

## Auth — `app/modules/users/`

> Full reference: [docs/modules/auth-module-documentation.md](modules/auth-module-documentation.md).

- **Identifiers.** Login, password reset and login OTP all accept a single
  `identifier` (email | username | phone), resolved by `identifiers.py`
  (shape-driven, username fallback); responses never reveal which matched.
- **Password policy** (`password_policy.py`) is configuration, not code:
  `PASSWORD_MIN_LENGTH`/`MAX_LENGTH`, `REQUIRE_UPPERCASE`/`LOWERCASE`/`DIGIT`/
  `SPECIAL`, `MIN_UNIQUE_CHARS`, `DISALLOW_COMMON`, `DISALLOW_USER_INFO`. One
  engine drives register, admin-create, change-password and reset; the
  `PasswordStr` Pydantic type enforces it at the boundary (422 envelope) and
  `validate_password(...)` adds the user-specific rules in the service.
  `GET /api/auth/password-policy` exposes the active rules to clients.
- **Password reset** (`password_reset.py`) ships a configurable-length **digit
  code (4 by default)** plus a link fallback. Defenses: code stored only as a
  keyed HMAC (`security.hash_one_time_code`), short TTL
  (`PASSWORD_RESET_CODE_TTL_MINUTES`), attempt cap
  (`PASSWORD_RESET_MAX_ATTEMPTS`, row destroyed at the cap), single-use,
  resend cooldown + hourly cap, and a uniform `{sent: true}` response. A
  successful reset emails a security confirmation.
- **Login OTP** (`login_otp.py`) is passwordless email OTP:
  `POST /api/auth/login-otp/request` sends a 6-digit code;
  `POST /api/auth/login-otp/verify` exchanges it for a token pair (clears the
  lockout, records the session). Same HMAC-at-rest/attempt-cap/cooldown model
  as reset, backed by `login_otp_tokens`.
- **Auth emails** (`auth_emails.py` + `users/templates/`) are typed-context
  wrappers over the email layer: `welcome` (on register), `login_otp`,
  `password_reset_code` / `password_reset_link`, `password_changed`. Every
  security email shows request-audit info.
- **GeoIP / client context** (`app/common/geoip.py`, `app/common/client_info.py`):
  `ClientInfoDep` resolves the real IP (`X-Forwarded-For`/`X-Real-IP`), parses
  the device from the User-Agent, and (when `GEOIP_ENABLED=true`, GeoLite2 DB
  mounted) the city/country. Used for logs and the audit block in auth emails.
- **Moderation** (`moderation.py`): admin **ban**/**unban** (hard; permanent or
  time-boxed) and **throttle**/**unthrottle** (soft; existing session keeps
  working, new auth returns 429). Ban destroys in-flight reset/OTP challenges
  and deactivates the Authentik account. Endpoints under
  `/api/users/{id}/ban|unban|throttle|unthrottle|moderation`; every action is
  written to the activity log. Automatic lockout (`locked_at`) remains separate.
- **Audit logging** (`audit.py`): every auth event (register, login success/
  failure/lockout, logout, token issue/refresh, OTP, password change/reset,
  profile diff, ban/throttle) dual-writes an append-only `activity_logs` row +
  a structured log, correlated by `request_id`. Failure paths commit the
  counter/lockout **and** their audit row before raising (otherwise the request
  rollback discards them). See
  `apps/core-platform/docs/AUTH_AUDIT_LOGGING_PLAN.md`.

- **Every user belongs to an organization.** `users.organization_id` is NOT NULL
  (`MultiTenantMixin`) and the role FK is three columns wide
  (`(tenant_id, organization_id, role_id)` → `roles`), so a user can never hold
  another organization's role. The unauthenticated creation paths have no
  organization bound to stamp from, so **`service.resolve_user_organization`**
  supplies one — the request's organization when there is one, else the tenant's
  root. Register, admin-create, **Authentik JIT provisioning** and the DEBUG-only
  dev-token user all go through it; a new path that creates a user must too, or
  it fails with a NOT NULL violation rather than anything readable.
- **Location is not on the user row.** Addresses live in the platform-wide
  address book (`/api/addresses` with `owner_type=user` → `geo.place_links` →
  `geo.places`) — there is deliberately no user-specific address endpoint.
  `users.primary_place_id` and `users.country_code` are caches; the address
  service calls `users.service.refresh_primary_place` on every attach/update/
  detach, which is the only writer of that column. `GET /api/users?city=…`
  (and `state`/`country`) resolves through the address book, not the user row.
- **Position telemetry** never touches the row authentication reads:
  `user_live_locations` (one row per user — what dispatch and beat planning read)
  is the last-known projection of the field-ops stream `fieldops.location_pings`,
  which replaced `user_location_pings` (see "Field operations" below).
  `PATCH /api/me/location` (now served by `app/modules/fieldops/api_me.py`)
  records a fix as a one-item batch; `GET /api/me/location` and
  `GET /api/users/{id}/location` read the last one. The only `users` column a
  fix touches is `is_location_set`.

Settings (auth OTP): `LOGIN_OTP_CODE_LENGTH`, `LOGIN_OTP_TTL_MINUTES`,
`LOGIN_OTP_MAX_ATTEMPTS`, `LOGIN_OTP_RESEND_COOLDOWN_SECONDS`,
`LOGIN_OTP_MAX_PER_HOUR`. GeoIP: `GEOIP_ENABLED`, `GEOIP_CITY_DB_PATH`,
`GEOIP_COUNTRY_DB_PATH` (see `deployment/config/geoip/README.md`).


## Favorites — upgraded

`collection_name` (NOT NULL, default `"default"`) joins the composite
uniqueness (`user × type × id × collection`) — a user can wishlist AND
shortlist the same record. Toggle/list/add APIs accept and filter by
collection. NOT NULL because Postgres treats NULLs as distinct in unique
constraints, which would allow duplicates.

## Search — `app/modules/search/`

Infrastructure-level CDC indexing (no double-writes in app code):

```
Postgres WAL → Debezium (unwrap) → Kafka zoho-mirror.public.<table>
             → search-indexer (FastStream consumer, batches ≤500, at-least-once)
             → Meilisearch index "<table>"
             ← GET /api/search/{index} (ScoutBuilder: Meili ranks, PG hydrates)
             ← React <Search/> (debounced, search-as-you-type)
```

**Indexer** (`indexer.py`, FastStream on aiokafka): one batch subscriber per
CDC topic (`AckPolicy.ACK`, `batch=True`, `max_records=SEARCH_INDEX_BATCH_SIZE`).
- Deletes AND soft-deletes leave the index (`__deleted` flag / `deleted_at`).
- Offsets commit only after the handler returns — i.e. after Meilisearch
  accepted the batch; Meili upserts are idempotent by id, replays harmless.
- Topics via `SEARCH_CDC_TOPICS`; bulk SQL updates index correctly because
  the WAL — not ORM events — is the source.
- Runs as `python -m app.modules.search.indexer` (calls `app.run()` itself —
  keeps `configure_logging()` first, no `faststream[cli]` extra needed).
- OTel: `KafkaTelemetryMiddleware` when `OTEL_ENABLED` — consumer spans flow
  to Alloy → Tempo like every other service.
- On startup it pushes declared index settings to Meilisearch
  (`registry.ensure_index_settings`) — see below.

**Registry** (`registry.py`) — the single place a table becomes searchable.
A `SearchableEntity` declares the model (hydration), the Out schema
(serialization), and the Meilisearch `searchable`/`filterable`/`sortable`
attributes. Meilisearch REJECTS filters on undeclared attributes, so the
settings bootstrap is mandatory, and the API validates filter fields against
this registry (a typo is a clean 400, not an opaque Meili error). Adding a
searchable table = Debezium `table.include.list` + `SEARCH_CDC_TOPICS` + one
registry entry.

**Query side**: `ScoutBuilder(Model, "query").where(...).get(db)` —
Meilisearch ranks, Postgres hydrates, relevance order preserved (fresh rows,
soft-delete filtered). Exposed at `GET /api/search/{index}?q=&filter=field:value`
(JWT-protected; `GET /api/search/indexes` lists what's searchable).

**Freshness**: write → searchable is ~1–3 s (WAL → Debezium → Kafka →
indexer batch window ≤1 s → Meili task queue). Near-real-time, not
transactional — never build read-your-own-writes flows on search.

**Frontend**: `frontend/src/Search.tsx` — 200 ms debounce, AbortController
cancels stale requests, Bearer token from localStorage (dev stacks mint one
via the DEBUG-only `/api/auth/dev-token`).

**Tests** (`tests/test_search_indexer.py`): consumer exercised through
`TestKafkaBroker` (no Kafka container), Meilisearch mocked with pytest-mock's
`mocker`; registry test asserts every declared attribute exists on the model.

## Core master data — `app/modules/{brands,manufacturers,entities}/`

Domain masters (not cross-cutting infrastructure) in the dedicated `core`
schema, following the canonical-master pattern `currencies` established:
`OrgEntityMixin` (tenant + organization NOT NULL) + `PolymorphicOwnerMixin`
provenance + `SoftDeleteFilteredMixin` + `BigIntPKWithUUIDv7Mixin`; business
columns nullable by doctrine; partial unique indexes for every uniqueness
rule; `name_normalized` / `value_normalized` / `alias_normalized` are STORED
generated columns with pg_trgm GIN indexes.

**Tables.** `brands`, `manufacturers` (canonical masters), `brand_manufacturers`
(role + `[valid_from, valid_to)` window), `manufacturer_identifiers`
(GSTIN/PAN/CIN/FSSAI/… with statutory-format CHECKs), `entity_types` (registry)
and `entity_aliases` (polymorphic alternative names).

**Database-owned guards** (the parts a CHECK cannot express):
`core.guard_brand_parent()` (no brand-tree cycles), and two *deferrable
constraint triggers* — `core.check_brand_manufacturer_overlap()` (no
overlapping validity windows per brand×manufacturer×kind) and
`core.check_entity_alias()` (proves a polymorphic alias target exists via
`core.entity_types`; `core.find_orphan_entity_aliases()` reports leaks).
Cross-organization pairing is prevented structurally by composite FKs
`(tenant_id, organization_id, x_id)`, so the reference design's
scope/owner-sync triggers are unnecessary.

**HTTP.** `/api/brands`, `/api/manufacturers`, `/api/entities`; each list is a
Slim DTO backed by `load_only`, each detail a Fat DTO with `selectinload`ed
children. Both masters are taggable and carry documents, and are searchable
via `search/registry.py` (`brands`, `manufacturers`).

**Zoho sync** (`brands/zoho/`, migration `20260928_1700_999509053c9f`) mirrors
Zoho Books' real but **undocumented** `/brands` (`{brand_id, name}`, unpaginated,
no incremental filter, detail buys nothing) into `core.brands` through the
crosswalk — a `zoho_id` echo, `match_on=()` (never auto-merge a same-named local
brand; a genuine collision fails loudly at `uq_brands_scope_name`). INBOUND
only: only `GET` was verified, no push is built. This reverses the table's
original "not a Zoho mirror" design, on the user's explicit instruction once the
endpoint was confirmed live — `docs/implementation-plan/brands-zoho-sync.md`.
Only `name` is Zoho-owned on a linked row; everything else (slug, code, kind,
hierarchy, …) stays fully locally editable.

## Categories & taxonomies — `app/modules/categories/` (schema `core`, migrations `20260925_1000_c7a1e9b2d4f8` + `20260925_1400_c063729f29c2`)

Organization-scoped taxonomy trees and their polymorphic assignments. Four
`core` tables: **`taxonomies`** (a named tree per organization; `slug` unique
among live rows; status `draft|active|retired`), **`taxonomy_entity_types`**
(the whitelist of categorisable types — `entity_type_code` FK →
`core.entity_types.code` — with an `allows_multiple` cardinality switch, NULL =
permissive), **`categories`** (tree nodes: `parent_id` + nested-set
`_lft`/`_rgt` + `depth` + `path`, maintained by the pure `tree.py` under a
per-taxonomy advisory lock; full approved display/SEO/flag column set per locked
L1; a `zoho_id` echo (crosswalk shape — no mirror mixins); `HasTagsMixin` +
`HasDocumentsMixin`), and **`categorizables`** (a polymorphic,
temporally-windowed assignment; `categorizable_type` FK → `core.entity_types.code`;
`categorizable_id` proved at COMMIT via `core.assert_entity_exists()`).

**Database-owned guards.** Four composite scope FKs collapse the reference
design's owner machinery (`fk_categories_taxonomy_scope`,
`fk_categories_parent_scope`, `fk_categorizables_category`, plus the org FK).
`core.guard_category_scope()` rejects a child under a leaf and a move that would
cycle; `core.guard_taxonomy_organization_change()` blocks re-org of a populated
tree; the deferred `core.check_categorizable_integrity()` skips tombstones,
checks the whitelist and raises `23P01` on overlapping windows;
`core.find_orphan_categorizables()` reports leaks. Known deviation (documented
in the migration): PostgreSQL cannot reference a partial unique index, so the
whitelist is enforced by that trigger rather than the planned composite FK.

**HTTP.** `/api/taxonomies` (trees; `PUT /{ref}/entity-types` replaces the
whitelist), `/api/categories` (Slim list carrying the full tile set, Fat detail
with tags + documents, `POST /{ref}/move`), `/api/categorizables` (assign,
`POST /sync` replace-set, unassign). Deferred-constraint failures surface as a
clean envelope through the shared `IntegrityError`/`StaleDataError` handlers
(SQLSTATE → 4xx). `categories` is searchable via `search/registry.py`; the
Debezium `table.include.list` carries `core.taxonomies`, `core.categories` and
`core.categorizables`.

**Zoho sync** (`categories/zoho/`) mirrors Zoho Books `/categories`
(`docs/zoho-docs-md/categories.md`) through the **crosswalk** — the same shape as
`currencies` and `taxes` (`docs/implementation-plan/sync-crosswalk-delta-v3.md`).
`core.categories` holds business columns plus one `zoho_id` echo; identity, the
apply gate's fence/hash, the raw document and custom fields live in
`sync.sync_records` / `sync.sync_payloads` (the table carries none of the
in-place mirror columns or push state). INBOUND + INCREMENTAL on
`last_modified_time` + index-then-detail; `include_root_category=false` keeps
Zoho's synthetic `ROOT` row out; the weekly full lane + `soft_delete_missing`
tombstone what Zoho deleted (behind `ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING`).
Parent links are resolved through the crosswalk in `post_upsert` (an
unresolvable one is queued on `sync.pending_references`) and the taxonomy's
nested-set bounds recomputed; synced rows land in an auto-provisioned
per-organization `zoho` taxonomy (`core.fill_category_default_taxonomy()`).
A linked category's Zoho-fed fields, **its parent and its taxes** are read-only through the
API. Its `category_tax_preferences` become `tax.tax_assignments` (below). `service.to_zoho_payload` is the seam for the (not-yet-built) command
outbox. Findings, live evidence and open items:
`docs/implementation-plan/categories-zoho-sync-review.md`.

## Tax assignments — `app/modules/taxes/` (schema `tax`, migrations `20260925_1600_84daf73430b6` + `20260925_1610_cbdb4590446e`)

One polymorphic table answers "which taxes does *this entity* carry?" for **any** entity —
a category today, an item, a customer or an invoice line when they exist — so none of them
grows its own tax column. **`tax.tax_assignments`** holds an owner (`owner_type_code` +
`owner_id`) → a tax component (rate *or* group) **or** an exemption, in an
inter/intra × sales/purchase context, with optional frozen snapshot for issued documents.
**`tax.taxable_entity_types`** is the global opt-in policy (one tax per context or several;
exemptions or not). Integrity is the platform registry's: the owner class is an FK chain to
`core.entity_types`, and deferred triggers prove the owner exists, shares the assignment's
tenant **and organization**, and honours the class's rule.

**Making an entity taxable** is a registry row + a policy row
(`taxes.registration.register_taxable_entity_type`, called from its migration) and
`HasTaxesMixin` on its model — no change to the `tax` schema. Writes go through
`taxes.assignment_service.replace_assignments`; `resolve_taxes` answers "which tax applies
here?" for a chain of owners (line → item → category), most specific first, falling back to
the organization default. HTTP: `/api/taxes/assignments`. Full design, recipe and evidence:
`docs/implementation-plan/tax-assignments.md`.

## Custom fields — `app/modules/custom_fields/` (schema `extfields`)
A typed, definition-driven key/value store: any registered entity type can carry
a growing set of custom fields without schema churn. Three tables, because the
owner registry is the shared one:

- **`extfields.data_types`** (GLOBAL) — Zoho's custom-field data-type vocabulary
  mapped to which physical column on `field_values` holds it. `code` is open
  (a new Zoho type is a **seed row**, `seed.py`); `storage_column` is a closed
  CHECK over `value_text|value_numeric|value_date|value_boolean|value_json` (AP8).
- **`extfields.field_definitions`** (ENTITY, org-scoped) — one custom field
  (Class F): presentation, validation, mandatory/visibility policy, a
  self-referential dependency, and the DPDP `pii_type`. `is_custom_field` is
  dropped — every row here is a custom field by construction.
- **`extfields.field_values`** (ENTITY, org-scoped) — one typed answer per
  (field, owner). `owner_type_code` is a real FK to the shared
  **`core.entity_types`** registry; `owner_id` is polymorphic with no FK.

**Integrity** (the parts the database owns): `ck_field_values_single_value`
(`num_nonnulls(...) <= 1`), the partial unique
`uq_field_values_field_owner`, and a **deferred constraint trigger**
`extfields.check_field_value_integrity()` that proves the owner instance exists
via the existing `core.assert_entity_exists()` *and* that the populated column
matches the definition's data type. Because it is deferred, a definition and its
first value may be written in either order in one transaction; the failure
surfaces at COMMIT. `extfields.find_orphan_field_values()` is the scheduled
safety net (walks the registry, `STABLE`).

- Read path: inherit `HasCustomFieldsMixin` (set `custom_fields_owner_type`),
  query with `selectinload(Model.custom_field_values)`.
- Write path: `service.set_value` / `sync_values` (or `/api/custom-fields/values`).
  Values arrive as plain JSON scalars and are placed in the correct column by
  the definition's data type — the five-column storage detail never reaches a
  client.
- DPDP: `field_definitions.pii_type` (`non_pii`/`pii`/`sensitive_pii`; NULL =
  unclassified) drives `POST /api/custom-fields/values/erase-pii`, which blanks
  and soft-deletes every value under a PII-classified field of one owner.

Adding a field = a `field_definitions` row; adding an owner type = a
`core.entity_types` row. No migration either way. Owner-type launch seeding and
a Zoho field-definition sync are separate workstreams.

## Field operations — `app/modules/fieldops/` (schema `fieldops`, migration `20260929_1000_5d8c2e1f7a90`)

Shifts (with pauses), visits (field / telephonic / video), visit tasks, and THE location
stream for FSA/DLP. Full reference: [docs/fieldops/README.md](fieldops/README.md); design
and rationale: [spec](fieldops/implementation-of-shift-visits-system.md),
[review](fieldops/improvement-document.md).

- **One stream.** `fieldops.location_pings` holds every fix — continuous tracking and the
  labelled checkpoints of shift start/pause/resume/end, visit start/end and tasks. Monthly
  partitions on the device fix time (clamped), a DEFAULT partition, replay-proof through
  `(tenant, user, uuid, recorded_at)`. Shifts and visits store times, never coordinates.
- **Business time is `occurred_at`**, derived from the device's monotonic clock, else its
  skew-corrected wall clock (`clock.py`) — an offline start at 09:02 synced at 18:40 starts
  at 09:02. `client_timestamp` (raw device time) is kept beside it everywhere.
- **Invariants in the database:** one open (active|paused) shift per user, one open pause per
  shift, one in-progress visit per user. Closing a shift closes its pause and cancels its
  stuck visits in the same transaction; auto-close never invents a long shift (a ghost closes
  at 0 minutes and is flagged).
- **Obligations vs permissions:** `fieldops.work_policies` (per organization × base role) says
  what a worker MUST do; RBAC says what they MAY — `fieldops.field_work:use` (member),
  `fieldops.telephonic_visit:create` (granted per organization role), review/read codes for
  managers. Manager reads are narrowed to their teams and reports (`scope.py`).
- **Geofencing** is accuracy-aware and advisory by default; soft/hard blocking never refuses a
  start that already happened offline. Everything estimated or suspicious opens an idempotent
  **anomaly** and puts the shift/visit in the review queue.
- **Offline safety:** client UUIDv7s make creates replay-safe; `X-Idempotency-Key` replays
  transitions from `core.idempotency_keys` (`app/modules/idempotency/`, platform-wide).
- Background work in `app/tasks/fieldops.py` (auto-close, orphan linking, metrics, checkpoint
  geocoding, missed visits, partitions/retention).

## Circuit breaker — upgraded

`zoho/core/circuit_breaker.py` is now a **time-based sliding window**
(Redis ZSET scored by timestamp, purged with `ZREMRANGEBYSCORE`): the math
is strictly "the last `ZOHO_CB_WINDOW_SECONDS`", immune to the time-decay
flaw of count-based windows. Trips on failure rate OR slow-call rate
(duration ≥ `ZOHO_CB_SLOW_SECONDS`), evaluated only past
`ZOHO_CB_MIN_CALLS`. Recovery: OPEN for `ZOHO_CB_RECOVERY_SECONDS`, then
HALF_OPEN where exactly ONE worker wins the probe lock (no thundering
herd); the probe's outcome closes or re-opens the circuit. State is
Redis-shared across every API + Celery process, keyed per endpoint group.
