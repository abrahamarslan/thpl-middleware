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
