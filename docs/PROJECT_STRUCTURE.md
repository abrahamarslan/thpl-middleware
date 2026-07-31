# Project Structure Reference

Every file in the repository, its purpose, and how to use it.
Architecture rationale lives in the root [README.md](../README.md); this is the file-level map.

```
th-middleware/
├── README.md                  Architecture overview, runbooks, decisions
├── .gitignore                 Repo-wide ignores (secrets, caches, build output)
├── docs/                      This reference + Zoho API docs + guides
└── apps/core-platform/
    ├── backend/               FastAPI + Celery application
    ├── frontend/              React (Vite) SPA
    └── deployment/            Docker Compose stack + configs + ops scripts
```

---

## 1. Root

| File | Purpose |
|---|---|
| `README.md` | Entry point: architecture, async/Celery topology, observability flow, security model, backup policy, quick-start commands, deliberate removals. Read this first. |
| `.gitignore` | Blocks `.env*` (except `.env.example`), Python/Node caches, `media/`, `backups/`, logs. |
| `structure.txt` | Historical artifact — the original folder listing this project was scaffolded from. Safe to delete. |
| `docs/PROJECT_STRUCTURE.md` | This file. |
| `docs/ZOHO_SYNC_ENGINE.md` | **The MDM sync engine**: hierarchical config, strategies (full/incremental/index), N+1 handling, nested-entity routing, outbox, observability, add-a-module recipe. |
| `docs/MODULES.md` | Cross-cutting modules: soft delete, tags, documents attachments, media, emails, favorites collections, search (CDC→Meilisearch), circuit breaker. |
| `docs/zoho-module-implementation-guide.md` | Step-by-step: build a Zoho module (API → local Postgres → Debezium → ClickHouse). |
| `docs/modules-to-implement/*.md` | The original module specs the implementations in MODULES.md were built from. |
| `docs/AUTHENTIK_SYNC.md` | Outbound user sync (app → Authentik): architecture, field/ID mapping, lifecycle map, one-time Authentik setup, backfill, ops queries. |
| `docs/zoho-docs-md/*.md` | Vendored Zoho Books API reference (oauth, contacts, items, invoices, …). Used when implementing modules. |

---

## 2. Backend — `apps/core-platform/backend/`

### 2.1 Top level

| File | Purpose / usage |
|---|---|
| `Dockerfile` | Multi-stage production image: deps built into `/opt/venv` in a builder stage, copied into a slim runtime, runs as non-root `appuser`. One image serves four roles (api, worker, beat, flower) — compose changes only the command. Build: `docker compose build backend`. |
| `.dockerignore` | Keeps tests, caches, `.env`, `media/` out of the image context. |
| `requirements.txt` | Runtime dependencies only. Versions are ranged; for CI/CD generate a lock: `uv pip compile requirements.txt -o requirements.lock`. |
| `requirements-dev.txt` | Adds pytest, pytest-asyncio, pytest-cov, pytest-mock, factory-boy, faker, ruff, mypy, pre-commit on top of runtime deps. Install locally: `pip install -r requirements-dev.txt`. Never installed in the image. Use the `mocker` fixture (pytest-mock) to patch external systems (Zoho client, Redis) in service-layer tests; use FastAPI `dependency_overrides` for route-level substitution. |
| `pytest.ini` | Pytest config: `tests/` as testpath, asyncio auto mode. Run: `pytest`. |
| `.env` | Local (non-Docker) dev settings. Git-ignored. Docker injects env via compose instead. |
| `.env.example` | Template for `.env` with placeholders and generation commands. |
| `alembic.ini` | Alembic config. The DB URL is injected from app settings in `alembic/env.py` — never hardcode it here. |

### 2.2 Alembic — `alembic/`

| File | Purpose / usage |
|---|---|
| `env.py` | Async migration environment. Imports `Base` and every module's `model.py` so `--autogenerate` detects tables. URL comes from `app.core.conf.settings`. |
| `script.py.mako` | Template for generated migration files. |
| `versions/` | Generated migrations live here. Create: `./manage.sh makemig "add zoho_contacts"`; apply: `./manage.sh migrate`. |

### 2.2b Logging config — `config/logging/` (baked into the image; bind-mountable)

Consumed by `app/core/logging/`. See [docs/LOGGING.md](LOGGING.md).

| File | Purpose / usage |
|---|---|
| `logging.yaml` | Application-level base: master `enabled` switch, root level/format, `redact_keys`, and third-party logger rules (e.g. `uvicorn.access` disabled). |
| `environments/{development,staging,production}.yaml` | Per-environment profiles. `ENVIRONMENT` selects one; sets level/format/caller (dev=DEBUG+console, staging=DEBUG+json, prod=INFO+json). |
| `modules/{zoho,users,security,documents,tasks}.yaml` | Per-module rules; each declares the `logger:` namespace it governs (e.g. `app.zoho`). Flip `enabled`/`level` to silence or deep-debug one module without touching others. |

### 2.3 Application core — `app/`

| File | Purpose / usage |
|---|---|
| `main.py` | Entrypoint: `app = register_app()`. Target of `uvicorn app.main:app`. |
| `router.py` | Master API router. Every module's router is included exactly once here with its prefix and tag. Adding a module = one import + one `include_router` line. |

#### `app/core/` — configuration & wiring

| File | Purpose / usage |
|---|---|
| `conf.py` | **The single source of configuration.** Pydantic-settings class; every tunable (DB pool, Redis URLs, Celery broker, JWT, Zoho credentials + guard-rail limits, Gotenberg URL, OTel) is an env var with a default. Import `from app.core.conf import settings` anywhere. |
| `registrar.py` | Application factory: logging → FastAPI instance (docs disabled in production) → CORS → request-context middleware → rate limiter (slowapi, Redis-backed) → exception handlers → routers → Prometheus `/metrics` → OpenTelemetry. Lifespan verifies Redis on startup, disposes pools on shutdown. |
| `observability.py` | OpenTelemetry setup. `setup_otel(app)` instruments FastAPI/httpx/SQLAlchemy/Redis and exports OTLP to Alloy → Tempo. `setup_otel_celery()` is invoked from the worker-init signal. Toggle with `OTEL_ENABLED`. |

#### `app/core/logging/` — enterprise logging (layered, config-driven)

Configuration precedence: code defaults → `config/logging/logging.yaml` → `environments/<env>.yaml` → `modules/*.yaml` → env vars (`LOG_ENABLED`/`LOG_LEVEL`/`LOG_FORMAT`). Full guide: [docs/LOGGING.md](LOGGING.md).

| File | Purpose / usage |
|---|---|
| `logging/schema.py` | Pydantic models (`LoggingConfig`, `LoggerRule`) — validate the merged YAML at startup; a bad level/typo fails loudly. |
| `logging/loader.py` | Loads + deep-merges the YAML layers, picks the `ENVIRONMENT` profile and every module file, applies env-var overrides. Cached. |
| `logging/setup.py` | `configure_logging()` builds the structlog→stdlib→stdout pipeline; enforces per-module enable/level via the stdlib logger hierarchy; honours the master switch. |
| `logging/redaction.py` | structlog processor that recursively masks `redact_keys` (password, token, authorization, …) anywhere in an event. |

#### `app/common/` — shared building blocks

| File | Purpose / usage |
|---|---|
| `log.py` | Backward-compat facade re-exporting `configure_logging` / `get_logger` / `get_logging_config` from `app.core.logging`. Called by the app factory and the Celery `setup_logging` signal. Use `structlog.get_logger("app.<module>.<area>")` in code so per-module config applies. |
| `exception/errors.py` | Domain exception hierarchy (`AppError`, `NotFoundError`, `AuthError`, `ForbiddenError`, `ConflictError`, `UpstreamError`). Services raise these; never raise bare `HTTPException` for business errors. |
| `exception/handlers.py` | Global handlers translating any exception into the unified envelope `{code, msg, data, request_id}`. Unhandled exceptions log a full traceback (→ Loki) and return an opaque 500. |
| `response/schema.py` | `ResponseModel[T]` success envelope and `PageModel[T]` for paginated payloads. |
| `serialization.py` | `to_jsonable()` — coerces datetime/Decimal/UUID/Enum (recursively) into JSON-safe values before writing JSONB columns (used by the activity recorder). |
| `security/jwt.py` | First-party PyJWT helpers: HS256 access **and refresh** tokens (`create_access_token`, `create_refresh_token`, `decode_token` with type checking). |
| `security/authentik.py` | Authentik OIDC validation (**inbound**): fetches the provider's JWKS (cached), verifies RS256 tokens (issuer/audience), used by the `CurrentUser` dependency for SSO logins. |
| `security/authentik_client.py` | Authentik admin API client (**outbound**, app → Authentik): async wrapper over `/api/v3/core/users/` using a service-account bearer token (create / update / set_password / set_active / delete / find_by_email). Raises `AuthentikError` (→ 502). See [docs/AUTHENTIK_SYNC.md](AUTHENTIK_SYNC.md). |

#### `app/database/`

| File | Purpose / usage |
|---|---|
| `db.py` | Async SQLAlchemy engine (pool settings from conf), `Base` declarative class, `get_db` session dependency (`DBSession` annotation) with commit-or-rollback semantics. Imports `soft_delete` for its listener side effect. |
| `mixins.py` | Reusable model mixins (cross-cutting **columns**): `IntPKMixin`, `TimestampMixin`, `SoftDeleteMixin`, `TenantMixin`, `AuditUserMixin`. Mix in most-specific-first, `Base` last. |
| `soft_delete.py` | `SoftDeleteFilteredMixin` + global `do_orm_execute` listener: opted-in models get `deleted_at IS NULL` on every SELECT; escape with `execution_options(include_deleted=True)`. See docs/MODULES.md. |
| `redis.py` | Shared async Redis client (`redis_client`) for caching, locks, token storage. |

#### `app/middleware/`

| File | Purpose / usage |
|---|---|
| `context.py` | `RequestContextMiddleware`: accepts/creates `X-Request-ID`, binds it into structlog contextvars (every log line in the request carries it), emits one structured access-log line per request, returns the id in the response header. |

#### `app/modules/` — business domains (FBA 5-layer pattern)

Each module follows **api → schema → service → crud → model**. Thin api, logic in service, SQL in crud.

| File | Purpose / usage |
|---|---|
| `system/api.py` | `/health` (liveness, no deps) and `/ready` (checks Postgres + Redis). Used by Docker healthchecks and Traefik. |

#### `app/modules/activity/` — audit trail (who did what)

Business/compliance audit — distinct from operational logging (`app/core/logging/` → Loki). Persisted, queryable, append-only. See [docs/AUDIT_AND_DATA_MODULES.md](AUDIT_AND_DATA_MODULES.md).

| File | Purpose / usage |
|---|---|
| `activity/model.py` | `ActivityLog` (append-only): action, actor snapshot, polymorphic subject, before/after `changes` (JSONB), `request_id` linking back to Loki/Tempo. |
| `activity/recorder.py` | **The utility for recording activity** (chosen over a mixin/event-listener). `record_activity(...)` writes through the caller's session (atomic), pulls request_id/ip from contextvars, SAVEPOINT-isolated best-effort by default. `model_changes()` diffs a dirty ORM instance (masks secrets). |
| `activity/crud.py` / `service.py` / `api.py` | Append + filtered read; read-only endpoints (`GET /api/activity`, `/{activity_id}`). |

#### `app/modules/files/` — uploaded/scanned documents (S3 + OCR)

| File | Purpose / usage |
|---|---|
| `files/model.py` | `FileEntity`: polymorphic `fileable_*`, Zoho/folder ids, file info, OCR scan fields, S3 storage, checksums/virus/PII security flags, status flags, upload audit. Uses the shared mixins. |
| `files/schema.py` | `FileCreate`, `FileStatusUpdate`, `FileSlimOut`, `FileOut` (with on-the-fly `*_formatted` computed fields: size, amount, dates). |
| `files/crud.py` / `service.py` / `api.py` | Async CRUD; create/list/slim/get/status-update/soft-delete, each recording activity. |

#### `app/modules/favorites/` — per-user polymorphic favorites

| File | Purpose / usage |
|---|---|
| `favorites/model.py` | `Favorite`: `user_id` FK + polymorphic `favoritable_*`, unique per (user, target). |
| `favorites/schema.py` / `crud.py` / `service.py` / `api.py` | Add / remove / **toggle** / list-mine; toggling and add/remove record activity. |

#### `app/modules/users/` — users & authentication

Authentik is the IdP; this module owns the **custom users table** (full port of the
Laravel migrations — every column, PostGIS geography fields, JSONB, all indexes).

| File | Purpose / usage |
|---|---|
| `users/model.py` | `User` (200+ columns: identity, 2FA, status, personal/family, professional, company, preferences, textual + geospatial location, tracking metadata, integration IDs incl. **Authentik mirror state** `authentik_pk`/`authentik_sync_status`/`authentik_sync_error`/`authentik_synced_at`, targets, login tracking, audit, soft deletes) and `PasswordResetToken`. Geography columns get GIST indexes automatically. |
| `users/schema.py` | `UserProfileBase` (every editable field), `UserCreate`/`UserUpdate`/`UserOut` (secrets excluded; geography as WKT strings), `UserListFilters`, auth schemas (login/register/refresh/password flows). |
| `users/crud.py` | Lookups (id/email/username/external_id), filtered + paginated list, create/update, soft-delete/restore/hard-delete, reset-token storage. |
| `users/service.py` | Registration, login with lockout (5 fails → 15 min), token pair issuance/refresh, change/forgot/reset password, **Authentik JIT provisioning** (inbound; `external_id` ← OIDC `sub`), full CRUD lifecycle with WKT→PostGIS conversion. After every local write it calls the **outbound Authentik sync** layer and enqueues a retry task on failure. |
| `users/authentik_sync.py` | **Outbound sync orchestration** (app → Authentik): `sync_create/update_profile/set_password/set_active/delete`, local→Authentik field mapping, `SyncResult` enum, `AUTHENTIK_SYNCED_FIELDS`. Best-effort — never raises into the request. See [docs/AUTHENTIK_SYNC.md](AUTHENTIK_SYNC.md). |
| `users/deps.py` | `CurrentUser` dependency: accepts Authentik RS256 **or** first-party HS256 tokens, resolves/provisions the DB user, rejects deactivated accounts. Used by every protected endpoint. |
| `users/api.py` | `/api/auth/*` (register, login, refresh, me, change/forgot/reset-password, dev-token) and `/api/users/*` (list with filters, create, get, update, soft/hard delete, restore). |
| `documents/api.py` | `POST /api/documents/render` → enqueues Celery PDF task, returns `202 + task_id`; `GET /render/{task_id}` polls status. |
| `documents/service.py` | `render_html_to_pdf()` — calls Gotenberg over the isolated `app-pdf` network, stores output in the shared media volume. Sync by design: PDF work belongs in workers. |
| `documents/schema.py` | Render request / task status schemas. |

#### `app/modules/zoho/` — the Zoho integration

| File | Purpose / usage |
|---|---|
| `core/__init__.py` | Public surface: `zoho_client` (async), `zoho_sync_client` (Celery), exceptions, DTOs. **All Zoho I/O goes through this package.** |
| `core/token_manager.py` | The "never see an expired token" layer: Redis-cached access token with early-expiry margin, single-flight refresh lock shared by every API+worker process, refresh-throttle guard (Zoho allows 10/10 min). |
| `core/rate_limiter.py` | Global Redis per-minute budget (default 90/min, Zoho allows ~100) + per-process concurrency semaphore. Waits instead of letting Zoho 429. |
| `core/circuit_breaker.py` | **Time-based sliding-window breaker** (Redis ZSET) per endpoint group: trips on failure rate OR slow-call rate over the last `ZOHO_CB_WINDOW_SECONDS`; HALF_OPEN single-probe lock prevents thundering herds. |
| `core/client.py` | Async `ZohoClient`: verbs + `paginate()` async iterator, org-id injection, `X-Request-Id` propagation, 401→invalidate-token-retry-once, 429→Retry-After backoff, 5xx/network→exponential retry, Zoho `{code,message}` envelope → typed exceptions. |
| `core/sync_client.py` | Same behaviour for synchronous Celery tasks; shares the token cache, refresh lock, and rate-limit window with the async client. |
| `core/schemas.py` | `ZohoResponse` (envelope-stripped data + `page_context`) and `ZohoPageContext` DTOs. |
| `core/exceptions.py` | `ZohoApiError`, `ZohoAuthError`, `ZohoNotFoundError`, `ZohoValidationError`, `ZohoRateLimitedError`, `ZohoCircuitOpenError` — all subclass the app's `UpstreamError` so the global handlers cover them. |
| `api.py` | `/api/zoho/items`, `/api/zoho/items/{id}`, `/api/zoho/sync/{entity}` — JWT-protected, served from short-TTL cache. |
| `service.py` | Read-through Redis caching over `zoho_client`; sync-state reporting. |
| `crud.py` | Upsert/read of `zoho_sync_state`. |
| `model.py` | `ZohoSyncState` table — legacy incremental-sync cursor per entity (the sync engine uses `zoho_sync_stats` instead). |
| `schema.py` | Transport schemas (`ZohoItem`, `SyncStateOut`). |

#### `app/modules/zoho/sync/` — **the Sync Engine** (see [docs/ZOHO_SYNC_ENGINE.md](ZOHO_SYNC_ENGINE.md))

| File | Purpose / usage |
|---|---|
| `config.py` | Hierarchical config: code defaults → `ZOHO_SYNC_*` env → per-module overrides; `FieldMapping` (dotted Zoho paths → local columns, transforms, outbound flags), `NestedEntityRule`. |
| `mapper.py` | Field-mapping engine: `map_inbound`/`map_outbound`, typed transforms, Zoho timestamp parsing, `flatten_custom_fields` (→ hstore). Missing keys skipped, never NULLed. |
| `mixins.py` | `ZohoEntityMixin` — the strict mirror-table schema: `zoho_id`/`code`/`description`, sync columns (`sync_status`, `sync_error`, `sync_logs`, …), status flags, `metadata` JSONB, `custom_fields` hstore, `zoho_raw` JSONB. All nullable by doctrine. |
| `models.py` | Observability tables: `zoho_sync_stats` (per-module cursors + counters + last-run outcome) and `zoho_queue_logs` (row-level journal of every queued unit of work). |
| `registry.py` | `ZohoModuleDefinition` + `sync_registry`; entity packages self-register on import (autodiscovery via `_ENTITY_PACKAGES`). |
| `engine.py` | Strategies (full/incremental/index), inline vs queued N+1 detail fetches, nested-entity FK resolution, identity matching by `zoho_id` (revives soft-deleted rows), stats upkeep. |
| `outbox.py` | Transactional outbox: journal + Celery push; create back-fills the Zoho-generated id; update escalates to create when never pushed. |
| `api.py` / `schemas.py` | Admin surface `/api/zoho/sync-engine/*`: list modules + stats, trigger runs, browse queue logs. |

#### `app/modules/zoho/organizations/` — Organizations module (worked example)

| File | Purpose / usage |
|---|---|
| `__init__.py` | Registers the module: FULL strategy + inline detail fetches (no upstream modified-filter), BIDIRECTIONAL, full field map incl. nested `address.*` → flat columns. |
| `model.py` | `zoho_organizations` mirror (strict schema + org business columns; partial unique index on live `zoho_id`). |
| `schema.py` / `crud.py` / `service.py` / `api.py` | Local-first CRUD at `/api/zoho/organizations`: reads from Postgres, writes via the outbox, `POST /sync` triggers an engine run. |

#### `app/modules/tags|documents|media|emails|search/` — cross-cutting modules (see [docs/MODULES.md](MODULES.md))

| Path | Purpose / usage |
|---|---|
| `tags/` | Multilingual polymorphic tags: `tags` + `taggables` pivot, `HasTagsMixin` (viewonly, selectinload-friendly), replace-set `/api/tags/sync`. |
| `documents/model.py` + `mixins.py` + `crud.py` | Polymorphic attachments (UUID PK, `documentable_*`), `HasDocumentsMixin`, attach/register/list endpoints alongside the existing Gotenberg render API. Presentation via Pydantic `@computed_field` — no `*_formatted` columns. |
| `media/` | Spatie-style galleries: `media` table + `HasMediaMixin` (`lazy="raise_on_sql"` N+1 firewall), storage strategy (local/S3), declarative `__media_conversions__` produced by Celery/Pillow. |
| `emails/` | Resend transactional email: `emails`/`email_events`/`email_links`, compose-and-queue service, svix-verified webhook sink building the delivered→opened→clicked timeline. |
| `search/indexer.py` | Standalone CDC consumer (compose service `search-indexer`, **FastStream** on aiokafka): Kafka `zoho-mirror.public.*` → Meilisearch. One batch subscriber per topic, `AckPolicy.ACK` (at-least-once), delete/soft-delete aware; bootstraps index settings on startup; OTel consumer spans via `KafkaTelemetryMiddleware`. Runs `python -m app.modules.search.indexer`. |
| `search/registry.py` | `SearchableEntity` registry — THE place a table becomes searchable: model + Out schema + Meilisearch searchable/filterable/sortable attributes; `ensure_index_settings()` pushes them idempotently. |
| `search/builder.py` | `ScoutBuilder` — Meilisearch relevance + Postgres hydration with preserved ordering. |
| `search/api.py` + `schema.py` | `GET /api/search/{index}` (JWT; `q`, repeatable `filter=field:value` validated against the registry, limit/offset) and `GET /api/search/indexes`. Hydrated rows serialized with the entity's registered Out schema. |

#### `app/tasks/` — Celery

| File | Purpose / usage |
|---|---|
| `celery_app.py` | The Celery application: Redis broker/backend, reliability settings (`acks_late`, prefetch 1), queue routing (`integrations`, `documents`, `default`), Beat schedule (incl. the sync-engine dispatcher + weekly full sync), events for Flower/exporter, structlog + OTel wiring via signals. |
| `zoho_sync.py` | **Sync-engine drivers**: `sync_module`, `fetch_detail` (N+1 fan-out), `push_outbound` (outbox executor), `sync_all_due` (config-driven beat dispatcher). Async-in-Celery via throwaway NullPool engines. Queue: `integrations`. |
| `emails.py` | `send_email` — Resend delivery with attachment loading and row-driven retry accounting. Queue: `integrations`. |
| `media.py` | `generate_conversions` — Pillow resizes declared by `__media_conversions__`. Queue: `documents`. |
| `zoho.py` | `sync_items` / `sync_contacts` tasks — paginate via `zoho_sync_client`, outer autoretry with backoff for prolonged outages. Queue: `integrations`. |
| `documents.py` | `generate_pdf` task — Gotenberg rendering. Queue: `documents`. |
| `maintenance.py` | `cleanup_old_media` — deletes generated PDFs older than 14 days. Queue: `default`. |
| `authentik.py` | Authentik sync retry net + `backfill`: `provision_user`, `sync_profile`, `sync_status`, `delete_user`. Sync tasks drive the async client via `asyncio.run` + a throwaway `NullPool` engine (asyncpg-only stack). Queue: `default`. See [docs/AUTHENTIK_SYNC.md](AUTHENTIK_SYNC.md). |

#### `tests/`

| File | Purpose / usage |
|---|---|
| `conftest.py` | Env defaults + `db`/`redis_available` fixtures. Integration tests hit scratch Postgres/Redis containers (ports 55432/56379, see the docstring) and SKIP cleanly when absent. |
| `test_health.py` | Route-table smoke tests (probes + every module router). |
| `zoho_sync/` | Sync-engine suite: config merging, mapper/transforms, engine strategies + N+1 + identity matching (FakeZohoClient + real Postgres), outbox flows, organizations module. |
| `test_circuit_breaker.py` | Sliding-window breaker states, rates, half-open probe (real Redis). |
| `test_soft_delete.py` / `test_tags.py` / `test_emails_webhook.py` | Global filter + partial unique indexes; tag pivot + UUID-PK eager loads; Resend webhook lifecycle. |
| `test_authentik_sync.py` | Outbound Authentik field mapping. |

Dev helper dot-scripts in `backend/`: `.setup_venv.sh` (venv + deps),
`.dev_check.sh [test]` (import smoke + pytest), `.dev_migrate.sh
upgrade|revision` (migrations against the scratch DB).

---

## 3. Frontend — `apps/core-platform/frontend/`

| File | Purpose / usage |
|---|---|
| `package.json` | React 18 + Vite 6 + TypeScript. `npm run dev` / `npm run build`. |
| `vite.config.ts` | Dev server on 5173 with `/api` proxy to the backend for Traefik-less local dev. |
| `tsconfig.json` | Strict TS config for the SPA. |
| `index.html` | Vite entry document. |
| `src/main.tsx` | React root render. |
| `src/App.tsx` | Placeholder app that probes `/health` and mounts `<Search/>` — replace with the real UI. |
| `src/Search.tsx` | Search-as-you-type against `/api/search/{index}`: 200 ms debounce, AbortController stale-request cancellation, Bearer token from localStorage (dev stacks mint one via DEBUG-only `/api/auth/dev-token`). |
| `nginx.conf` | Production serving config (SPA fallback, gzip, immutable asset caching). Copied by the deployment Dockerfile. |
| `.gitignore` | node_modules, dist, env files. |

---

## 4. Deployment — `apps/core-platform/deployment/`

### 4.1 Compose files

| File | Purpose / usage |
|---|---|
| `docker-compose.yml` | The production-safe base: Traefik (only published ports 80/443), Postgres+PostGIS (custom image baking pgvector/pgaudit/pg_partman; logical replication on for Debezium), postgres-init (Authentik DB), postgres-backup (pg_dump every 2 days), Redis, ClickHouse (native Prometheus endpoint :9363), MeiliSearch, backend API, celery-worker/beat/flower/celery-exporter, kafka-exporter (consumer lag), **search-indexer (Kafka CDC → Meilisearch, FastStream)**, frontend, Soketi, Authentik, Kafka (KRaft) + Kafka-UI, **Debezium (Kafka Connect)**, Prometheus (remote-write receiver on), loki-init/Loki + tempo-init/Tempo (non-root, chown init containers), Alloy (postgres/redis/unix exporters built in → remote_write), Grafana, Gotenberg (isolated `app-pdf` network), offen volume backup, acme-dns (production profile). |
| `docker-compose.dev.yml` | Dev overlay: host ports for every internal service, backend bind-mount + `--reload`, Vite dev server, MailHog, Debezium REST on 8083. `./manage.sh dev`. |
| `docker-compose.prod.yml` | Prod overlay: Let's Encrypt DNS-01 certresolver on all public routers, acme-dns wiring. `./manage.sh prod`. |
| `.env` / `.env.example` | All stack configuration: ports, credentials, backup crons, Zoho secrets, tuning. The example is the committed template. |
| `.gitignore` | Ignores `.env`, mkcert certs, acme-dns credentials, backups. |
| `manage.sh` | Day-2 CLI: `dev`, `prod`, `logs`, `build`, `shell-backend`, `migrate`, `makemig`, `db-backup`, `db-restore`, `reset-db`, `healthcheck`, `setup-ssl`, `register-acmedns`, `register-debezium`, `debezium-status`, `authentik-backfill`, `clean`, `prune`. Run `./manage.sh help`. |

### 4.2 Service configs — `config/`

| File | Purpose / usage |
|---|---|
| `traefik/traefik.yml` | Static config: 80→443 redirect, docker + file providers, JSON access logs to stdout (→ Loki), Prometheus metrics entrypoint :8082, ACME DNS-01 resolver. |
| `traefik/dynamic/middlewares.yml` | `security-headers`, `gzip`, `dashboard-auth` (basic-auth guarding the Traefik dashboard **and Flower** — default admin/changeme, replace the hash with `htpasswd -nb`). |
| `traefik/dynamic/tls.yml` | mkcert dev certificates as the default TLS store. |
| `traefik/certs/` | mkcert output (git-ignored). Generated by `scripts/setup-ssl.sh`. |
| `postgres/01-init-db.sh` | Idempotent creation of the Authentik role + database; run by the one-shot `postgres-init` container. |
| `prometheus/prometheus.yml` | Scrape jobs: backend, traefik, celery-exporter, kafka-exporter, clickhouse, soketi, loki, tempo, alloy, grafana, authentik. Postgres/Redis/host metrics arrive via Alloy remote_write (no standalone exporters). |
| `loki/loki.yaml` | Single-binary Loki, TSDB schema v13, filesystem storage, 30-day retention with compactor deletes. |
| `tempo/tempo.yaml` | Tempo with OTLP receivers, local storage, 14-day block retention. |
| `alloy/config.alloy` | Three pipelines: Docker log discovery → label (`service`, `container`, `level`) → Loki; OTLP receiver (:4317/:4318) → batch → Tempo; built-in postgres/redis/unix exporters → remote_write → Prometheus. |
| `postgres/Dockerfile` | Custom image on kartoza/postgis baking `pgvector`, `pgaudit`, `pg_partman` via apt. Built by compose (`core-platform-postgres:latest`). |
| `clickhouse/prometheus.xml` | Enables ClickHouse's native Prometheus handler on :9363. |
| `grafana/provisioning/datasources/datasources.yml` | Prometheus (default), Loki (derived `trace_id` field → Tempo), Tempo (traces→logs link). |
| `debezium/zoho-mirror-connector.json` | Debezium Postgres connector template: `pgoutput` plugin, `zoho_contacts`/`zoho_items` tables, unwrap transform, topic prefix `zoho-mirror`. Extend `table.include.list` as modules grow. |
| `acmedns/config.cfg` | acme-dns server config for production DNS-01 (replace example domains). |

### 4.3 Healthchecks — `healthcheck/`

`./manage.sh healthcheck` runs `test-all.sh`, which executes each script below; each sources `_common.sh` (env loading, check/summary helpers).

| Script | Verifies |
|---|---|
| `test-traefik.sh` | Proxy up, routes responding. |
| `test-postgres.sh` / `test-redis.sh` / `test-clickhouse.sh` / `test-meilisearch.sh` | Data stores. |
| `test-backend.sh` / `test-frontend.sh` | App containers + HTTP. |
| `test-celery.sh` | Worker/beat/flower/exporter running, worker ping, task registration, exporter metrics. |
| `test-soketi.sh` | WebSocket server. |
| `test-authentik.sh` | IAM server. |
| `test-kafka.sh` | KRaft broker: API versions, topic CRUD, produce/consume round-trip, Kafka-UI. |
| `test-prometheus.sh` / `test-loki.sh` / `test-grafana.sh` | Monitoring endpoints. |
| `test-observability.sh` | Loki/Tempo/Alloy ready **and Loki actually receiving container logs** (run from inside the backend container — these services publish no host ports). |
| `test-gotenberg.sh` | Container healthy, **no published host ports (isolation check)**, reachable from backend only, Chromium renders a real PDF. |

### 4.4 Ops scripts — `scripts/`

| Script | Purpose |
|---|---|
| `setup-ssl.sh` | Installs mkcert, generates `local.pem`/`local-key.pem` into `config/traefik/certs/` for `app.local` + subdomains. |
| `reset-db.sh` | Backs up all DBs then resets the postgres volume. |
| `register-debezium.sh` | Substitutes DB credentials into the connector template and PUTs it to the Debezium REST API (idempotent; runs curl inside the container). |

### 4.5 Other

| Path | Purpose |
|---|---|
| `frontend/Dockerfile` | Frontend image: `development` target (node + Vite HMR) and `production` target (builder → nginx, non-root). |
| `backups/` | Output directory for pg_dump archives and volume tarballs (git-ignored). |
