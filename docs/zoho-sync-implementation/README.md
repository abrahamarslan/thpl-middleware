# Zoho Sync Platform — Implementation

Living documentation of the Zoho sync platform **as it is being built** in
`apps/core-platform/backend`. Every component gets a file here the moment it
lands: what it does, why it exists, how it is configured, how it fails, and
how it is tested. If code and this folder disagree, the code is a bug or the
doc is stale — both are defects.

---

## 1. Index

### 1.1 Architecture (the "why" — read before changing anything)

| Doc | What it settles |
|---|---|
| [`../zoho-architecture-decision-framework.md`](../zoho-architecture-decision-framework.md) | v1 — storage doctrine (typed projection over `zoho_raw`), field taxonomy A–H, ownership classes O1/O2/O3, read model ≠ write model |
| [`../zoho-realtime-sync-architecture.md`](../zoho-realtime-sync-architecture.md) | v2 — payload provenance (E1), monotonic fence (E2), fetch-on-notify webhooks, stock lanes, line-item snapshots |
| [`../zoho-sync-platform-architecture.md`](../zoho-sync-platform-architecture.md) | v3 — the control plane: gates, lanes, apply gate, outbox, inbox, error model, observability, migration plan |
| [`../zoho-sync-platform-architecture-delta-v3.1.md`](../zoho-sync-platform-architecture-delta-v3.1.md) | v3.1 — Zoho Inventory, expanded push, **45,000/day governor**, sync scopes, approval gate, reports, sync event log, mixin split |
| [`../ZOHO_SYNC_ENGINE.md`](../ZOHO_SYNC_ENGINE.md) | the first-generation engine that is being replaced (still running) |
| [`../zoho-docs-md/`](../zoho-docs-md/) | vendored Zoho Books API reference — the only source allowed for endpoint shapes |

### 1.2 Implementation (the "what is actually built")

| Component | Doc | Status | Code |
|---|---|---|---|
| Error model & retry policy | [`errors-and-policy.md`](errors-and-policy.md) | ✅ built | `app/modules/zoho/core/errors.py`, `policy.py` |
| Quota day & pacing curve | [`governor.md`](governor.md) §2 | ✅ built | `app/modules/zoho/core/pacing.py` |
| Governor (daily quota + rate + concurrency) | [`governor.md`](governor.md) | ✅ live | `app/modules/zoho/core/governor.py`, `core/lua/*.lua` |
| Circuit breaker v2 | [`circuit-breaker.md`](circuit-breaker.md) | ✅ live | `app/modules/zoho/core/breaker.py` |
| Token manager v2 & encrypted credential store | [`auth.md`](auth.md) | ✅ live | `app/modules/zoho/core/auth.py`, `ZohoOAuthCredential`, migration `c3d4e5f6a7b8` |
| Transport (single async client through the gates) | [`transport.md`](transport.md) | ✅ live | `app/modules/zoho/core/transport.py` (+ shim `client.py`) |
| OTel URL scrubbing (secrets out of Tempo) | [`auth.md`](auth.md) §6 | ✅ live | `app/core/observability.py` |
| Engine switches (global / direction / module / auto auth-pause) | [`control-plane.md`](control-plane.md) §2 | ✅ live | `app/modules/zoho/control/switches.py` |
| Run leases & fenced cursors | [`control-plane.md`](control-plane.md) §3 | ✅ live | `app/modules/zoho/control/runs.py` |
| Planner (single scheduler) | [`control-plane.md`](control-plane.md) §4 | ✅ live | `app/modules/zoho/control/planner.py`, task `planner_tick` |
| Retention (partitions + policies) | [`control-plane.md`](control-plane.md) §5 | ✅ live | `app/modules/zoho/control/retention.py`, task `retention_maintenance` |
| `soft_delete_missing` guard | [`control-plane.md`](control-plane.md) §6 | ✅ live | `app/modules/zoho/sync/engine.py` |
| Zoho gauges on `/metrics` | [`control-plane.md`](control-plane.md) §7 | ✅ live | `app/modules/zoho/control/metrics.py` |
| Record-level sync events | [`sync-events.md`](sync-events.md) | ✅ live (pull) | `app/modules/zoho/control/events.py` |
| Operator API | [`operator-api.md`](operator-api.md) | ✅ live | `app/modules/zoho/admin/` |
| Settings tables migration (pre-existing gap) | [`ERRORS…`](ERRORS-AND-THEIR-RESOLUTIONS.md) E12 | ✅ | migration `e6f7a8b9c0d1` |
| Apply gate (fence, provenance, hash no-op, resurrection) | [`apply-gate.md`](apply-gate.md) §2 | ✅ live (pull) | `app/modules/zoho/sync/apply.py`, `sync/engine.py` |
| Detail-call skip (N+1 saver) | [`apply-gate.md`](apply-gate.md) §3 | ✅ live | `sync/engine.py` |
| Bounded slices, per-page commit, resume | [`apply-gate.md`](apply-gate.md) §4 | ✅ live | `sync/engine.py`, `app/tasks/zoho_sync.py::execute_leased_run` |
| Mixin split (Identity / Mirror / Pushable / Approval / WarehouseScoped / Child) | [`apply-gate.md`](apply-gate.md) §5 | ✅ built | `sync/mixins.py`, migration `f79d022c961a` |
| Config resolver (runtime per-module overrides) | [`config-resolver.md`](config-resolver.md) | ✅ live | `app/modules/zoho/control/config.py`, `/api/zoho/admin/config/*` |
| Planner continuations, write-pressure gate, governor reseed | [`control-plane.md`](control-plane.md) §4.3–4.5 | ✅ live | `control/planner.py`, `Governor.reseed` |
| Package-by-feature layout + registry validator | [`package-by-feature.md`](package-by-feature.md) | ✅ live | `app/modules/<feature>/zoho/`, `sync/registry.py` |
| Batched page apply | [`apply-gate.md`](apply-gate.md) §4b | ✅ live | `sync/engine.py::_apply_page` |
| Worker event loop (ADR‑3) | [`worker-event-loop.md`](worker-event-loop.md) | ✅ live | `app/tasks/_loop.py` |
| Adapter: organizations | [`adapters/organizations.md`](adapters/organizations.md) | ✅ live (moved) | `app/modules/organizations/` |
| Adapter: currencies (O1) | [`adapters/currencies.md`](adapters/currencies.md) | ✅ live (pull) | `app/modules/currencies/`, migration `91e970e99176` |
| Adapter: taxes (O1) | [`adapters/taxes.md`](adapters/taxes.md) | ✅ live (pull) | `app/modules/taxes/`, migration `91e970e99176` |
| Adapter: locations (O1) | [`adapters/locations.md`](adapters/locations.md) | ✅ live (pull) | `app/modules/locations/`, migration `e6e42c16c52e` |
| Adapter: Zoho users (O1) | [`adapters/users.md`](adapters/users.md) | ✅ live (pull) | `app/modules/zoho_users/`, migration `e6e42c16c52e` |
| Import contracts (dependency rules) | [`package-by-feature.md`](package-by-feature.md) §3 | ✅ enforced by tests | `.importlinter`, `tests/test_import_contracts.py` |
| Engine CLI + live runbook | [`cli.md`](cli.md) | ✅ | `app/modules/zoho/cli.py` |
| Connection readiness (`GET /api/zoho/auth/connection`) | [`auth.md`](auth.md) §5c | ✅ live | `app/modules/zoho/core/connection.py` |
| **Tenancy**: tenants, organization tree, roles, scoping of every table | [`../tenancy/README.md`](../tenancy/README.md) | ✅ live | `app/database/{mixins,tenancy}.py`, `app/modules/{tenants,organizations,roles}/`, migration `7c2e91d4b0a8` |
| **Location hub**: canonical places + the polymorphic address book (a Zoho location becomes a place) | [`../geo/README.md`](../geo/README.md) | ✅ live | `app/modules/geo/`, migration `4f2f2a8c7898` |
| **Geocoding**: swappable providers (Google · Mapbox · Nominatim · Pelias) + Valhalla routing | [`../geo/geocoding.md`](../geo/geocoding.md) | ✅ live (none configured by default) | `app/modules/geo/geocoding/` |
| Outbox v2 & approval gate | `outbox-and-approvals.md` | ⏳ planned | — |
| Webhook inbox | `webhooks.md` | ⏳ planned | — |
| Feature adapters (contacts, items, …) | `adapters/<module>.md` | ⏳ planned | — |

### 1.3 Operations

| Doc | Purpose |
|---|---|
| [`ERRORS-AND-THEIR-RESOLUTIONS.md`](ERRORS-AND-THEIR-RESOLUTIONS.md) | every error hit while building or running this platform, its root cause and its fix — **append, never rewrite** |

---

## 2. Build order

Phases follow the migration plan (v3 §15 as amended by v3.1 §14). The current
position is marked.

| Phase | Scope | Status |
|---|---|---|
| 0 | Verification spike against a sandbox org (capabilities, quota reset, webhook signature, ids across Books/Inventory) | ⏳ not started — blocks lane enablement, not core work |
| 1 | Stop-the-bleeding fixes on the existing engine (beat waste, POST retries, secret leakage, unsafe reconcile deletes) | **✅ done** (2026‑09‑18) |
| **2** | **Platform core: error model, policy, governor, breaker, auth, transport** | **✅ done** (2026‑09‑18) — per-process event loop (ADR‑3) deferred to Phase 4 task rework |
| 3 | Infrastructure (Redis split, worker topology, Prometheus job, Traefik webhook route) | ⏳ |
| 4 | Control plane (switches, config resolver, planner, leases, cursors) + apply gate + control tables | **✅ done** (2026‑09‑19) — ADR‑3 per-process event loop moved to Phase 5 (all async tasks must switch together); batched `INSERT … ON CONFLICT` apply moves with the Phase 5 module rebuild |
| 5 | Package-by-feature layout + O1 masters (+ ADR‑3 event loop, batched apply) | **✅ done** (2026‑09‑19) — organizations, currencies, taxes, locations, users; import contracts; engine CLI. **Next step is a live run** ([`cli.md`](cli.md) §2) before any new module |
| 6 | Pull for contacts, items, batches | ⏸ **on hold** until the masters have been seen working against the live org |
| 7 | Pull for documents (Books + Inventory) | ⏳ |
| 8 | Push: outbox v2, approval gate, module rollout | ⏳ |
| 8b | Reports | ⏳ |
| 9 | Decommission the v1 engine paths | ⏳ |

---

## 3. What exists today (2026‑09‑19)

```
app/modules/zoho/core/
├── errors.py        ✅ ErrorCategory + typed exceptions + fingerprints
├── policy.py        ✅ classification & retry decisions (pure)
├── pacing.py        ✅ quota-day arithmetic + background pacing curve
├── governor.py      ✅ THE admission gate (quota + rate + concurrency)
├── breaker.py       ✅ circuit breaker v2 (owned single probe, 429-safe)
├── auth.py          ✅ token manager v2 + encrypted CredentialStore
├── transport.py     ✅ the single async client (Books + Inventory)
├── lua/
│   ├── governor_acquire.lua   ✅ one atomic admission decision
│   └── governor_release.lua   ✅ settle a lease (commit or refund)
├── client.py        ♻ shim → transport.py (v1 import path)
├── exceptions.py    ♻ shim → errors.py (v1 import path)
└── schemas.py       kept — ZohoResponse / ZohoPageContext

app/modules/zoho/control/          (Phase 4)
├── models.py        ✅ zoho_sync_runs · zoho_sync_cursors · zoho_quota_days ·
│                       zoho_sync_events (partitioned) · zoho_retention_policies
├── switches.py      ✅ engine switches (audited settings + Redis mirror)
├── runs.py          ✅ run leases (DB-enforced singleton) + fenced cursors
├── planner.py       ✅ the single scheduler (pure plan() + async tick())
├── events.py        ✅ record-level sync events with masked field diffs
├── retention.py     ✅ partition maintenance + policy purges
├── config.py        ✅ runtime per-module overrides (audited, versioned cache)
└── metrics.py       ✅ gauges on /metrics from the planner snapshot

app/modules/zoho/sync/             (v1 engine, now behind the apply gate)
├── apply.py         ✅ apply-gate decision table + canonical hashing (pure)
├── engine.py        ✅ gate · detail skip · bounded slices · page hook
└── mixins.py        ✅ Identity / Mirror / Pushable / Approval / WarehouseScoped /
                        Child mixins; ZohoEntityMixin = compatibility alias

app/modules/zoho/admin/            ✅ operator API at /api/zoho/admin

app/modules/<feature>/zoho/        (Phase 5 — package-by-feature)
├── organizations/zoho/  ✅ spec.py · fields.py   (feature moved from app/modules/zoho/organizations)
├── currencies/zoho/     ✅ O1 master, /settings/currencies (un-paginated)
├── taxes/zoho/          ✅ O1 master, /settings/taxes
├── locations/zoho/      ✅ O1 master, /locations (un-paginated)
└── zoho_users/zoho/     ✅ O1 master, /users?filter_by=Status.All

app/modules/zoho/cli.py            ✅ check · sync · status · runs (see cli.md)
.importlinter                      ✅ 3 dependency contracts (run by the test suite)

app/tasks/_loop.py                 ✅ one event loop per worker process (ADR‑3)

deleted: sync_client.py · rate_limiter.py · circuit_breaker.py · token_manager.py
         app/tasks/zoho.py (+ its two beat entries) · GET /api/zoho/items[/{id}]
         tests/test_circuit_breaker.py (v1 breaker)
         Beat: zoho-sync-dispatcher · zoho-full-sync-weekly (→ planner)
```

### 3.1 Behaviour changes now in effect

| Change | Effect on the running system |
|---|---|
| Every Zoho call goes through the governor | daily ceiling 45,000 (`ZOHO_DAILY_HARD_LIMIT`), thresholds at 80/93/97.8 %, per-minute 80, **6 concurrent org-wide** (was 8 *per process*) |
| v1 engine calls default to priority `INCREMENTAL` | they are paced by the business-hours curve and pause at `ESSENTIAL` |
| POST never retried after a 5xx/read timeout | a create in doubt raises `ZohoAmbiguousOutcome`; the v1 Celery tasks no longer auto-retry it (`dont_autoretry_for`), so it fails loudly into `zoho_queue_logs` until outbox v2 resolves it by lookup |
| 429 no longer opens the circuit | throttling is handled by the governor |
| `paginate()` raises on a list without `page_context` | v1 used to end the scan silently |
| Beat entries `zoho-sync-items` / `zoho-sync-contacts` removed | ~1,700+ wasted calls/day saved (row counting only) |
| `GET /api/zoho/items`, `GET /api/zoho/items/{id}` removed | no request path calls Zoho; clients must wait for the items mirror |
| Refresh token no longer in `setting_values` / `setting_audit_logs` / Redis | the migration deleted those rows — **reconnect once** via `/api/zoho/auth/initiate` after deploying if `ZOHO_REFRESH_TOKEN` is not set in the env |
| Span URLs scrubbed | `client_secret`, `refresh_token`, `code` no longer reach Tempo |
| New env vars passed through compose | `ZOHO_TOKEN_PERSISTENCE_ENABLED`, `ZOHO_TOKEN_ENCRYPTION_KEY`, `ZOHO_GOVERNOR_ENABLED`, `ZOHO_CONTRACT_DAILY_LIMIT`, `ZOHO_DAILY_HARD_LIMIT`, `ZOHO_RATE_LIMIT_PER_MINUTE`, `ZOHO_MAX_CONCURRENT_REQUESTS`, `ZOHO_QUOTA_DAY_TIMEZONE`, `ZOHO_INVENTORY_API_URL` |
| **Phase 4:** the planner is the only Zoho scheduler | one Beat entry every minute; a module can never run twice at once (DB lease); the weekly full is per module and paused when quota is tight |
| **Phase 4:** runs are recorded | `zoho_sync_runs` (status, counters, error fingerprint, duration) — visible at `/api/zoho/admin/runs` |
| **Phase 4:** every inserted/updated/tombstoned record is logged | `zoho_sync_events` with masked old → new values; `/api/zoho/admin/records/{module}/{ref}/events` |
| **Phase 4:** `soft_delete_missing` is off | local rows are no longer deleted because one list scan missed them |
| **Phase 4:** a revoked refresh token pauses the whole engine | cleared automatically by a successful reconnect |
| **Phase 4:** settings tables now exist | the hierarchical settings module works in migrated databases for the first time (E12) |
| **Phase 4b:** identical payloads write nothing | no UPDATE, no WAL, no Debezium event for records that did not change (after one hash-seeding pass per row) |
| **Phase 4b:** older payloads are ignored | a late webhook/list page can no longer overwrite newer data (`stale_ignored` events) |
| **Phase 4b:** unchanged records skip the detail call | steady-state scans of detail modules spend list pages only |
| **Phase 4b:** runs are 240 s slices | long scans yield and resume at the next page instead of being killed at 540 s and rolled back; every page is committed and heartbeated |
| **Phase 4b:** a user's local delete is no longer undone by a pull | only sync tombstones (`remote_deleted_at`) are resurrected |
| **Phase 4b:** inbound apply keeps push state | `sync_status` `queued`/`syncing`/`error` survive a pull |
| **Phase 4b:** sync knobs are runtime-tunable | `/api/zoho/admin/config/{module}` — interval, strategy, budgets, … (audited) |
| **Phase 4b:** background lanes yield under write pressure | Debezium slot lag > 512 MB or `integrations` queue > 5000 |
| **Phase 5:** currencies, taxes, locations and Zoho users are mirrored | daily; `GET /api/zoho/{currencies,taxes,locations,users}[/{ref}]`; ≈ 6 Zoho calls per full master pass |
| **Phase 5:** organizations sync no longer fails on the missing `page_context` | E29 — it would have failed every run |
| **Phase 5:** a page is written with one query + one flush | ~2 statements per page instead of ~2 per record |
| **Phase 5:** workers keep their DB/Redis pools between tasks | no new connection per task; peak = concurrency × (pool + overflow) |
| **Phase 5:** a broken module spec stops startup | `RegistryError` lists every problem (API and workers) |
| **Phase 5:** organizations code moved | `app/modules/organizations/`; HTTP paths unchanged |

Rollback lever: `ZOHO_GOVERNOR_ENABLED=false` makes every governor acquire a
no-op (breaker, token manager and transport stay).

### 3.2 Deploying to the WSL Docker stack

```bash
cd apps/core-platform/deployment
# 1. set ZOHO_TOKEN_ENCRYPTION_KEY="$(openssl rand -base64 48)" and
#    ZOHO_TOKEN_PERSISTENCE_ENABLED=true in .env (dev) / .env.prod (prod)
# 2. rebuild the shared backend image and recreate backend + workers + beat
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build backend celery-worker celery-beat
# 3. apply migrations (zoho_oauth_credentials, control tables, settings tables,
#    apply-gate columns f79d022c961a, zoho_currencies + zoho_taxes 91e970e99176,
#    zoho_locations + zoho_users e6e42c16c52e)
docker compose exec backend alembic upgrade head
# 4. reconnect Zoho once: open https://<domain>/api/zoho/auth/initiate
# 5. set ZOHO_OPERATOR_EMAILS="you@tarrinahealth.com" for /api/zoho/admin access
# 6. recreate celery-beat so the old dispatcher entries are gone (schedule file is in /tmp)
# 7. optional: create the first week of event partitions now
docker compose exec celery-worker celery -A app.tasks.celery_app call app.tasks.zoho_sync.retention_maintenance
```

Phase 5 extra step — re-register the Debezium connector so the four new mirror
tables (currencies, taxes, locations, users) stream; they are empty at
deploy, so no snapshot is needed:
`bash scripts/register-debezium.sh`.

Checklist for every change that adds a `ZOHO_*` setting: `conf.py`,
`deployment/docker-compose.yml` (`x-backend-env`), `.env.example`,
`.env.prod.example` — in the same change (E25).

### 3.3 Test counts

`tests/zoho_core`: 250 — policy 34, transport 23, apply gate 19, config
resolver 18, breaker 17, governor 15, switches 15, planner 14, auth 12,
pacing 11, sync events 10, task retry policy 10, operator API 9, registry 8,
planner tick 6, retention 6, runs 5, **masters e2e 4**, URL scrubbing 4,
batch apply 4, slices 3, masters 3. `tests/zoho_sync`: 35.
`tests/test_task_loop.py`: 5 · `tests/test_import_contracts.py`: 1.
**0 skipped** with the scratch services up. Full suite: 420 passed, 3 failed —
the 3 are pre-existing and unrelated (E07).

### 3.4 Next step — see it live (no new modules)

Phase 6 (contacts, items, batches) is **on hold by decision** until the engine
has been watched working on the live org with the five masters. Runbook:
[`cli.md`](cli.md) §2 — bring the stack up, connect Zoho once, then
`cli check --live` → `cli sync` → `cli status`, and exercise the no-op second
pass, a Zoho-side edit, the pause switch and the planner. Findings go to
`ERRORS-AND-THEIR-RESOLUTIONS.md`; every **[verify]** in the adapter docs
(pagination of organizations, currencies and locations) gets confirmed or
fixed there.

---

## 4. Conventions for this folder

1. **One file per component**, named after the component, lowercase.
2. Every component doc has the same shape: *Purpose · Where it lives ·
   How it works · Configuration · Failure modes · Metrics/logs · Tests ·
   Open questions*.
3. Facts that depend on unverified Zoho behaviour carry **[verify]** and a
   pointer to the Phase‑0 checklist.
4. Anything that deviates from `docs/architecture-prompts/master-prompt.md`
   is flagged **⚠ scope** with the reason, in both the code and the doc.
5. Errors found while building go to `ERRORS-AND-THEIR-RESOLUTIONS.md`
   immediately, with the exact message — future-you greps that file first.

## 5. Running the tests

```bash
# from apps/core-platform/backend (WSL)
.venv/bin/python -m pytest tests/zoho_core -q          # platform core
.venv/bin/python -m pytest -q                          # everything

# integration tests need the scratch containers. They SKIP cleanly without
# them, so check the skip count (ERRORS E09). One helper starts both, waits for
# Postgres through kartoza's restart and applies migrations:
bash .dev_scratch.sh
bash .dev_scratch.sh stop        # remove both containers
```

From Windows, call scripts rather than inline bash (ERRORS E08):

```powershell
wsl -d Ubuntu -- bash -lc "bash /home/a2/projects/th-middleware/apps/core-platform/backend/.dev_scratch.sh"
```
