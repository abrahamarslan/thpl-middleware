# Seeing the engine work — CLI and live runbook

**Status:** ✅ · **Code:** `app/modules/zoho/cli.py` ·
**Tests:** `tests/zoho_core/test_masters_e2e.py` (the whole pipeline with only
the HTTP wire and the OAuth token faked; run it with `-s` to see the tables below)

---

## 1. Commands

Run inside the backend container (`dc` = `docker compose -f docker-compose.yml -f docker-compose.dev.yml`,
from `apps/core-platform/deployment`):

| Command | What it does | Zoho calls |
|---|---|---|
| `dc exec backend python -m app.modules.zoho.cli check` | registered modules (specs validated), token health, governor (used / limit / state / reset time), switches | 0 |
| `… cli check --live` | the above + **one** `GET /organizations` at interactive priority, proving credentials and connectivity | 1 |
| `… cli sync` | a **leased** run of every registered module, now, in this process (lane `manual`, trigger `cli`), then a results table | see §3 |
| `… cli sync taxes currencies` | only those modules | |
| `… cli sync organizations --mode full` | override the strategy | |
| `… cli status` | per module: mirror table, live rows, newest sync, last run and its counters, interval | 0 |
| `… cli runs [--limit 20] [--module taxes]` | recent runs (all triggers: planner, cli, operator, api) | 0 |

`sync` goes through exactly the same code as the Celery worker: switches →
governor → breaker → token manager → transport → apply gate → batched page
write → sync events → run record. A paused engine or a spent quota shows as
`yielded` / `suspended` with the reason, never as a bypass.

---

## 2. Live runbook (WSL Docker, first time)

The dev stack must be up, and Zoho must be connected **once** (browser consent
— only a person can do this).

```bash
cd apps/core-platform/deployment
alias dc='docker compose -f docker-compose.yml -f docker-compose.dev.yml'

# 0. .env — keep the refresh token encrypted in Postgres, and allow yourself the operator API
#    ZOHO_TOKEN_PERSISTENCE_ENABLED=true
#    ZOHO_TOKEN_ENCRYPTION_KEY="<openssl rand -base64 48>"
#    ZOHO_OPERATOR_EMAILS="you@tarrinahealth.com"

# 1. build + start, apply migrations (control plane, apply gate, 4 master tables)
dc up -d --build
dc exec backend alembic upgrade head

# 2. connect Zoho (auth.md §5b): Swagger → GET /api/zoho/auth/initiate?redirect=false
#    (leave return_url EMPTY), open data.authorization_url, consent.
#    The callback answers {"connected": true, "persisted": true}.

# 3. prove it — also verifies ZOHO_ORGANIZATION_ID against the orgs the user can see
dc exec backend python -m app.modules.zoho.cli check --live

# 4. watch the engine pull the masters
dc exec backend python -m app.modules.zoho.cli sync
dc exec backend python -m app.modules.zoho.cli status
```

What to try next, and what you should see:

| Try | Expected |
|---|---|
| `cli sync` a second time | every module `succeeded` with `created 0 · updated 0 · unchanged N` — the apply gate writes nothing |
| edit a tax rate in Zoho → `cli sync taxes` | `updated 1`; `GET /api/zoho/admin/records/taxes/<tax_id>/events?by=zoho` shows the old → new value |
| `PUT /api/zoho/admin/switches/engine_paused {"value": true, …}` → `cli sync` | every module `yielded`, reason `switch:engine_paused`, 0 Zoho calls |
| leave it running (celery-beat up) | `cli runs` shows `trigger=planner` runs: organizations every 6 h, the masters daily |
| `PUT /api/zoho/admin/config/taxes/sync_interval_minutes {"value": 60, …}` | the planner schedules taxes hourly from the next tick |
| `GET /api/zoho/currencies`, `/taxes`, `/locations`, `/users`, `/organizations` | the mirrors, served locally (0 Zoho calls) |

---

## 2b. Logs — where the requests and responses are

Every Zoho call is logged by the transport through structlog (`logger` in
`app/modules/zoho/core/transport.py`). The logs go to stdout, then Docker,
then **Alloy → Loki**. Grafana (`https://app.local/grafana`, Explore → Loki)
shows them with the rest of the stack.

| Event | When | Fields |
|---|---|---|
| `zoho.transport.call_completed` | every successful call | module, method, path template, status, duration, response bytes, priority, `zoho_request_id`, `run_id` |
| `zoho.transport.call_failed` / `…retrying` | every failed attempt | the above + `zoho_code`, Zoho's `message`, `error_category`, `reason` |
| `zoho.transport.http_exchange` | **only with `ZOHO_HTTP_LOG_BODIES=true`** | full URL, query, request body, **response body** (truncated to `ZOHO_HTTP_LOG_BODY_MAX`, default 2000) |
| `zoho.run.started` / `zoho.run.finished` | each run | counters, status, stop reason |

Bodies are not logged by default: they hold customer and personal data, and
they would flood Loki. The OAuth token travels in a header and is never
logged. Span URLs in Tempo are scrubbed (auth.md §6).

```bash
# live tail of the worker (planner-driven runs) — Zoho calls only
dc logs -f celery-worker | grep zoho.transport
# a CLI run prints its own logs to your terminal
dc exec backend python -m app.modules.zoho.cli sync taxes
# temporarily see request/response bodies for a CLI run (no restart needed)
dc exec -e ZOHO_HTTP_LOG_BODIES=true backend python -m app.modules.zoho.cli sync taxes
```

Loki (Grafana → Explore): `{container="celery-worker"} |= "zoho.transport"`, or
`|= "<run_id>"` to follow one run.

## 2c. Troubleshooting the first run

| You see | Meaning | Fix |
|---|---|---|
| `zoho_code=6041 This user is not associated with the CompanyID…` | `ZOHO_ORGANIZATION_ID` is not an org of the connected user | `cli check --live` lists the right id → `.env` → recreate backend + celery-worker + celery-beat. **No re-consent needed** (E35) |
| `check --live` crashed with a circular import | fixed (E33) | — |
| `transform_failed … fiscal_year_start_month` | the live API sends a month name | fixed (E34) |
| a module `failed` with `ZohoContractError … page_context` | a list endpoint answered without pagination; that module needs `paginated=False` | report it; see E28/E29 |
| `yielded switch:auth_paused` | the refresh token was revoked | reconnect (auth.md §5b) |

**Containers down/up:** the refresh token is stored encrypted in Postgres
(volume `app_postgres_data`), so `dc down` / `dc up` does **not** need a new
consent. You need one only if the volume is deleted (`dc down -v`),
`ZOHO_TOKEN_ENCRYPTION_KEY` changes (the stored token can no longer be
decrypted — keep the key with your secrets), or the token is revoked in Zoho
or via `/api/zoho/auth/revoke`.

## 3. Cost of one full master pass

| Module | Calls | Why |
|---|---|---|
| organizations | 1 + N orgs (usually 2) | list is thin → one detail per org |
| currencies | 1 | single un-paginated response |
| taxes | ⌈taxes / 200⌉ (usually 1) | paginated |
| locations | 1 | single un-paginated response |
| users | ⌈users / 200⌉ (usually 1) | paginated, `filter_by=Status.All` |
| **total** | **≈ 6** | of 45,000/day |

---

## 4. Reading a `sync` result

```
module         status     mode  pages  listed  created  updated  unchanged  stale_ignored  errors  details_saved  seconds  stop_reason
organizations  succeeded  full  1      1       1        0        0          0              0       0              0.4      —
currencies     succeeded  full  1      2       2        0        0          0              0       0              0.0      —
taxes          succeeded  full  1      2       2        0        0          0              0       0              0.0      —
locations      succeeded  full  1      1       1        0        0          0              0       0              0.0      —
users          succeeded  full  1      2       2        0        0          0              0       0              0.0      —
```
(from `test_masters_e2e.py -s` with Zoho's documented payloads)

| Status | Meaning | Action |
|---|---|---|
| `succeeded` / `partial` | scan complete (partial = some records failed, see `errors` and `zoho_queue_logs`) | — |
| `yielded` | a slice budget, the governor or a switch stopped it; `stop_reason` says which | the planner resumes it |
| `suspended` | daily quota spent (Zoho code 45) | resumes next quota day |
| `failed` | `stop_reason` carries the exception (`ZohoAuthRevokedError` → reconnect; `ZohoContractError` → a response shape we did not expect, see ERRORS E28/E29) | check logs / `cli runs` |
| `skipped` | another run of the same lane is active (lease) | — |
