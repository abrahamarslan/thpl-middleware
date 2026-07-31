# Zoho Sync Engine

The distributed MDM layer that keeps PostgreSQL a **two-way, eventually
consistent replica** of the Zoho ecosystem (Books / Inventory / HRMS).
Local apps (FSA, Delivery) talk ONLY to our FastAPI; the engine reconciles
with Zoho in the background through Celery.

Code: `app/modules/zoho/sync/` (framework) + one package per entity
(`app/modules/zoho/organizations/`, …). Celery drivers:
`app/tasks/zoho_sync.py`. Admin API: `/api/zoho/sync-engine/*`.

```
                         ┌─────────────────────────────────────────────┐
   Zoho Books API        │                Sync Engine                  │
 ┌───────────────┐  list │  ┌──────────┐   ┌────────┐   ┌───────────┐  │      ┌────────────┐
 │ /organizations│ ─────►│  │ Strategy │──►│ Mapper │──►│  Upsert   │──┼─────►│ PostgreSQL │
 │ /contacts ... │ detail│  │ full/incr│   │ fields │   │ by zoho_id│  │      │ mirror +   │
 └───────▲───────┘ ─────►│  │ /index   │   │ nested │   │ (revive)  │  │      │ PostGIS/   │
         │               │  └──────────┘   └────────┘   └───────────┘  │      │ hstore     │
         │   outbox      │        ▲            observability           │      └─────┬──────┘
         └───────────────┼── push_outbound    zoho_sync_stats          │            │ Debezium CDC
             create/     │   (Celery)         zoho_queue_logs          │            ▼
             update/     └─────────────────────────────────────────────┘      Kafka ─► ClickHouse
             delete                                                                 └► Meilisearch
```

---

## 1. The layer cake

| Layer | Location | Responsibility |
|---|---|---|
| Core client | `zoho/core/` | tokens (never-expired), global rate budget, circuit breaker, retries. Modules never touch HTTP. |
| **Config** | `zoho/sync/config.py` | hierarchical knobs + declarative field maps (the Laravel `zoho-modules.php` replacement) |
| **Mapper** | `zoho/sync/mapper.py` | dotted-path extraction, typed transforms, inbound/outbound payload building, custom-field flattening |
| **Mixin** | `zoho/sync/mixins.py` | `ZohoEntityMixin` — the strict schema every mirror table implements |
| **Observability** | `zoho/sync/models.py` | `zoho_sync_stats` (table-level), `zoho_queue_logs` (row-level) |
| **Registry** | `zoho/sync/registry.py` | modules self-register a `ZohoModuleDefinition`; autodiscovery imports them |
| **Engine** | `zoho/sync/engine.py` | strategies, N+1 orchestration, nested-entity FK resolution, identity matching |
| **Outbox** | `zoho/sync/outbox.py` | local→Zoho create/update/delete with transactional journaling |
| Tasks | `app/tasks/zoho_sync.py` | Celery: `sync_module`, `fetch_detail`, `push_outbound`, `sync_all_due` dispatcher |
| Admin API | `zoho/sync/api.py` | `/api/zoho/sync-engine/modules[…]` — configs, stats, queue logs, trigger runs |

## 2. Hierarchical configuration

Three layers, most-specific-wins, materialised once at import:

1. **Code defaults** — `GlobalSyncDefaults` field defaults.
2. **Environment** — `ZOHO_SYNC_*` env vars (batch size, interval, retry
   limit, pacing) override fleet-wide.
3. **Module declaration** — each module passes only what it overrides to
   `resolve_module_config(...)`.

Key knobs (see `config.py` for all):

| Knob | Meaning |
|---|---|
| `strategy` | `full` \| `incremental` \| `index` |
| `direction` | `inbound` \| `outbound` \| `bidirectional` \| `disabled` |
| `detail_required` | solve N+1: fetch full record before upserting |
| `detail_dispatch` | `inline` (same task, paced by `wait_between_calls`) or `queued` (one Celery task per record) |
| `batch_size` | list page size (Zoho caps at 200) |
| `sync_interval_minutes` | cadence honoured by the beat dispatcher |
| `modified_since_param` | Zoho's incremental filter; `None` ⇒ incremental degrades to full |
| `field_map` | list of `FieldMapping(zoho=…, local=…, transform=…, outbound=…)` |
| `nested` | `NestedEntityRule`s routing embedded objects to their own modules |
| `soft_delete_missing` | full sync soft-deletes rows that vanished upstream |

Field mapping example (`zoho="address.city"` → `local="address_city"`,
dotted paths rebuilt as nested objects on outbound writes):

```python
F(zoho="currency_name", local="name", transform="str")
F(zoho="is_default_org", local="is_default_org", transform="bool", outbound=False)  # read-only
```

Transforms: `str` (blank-normalising — Zoho sends `" "` for empty), `int`,
`float`, `bool`, `decimal`, `zoho_datetime`, `zoho_date`; register custom
ones with `mapper.register_transform`.

**Failure doctrine:** missing keys are skipped (a thin index payload never
NULLs data a detail sync wrote); one bad field/record logs and continues;
only upstream failures abort a run (so Celery backoff takes over).

## 3. The strict schema (`ZohoEntityMixin`)

Every mirror table gets, all `nullable=True`:

- **Identifiers**: `zoho_id` (indexed; NULL until an outbound create
  succeeds), `code` (unique when set), `description`
- **Sync columns**: `synced_at`, `sync_status`
  (pending/queued/syncing/synced/error/conflict/deleted), `sync_error`,
  `sync_attempt_count`, `sync_logs` (JSONB rolling journal, capped at 50)
- **Flags**: `is_active`, `is_verified`, `is_blocked`, `is_featured`,
  `is_promoted`, `is_sponsored`, `is_partnered`, `is_visible`,
  `show_in_menu`, `display_order`, `menu_order`
- **Extensions**: `metadata` (JSONB), `document_id`, `custom_fields`
  (**hstore** — Zoho custom fields flattened to text), `zoho_raw` (JSONB —
  the FULL untouched document; Debezium streams it downstream, a Zoho schema
  change never loses data)

Standard model shape (+ partial unique index so a soft-deleted ghost never
blocks a re-sync):

```python
class ZohoThing(IntPKMixin, TimestampMixin, SoftDeleteFilteredMixin, ZohoEntityMixin, Base):
    __tablename__ = "zoho_things"
    ...business columns, all nullable...
    __table_args__ = (
        Index("uq_zoho_things_zoho_id_live", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
    )
```

## 4. Inbound strategies

- **FULL** — paginate the list endpoint. With `detail_required`, the N+1
  issue is handled explicitly per record: **inline** (fetch now, paced) or
  **queued** (fan out `fetch_detail` Celery tasks, journalled in
  `zoho_queue_logs` first). Optional reconciliation soft-deletes rows gone
  upstream.
- **INCREMENTAL** — same pipeline windowed by the `last_modified_time`
  cursor persisted in `zoho_sync_stats.last_incremental_cursor`
  (sorted ascending; the max modified time seen becomes the next cursor).
  Degrades to FULL when the module has no modified filter.
- **INDEX** — list-only, never N+1 — for lightweight modules whose index
  row carries everything mirrored.

**Identity matching**: always by `zoho_id`, with `include_deleted=True` —
exists ⇒ UPDATE (revives soft-deleted rows), missing ⇒ CREATE.

**Nested/lazy-loaded relations**: Zoho embeds children in parents (Contact
carries `currency`, `tax_groups`). `NestedEntityRule(attr, module,
parent_fk, parent_zoho_fk, many)` routes each embedded payload to its
owning module's definition, upserts the child FIRST, then stamps the
child's local id / zoho_id onto the parent's FK columns.

## 5. Outbound — the transactional outbox

```
service writes local row ──┐ same transaction
journal zoho_queue_logs  ──┘        │ commit
                                    ▼
      Celery push_outbound (queue: integrations, backoff retries)
        create → POST, extract generated id → back-fill zoho_id
        update → PUT /{endpoint}/{zoho_id}   (no zoho_id yet? escalates to create)
        delete → DELETE, row marked sync_status='deleted'
```

Failures set `sync_error` / bump `sync_attempt_count` on the row, mark the
queue-log `failed`, and re-raise for Celery's exponential backoff.

## 6. Scheduling

Two beat entries drive EVERY module (config-driven — adding a module needs
no beat changes):

- `zoho-sync-dispatcher` (*/5 min): enqueues a run for each module whose
  `sync_interval_minutes` elapsed.
- `zoho-full-sync-weekly` (Sun 03:00): forces a full run for every module —
  the safety net for records incremental windows can miss.

Manual: `POST /api/zoho/organizations/sync?mode=full` or
`POST /api/zoho/sync-engine/modules/{module}/run?mode=incremental`.

## 7. Observability

- `GET /api/zoho/sync-engine/modules` — every module, effective config, live stats.
- `zoho_sync_stats` — cursors, lifetime counters, last-run outcome/duration.
- `zoho_queue_logs` — row-level journal: queued/started/finished timestamps,
  Celery task id, request id, error, per unit of work
  (`GET /api/zoho/sync-engine/modules/{m}/queue-logs?status=failed`).
- Row-level: every mirrored row carries `sync_status`, `sync_error`,
  `synced_at` and a `sync_logs` journal.
- Both tables are in Debezium's `table.include.list` → Kafka → ClickHouse
  for long-term sync analytics; logs in Loki (`logger="app.zoho.sync*"`),
  traces in Tempo, task metrics via celery-exporter.

## 8. Adding a new module (recipe)

1. `app/modules/zoho/<entity>/model.py` — model as in §3.
2. `__init__.py` — `resolve_module_config(...)` + `sync_registry.register(ZohoModuleDefinition(config=…, model=…))`.
3. Add the package to `_ENTITY_PACKAGES` in `zoho/sync/registry.py`.
4. Import the model in `alembic/env.py`; `bash .dev_migrate.sh revision "add zoho_<entity>"`; review; `migrate`.
5. Optional API package (`schema/crud/service/api.py`) + one line in `app/router.py`.
6. Optional CDC: add the table to `deployment/config/debezium/zoho-mirror-connector.json` → `./manage.sh register-debezium`.
7. Tests: copy the shape of `tests/zoho_sync/test_engine.py` (FakeZohoClient + real Postgres).

That's it — the dispatcher schedules it, the admin API exposes it, stats and
queue logs appear automatically.

## 9. Worked example: organizations

`app/modules/zoho/organizations/` mirrors
[docs/zoho-docs-md/organizations.md](zoho-docs-md/organizations.md):

- **FULL + inline detail** (tiny dataset; the list payload is a thin index;
  Zoho orgs have no modified-since filter → `modified_since_param=None`).
- **BIDIRECTIONAL**: `POST/PUT/DELETE /api/zoho/organizations[…]` write
  locally first and converge via the outbox; server-managed attributes
  (`is_default_org`, `user_role`, `currency_id`, …) are `outbound=False`.
- Endpoints: list / get-by-local-or-zoho-id / create / update / soft-delete /
  trigger sync. Reads are ALWAYS local (fast, offline-tolerant, zero rate
  budget).

## 10. Async-in-Celery pattern

The stack is asyncpg-only; Celery workers are synchronous. Every task runs
the async engine via `asyncio.run` with a throwaway `NullPool` engine, a
fresh `ZohoClient`, and a final `redis_client.aclose()` so no loop-bound
connections leak between tasks (see `app/tasks/zoho_sync.py` docstring).

## 11. Local development

```bash
cd apps/core-platform/backend
bash .setup_venv.sh                  # create .venv + install deps
# scratch services for integration tests / migrations (see tests/conftest.py):
docker run -d --rm --name thm-scratch-pg -p 55432:5432 \
  -e POSTGRES_USER=app -e POSTGRES_PASS=app_password -e POSTGRES_DBNAME=app_db \
  -e POSTGRES_MULTIPLE_EXTENSIONS=postgis,hstore,postgis_topology,pgrouting,pg_trgm,pgcrypto \
  kartoza/postgis:18-3.6--v2025.11.24
docker run -d --rm --name thm-scratch-redis -p 56379:6379 redis:7.4-alpine
bash .dev_migrate.sh upgrade         # apply migrations to the scratch DB
bash .dev_check.sh test              # import smoke + full pytest suite
```

Integration tests skip automatically when the scratch services are absent.
