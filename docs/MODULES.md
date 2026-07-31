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

Transactional email via Resend with a full lifecycle mirror:

- `POST /api/emails/send` persists first (`emails` row, JSONB recipient
  arrays + deduped `all_recipients` for "ever emailed x@y?" queries),
  attaches existing Documents (single source of file truth), then queues
  `app/tasks/emails.send_email` (integrations queue). Scheduling via
  `scheduled_at` → Celery `eta`.
- The worker builds the Resend payload (base64 attachments, inline CIDs),
  honours `attempts/max_attempts` on the row under Celery backoff, and
  records provider ids/responses.
- `POST /api/emails/webhooks/resend` (svix-signature-verified when
  `RESEND_WEBHOOK_SECRET` is set) appends `email_events` rows and maintains
  aggregates: delivered/bounced status, open/click counts, first/last
  timestamps. Unknown messages are acknowledged, never retry-stormed.

Settings: `RESEND_API_KEY`, `RESEND_DEFAULT_FROM`, `RESEND_WEBHOOK_SECRET`,
`EMAIL_MAX_ATTEMPTS`.

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
