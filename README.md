# TH Middleware — Core Platform

Enterprise middleware between our applications (sales, delivery, analytics) and **Zoho Books**.
Built on the pseudo 3-tier architecture from [fastapi-best-architecture](https://github.com/fastapi-practices/fastapi_best_architecture):

| workflow       | layer     | location (per module)          |
|----------------|-----------|--------------------------------|
| view           | `api`     | `app/modules/<m>/api.py`       |
| data transmit  | `schema`  | `app/modules/<m>/schema.py`    |
| business logic | `service` | `app/modules/<m>/service.py`   |
| data access    | `crud`    | `app/modules/<m>/crud.py`      |
| model          | `model`   | `app/modules/<m>/model.py`     |

See `app/modules/zoho/` for a complete example of all five layers.

## Repository layout

```
apps/core-platform/
├── backend/           FastAPI app + Celery tasks (one image, four roles)
│   ├── app/
│   │   ├── core/      settings, app factory, OpenTelemetry
│   │   ├── common/    logging, exceptions, response envelope, JWT
│   │   ├── database/  async SQLAlchemy + Redis
│   │   ├── middleware/ request-id + access logging
│   │   ├── modules/   auth, zoho, documents, system  (api/schema/service/crud/model)
│   │   └── tasks/     celery_app, zoho sync, pdf generation, maintenance
│   └── alembic/       async migrations
├── frontend/          React + Vite (nginx in production)
└── deployment/
    ├── docker-compose.yml        base (production-safe: only Traefik on host)
    ├── docker-compose.dev.yml    dev ports, hot reload, MailHog
    ├── docker-compose.prod.yml   ACME DNS-01 TLS
    ├── config/                   traefik, prometheus, loki, tempo, alloy, grafana, postgres
    ├── healthcheck/              per-service test scripts (./manage.sh healthcheck)
    └── manage.sh                 day-2 operations
```

## Async architecture — Celery: where each piece is used

| Component | Service | Used for |
|---|---|---|
| **Worker** | `celery-worker` | Zoho catalog/contact syncs, pushing orders to Zoho, **PDF generation via Gotenberg** (invoices, delivery notes), future OR-Tools route optimisation & rostering jobs (CPU-heavy, minutes-long — must never block API workers) |
| **Queues** | Redis (broker, DB 2) | `default` (misc), `integrations` (Zoho — rate-limit sensitive, retry w/ backoff), `documents` (slow, CPU-bound). Separate queues mean a burst of PDFs can't starve order syncs; scale per-queue workers independently |
| **Beat** | `celery-beat` | Cron-style scheduler: item sync every 15 min, contact sync every 2 h, media cleanup nightly. Replaces APScheduler (one scheduler, persistent, observable). **Run exactly one instance** |
| **Flower** | `flower` | Live task dashboard at `https://<domain>/flower` (basic-auth via Traefik): inspect running/failed tasks, retry, revoke |
| **Exporter** | `celery-exporter` | Prometheus metrics: task throughput, runtime percentiles, failure counts → Grafana alerting ("Zoho sync failing for 1 h") |

The API enqueues and returns `202 + task_id` (see `POST /api/documents/render`); clients poll or get a Soketi push on completion. Kafka carries **domain events** (order placed, delivery completed) into ClickHouse for analytics — Celery is for *jobs*, Kafka for *event streams*; don't mix the two.

**Debezium (CDC):** the `debezium` Kafka Connect service streams row-level changes from the Postgres `zoho_*` mirror tables into Kafka (`zoho-mirror.public.*`), from where ClickHouse ingests them. Register/inspect with `./manage.sh register-debezium` / `debezium-status`. Full pipeline: [docs/zoho-module-implementation-guide.md](docs/zoho-module-implementation-guide.md).

**Search (CDC → Meilisearch):** the same WAL stream feeds `search-indexer` (FastStream), which keeps Meilisearch indexes in sync (~1–3 s freshness) — deletes and soft-deletes included. Query via `GET /api/search/{index}` (Meilisearch ranks, Postgres hydrates); the frontend ships a debounced `<Search/>` component. Adding a searchable table = Debezium `table.include.list` + `SEARCH_CDC_TOPICS` + one `SearchableEntity` entry in `app/modules/search/registry.py`. Details: [docs/MODULES.md](docs/MODULES.md).

## Observability — Loki + Alloy + Tempo + Prometheus + Grafana

```
containers (JSON logs, stdout) ──► Alloy (docker discovery) ──► Loki ──┐
backend/workers (OTLP traces)  ──► Alloy (:4318)            ──► Tempo ─┼──► Grafana
backend /metrics, exporters    ◄── Prometheus (scrape)      ───────────┘
```

- **Logs**: every service writes JSON to stdout. The backend binds `request_id` (and `trace_id` when OTel is on) into every log line.
- **Traces**: FastAPI, httpx (Zoho calls!), SQLAlchemy, Redis and Celery are auto-instrumented — one trace shows API → DB → Zoho → Celery task.
- **Metrics**: Prometheus scrapes backend, Traefik, Celery exporter, postgres/redis exporters, Soketi, Loki/Tempo/Alloy themselves.

**Debug runbook** (Grafana → Explore → Loki):
```logql
{service="backend"} | json | level="error"                  # all backend errors
{service=~"backend|celery-worker"} | json | request_id="X"  # one request end-to-end
{container="traefik"} | json | OriginStatus >= 500          # 5xx at the edge
```
From an error log line, click the `trace_id` derived field to jump to the full Tempo trace; from a slow trace, jump back to its logs.

## Security decisions

- **Gotenberg is application-private**: no host port, no Traefik route; it lives alone on the `app-pdf` network which only `backend` and `celery-worker` join. Nothing else — host included — can reach it. (`test-gotenberg.sh` verifies the isolation.)
- **Base compose publishes only Traefik 80/443.** Postgres, Redis, Kafka, ClickHouse, etc. get host ports *only* via `docker-compose.dev.yml`.
- Flower & the Traefik dashboard sit behind basic-auth (`config/traefik/dynamic/middlewares.yml` — **default admin/changeme, replace the hash**).
- ⚠️ **Rotate the Zoho client secret** — the previous one was committed in plaintext. `.env` files are git-ignored; commit only `.env.example`.

## Backups (every 2 days)

- `postgres-backup`: `pg_dump` of app + authentik DBs, cron `0 2 */2 * *`, retained 14 days, written to `deployment/backups/`.
- `backup` (offen): tars non-DB stateful volumes (grafana, authentik media, meilisearch) at `0 3 */2 * *`.
- Live Postgres data files are **never** volume-copied (inconsistent restores) — that was removed deliberately.
- Restore: `./manage.sh db-restore <file>`.

## Running

```bash
cd apps/core-platform/deployment
cp .env.example .env            # then fill in secrets (dev .env already present)
./scripts/setup-ssl.sh          # mkcert dev certs (run once)
# hosts file: 127.0.0.1 app.local auth.app.local ws.app.local traefik.app.local
./manage.sh dev                 # full stack with hot reload
./manage.sh migrate             # alembic upgrade head
./manage.sh healthcheck         # verify all services
```

| URL | What |
|---|---|
| `https://app.local` | React frontend |
| `https://app.local/api/docs` | API docs (non-production only) |
| `https://app.local/grafana` | Dashboards, logs, traces |
| `https://app.local/flower` | Celery tasks |
| `https://auth.app.local` | Authentik SSO |
| `wss://ws.app.local` | Soketi WebSockets |

## Deliberate removals (vs. the original draft)

- **Zookeeper** → Kafka 3.9 runs KRaft; one fewer JVM.
- **Mercure** → redundant with Soketi; one real-time channel (Pusher protocol works for React + mobile).
- **HAProxy** → Traefik already load-balances; second LB added nothing.
- **APScheduler, loguru, python-json-logger, aiohttp, confluent-kafka, psycopg2** → one tool per job (Beat, structlog, httpx, FastStream-on-aiokafka, asyncpg).
- **Raw aiokafka consumer loop** → FastStream (declarative subscribers, Pydantic validation, `TestKafkaBroker`, OTel middleware) — see [docs/FASTSTREAM_ANALYSIS.md](docs/FASTSTREAM_ANALYSIS.md).
- **python-jose / passlib** → unmaintained; PyJWT + bcrypt.
- **Mounted-code production backend** → immutable baked image; bind mounts are dev-only.

## Documentation

- [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) — every file, its purpose, how to use it.
- [docs/LOGGING.md](docs/LOGGING.md) — config-driven logging: per-environment + per-module YAML, redaction, on/off switches, recipes.
- [docs/AUDIT_AND_DATA_MODULES.md](docs/AUDIT_AND_DATA_MODULES.md) — activity/audit trail (mixins-vs-utility decision), files (S3/OCR), favorites; shared model mixins.
- [docs/zoho-module-implementation-guide.md](docs/zoho-module-implementation-guide.md) — step-by-step: build a Zoho module (API → Postgres mirror → Debezium → ClickHouse).
- [docs/zoho-docs-md/](docs/zoho-docs-md/) — vendored Zoho Books API reference.
- Zoho core layer (`app/modules/zoho/core/`): token manager (single-flight refresh, never-expired guarantee), global rate limiter, circuit breaker, async + sync clients with pagination.

## Roadmap notes

- New domains (orders, delivery/route-optimisation, rostering) = new folders under `app/modules/` + tasks under `app/tasks/` — same 5-layer pattern. Split into separate microservices only when a module needs independent scaling or deployment.
- Authentik is pinned at 2024.12.3 — plan an upgrade (config unchanged).
- Single Kafka broker / single Postgres: fine until real load; HA paths are documented inline in compose.
