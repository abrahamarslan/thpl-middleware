# Zoho Module Implementation Guide

How to build a Zoho Books module end-to-end: **Zoho API → local PostgreSQL mirror →
Debezium CDC → Kafka → ClickHouse analytics**, using the Contacts module
([docs/zoho-docs-md/contact.md](zoho-docs-md/contact.md)) as the worked example.

The same recipe applies to every entity in `docs/zoho-docs-md/` (items, invoices,
sales orders, payments, …).

---

## 0. One-time prerequisites — OAuth setup

Per [oauth-zoho.md](zoho-docs-md/oauth-zoho.md), the platform is a backend service →
use a **Self Client**:

1. [Zoho API Console](https://api-console.zoho.com/) → **Self Client** → Create.
   Copy Client ID + Client Secret.
2. **Generate Code** tab → enter scopes (comma-separated), e.g.
   `ZohoBooks.contacts.ALL,ZohoBooks.settings.ALL,ZohoBooks.invoices.ALL,ZohoBooks.salesorders.ALL`
   → pick max duration → Create → copy the grant code (valid ~3 min!).
3. Exchange it for tokens **immediately** (note `.in` DC — must match your account region):

   ```bash
   curl -X POST "https://accounts.zoho.in/oauth/v2/token" \
     -d "code=GRANT_CODE" \
     -d "client_id=CLIENT_ID" \
     -d "client_secret=CLIENT_SECRET" \
     -d "grant_type=authorization_code"
   ```

4. Save the `refresh_token` from the response — it never expires. Put it in
   `deployment/.env` (`ZOHO_REFRESH_TOKEN=...`). Access tokens are minted from it
   automatically; you never handle them manually.

> Zoho limits that shape this design: access tokens live 1 h; max **10 token
> refreshes / 10 min**; max **15 active access tokens** per refresh token;
> ~**100 API requests/min/org**; **429** on overrun.

---

## 1. The core layer — what you get for free

Everything below `app/modules/zoho/core/` is already built. Module code **never**
touches tokens, retries, or rate limits.

```
your service / task
      │
      ▼
zoho_client (async, API paths)  /  zoho_sync_client (Celery tasks)
      │ 1. circuit breaker check        (per endpoint group, Redis-shared)
      │ 2. rate-limit slot              (global 90/min budget, Redis-shared)
      │ 3. valid access token           (cached; single-flight refresh; 2-min early expiry)
      │ 4. HTTP call                    (org_id + X-Request-Id injected)
      │ 5. 401 → invalidate + retry once with fresh token   ← "never expired token"
      │    429 → honour Retry-After, backoff retry
      │    5xx/network → exponential backoff retry
      ▼
ZohoResponse(data, page_context, zoho_code, message, raw)
```

Failures surface as typed exceptions (`ZohoNotFoundError`, `ZohoValidationError`,
`ZohoRateLimitedError`, `ZohoCircuitOpenError`, `ZohoAuthError`) that the global
exception handlers already convert to clean API errors.

Usage patterns:

```python
# async (API request path)
from app.modules.zoho.core import zoho_client
resp = await zoho_client.get("/contacts", params={"contact_type": "customer"})
contacts = resp.data                                   # envelope stripped

async for page in zoho_client.paginate("/contacts"):   # all pages
    ...

# sync (Celery tasks)
from app.modules.zoho.core import zoho_sync_client
for page in zoho_sync_client.paginate("/contacts", params={"sort_column": "last_modified_time"}):
    ...
```

Tuning lives in `app/core/conf.py`: `ZOHO_RATE_LIMIT_PER_MINUTE`,
`ZOHO_MAX_CONCURRENT_REQUESTS`, `ZOHO_CB_FAILURE_THRESHOLD`,
`ZOHO_CB_RECOVERY_SECONDS`, `ZOHO_TOKEN_REFRESH_MARGIN`.

---

## 2. Building a module: Contacts, step by step

Target layout (FBA 5-layer):

```
app/modules/contacts/
├── __init__.py
├── model.py      # mirror table
├── schema.py     # transport DTOs
├── crud.py       # upserts / queries
├── service.py    # business logic
└── api.py        # HTTP endpoints
app/tasks/contacts.py   # full + incremental sync tasks
```

### Step 1 — Mirror table (`model.py`)

Design rule: **extract the columns you query; keep the full Zoho payload in JSONB.**
Zoho adds fields constantly — JSONB means a Zoho change never breaks ingestion,
and Debezium still streams the whole document downstream.

```python
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database.db import Base


class ZohoContact(Base):
    __tablename__ = "zoho_contacts"

    contact_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # Zoho's ID
    contact_name: Mapped[str] = mapped_column(String(256), index=True)
    company_name: Mapped[str | None] = mapped_column(String(256))
    contact_type: Mapped[str] = mapped_column(String(16), index=True)      # customer | vendor
    status: Mapped[str] = mapped_column(String(16), default="active")
    gst_no: Mapped[str | None] = mapped_column(String(20))
    outstanding_receivable_amount: Mapped[float | None] = mapped_column(Numeric(15, 2))
    payment_terms: Mapped[int | None] = mapped_column(BigInteger)

    raw: Mapped[dict] = mapped_column(JSONB)                                # full Zoho document
    zoho_last_modified_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)        # soft delete

    __table_args__ = (Index("ix_zoho_contacts_modified", "zoho_last_modified_time"),)
```

### Step 2 — Migration

```bash
# import the model in alembic/env.py first:
#   from app.modules.contacts import model as _contacts_model  # noqa: F401
./manage.sh makemig "add zoho_contacts mirror table"
./manage.sh migrate
```

### Step 3 — CRUD (`crud.py`): idempotent upsert

Syncs re-process records, so writes must be upserts:

```python
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.contacts.model import ZohoContact


async def upsert_contacts(db: AsyncSession, rows: list[dict]) -> int:
    if not rows:
        return 0
    stmt = insert(ZohoContact).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ZohoContact.contact_id],
        set_={c: stmt.excluded[c] for c in rows[0] if c != "contact_id"},
    )
    await db.execute(stmt)
    return len(rows)
```

(For the sync Celery path, the same statement runs through a sync `Session`; see
Step 5.)

### Step 4 — Service + API: read from Postgres, not Zoho

After mirroring, list endpoints serve **local data** (fast, offline-tolerant,
no rate-limit cost). Only drill-down/freshness-critical calls go straight to Zoho.

```python
# service.py (excerpt)
async def list_contacts(db, *, contact_type: str | None = None, page: int = 1, page_size: int = 50):
    query = select(ZohoContact).where(ZohoContact.is_deleted.is_(False))
    if contact_type:
        query = query.where(ZohoContact.contact_type == contact_type)
    return (await db.scalars(query.offset((page - 1) * page_size).limit(page_size))).all()
```

Register the router in `app/router.py`:

```python
from app.modules.contacts.api import router as contacts_router
api_router.include_router(contacts_router, prefix="/contacts", tags=["contacts"])
```

### Step 5 — Sync tasks (`app/tasks/contacts.py`)

Two tasks; both go on the `integrations` queue (already routed in `celery_app.py`):

**Full sync** — first run and weekly safety net:

```python
@shared_task(name="app.tasks.contacts.full_sync", autoretry_for=(ZohoApiError,),
             retry_backoff=60, retry_backoff_max=900, max_retries=5)
def full_sync() -> dict:
    total = 0
    for page in zoho_sync_client.paginate("/contacts", per_page=200):
        rows = [_map_contact(c) for c in page.data or []]
        total += _upsert_sync(rows)          # sync-session upsert
    _update_sync_state("contacts", status="success")
    return {"synced": total}
```

**Incremental sync** — the workhorse. Uses the `last_modified_time` filter with the
cursor stored in `zoho_sync_state` (the table already exists):

```python
@shared_task(name="app.tasks.contacts.incremental_sync", ...)
def incremental_sync() -> dict:
    cursor = _get_sync_cursor("contacts")    # last successful last_modified_time
    params = {"sort_column": "last_modified_time", "sort_order": "A"}
    if cursor:
        params["last_modified_time"] = cursor.strftime("%Y-%m-%dT%H:%M:%S%z")
    total = 0
    for page in zoho_sync_client.paginate("/contacts", params=params):
        rows = [_map_contact(c) for c in page.data or []]
        total += _upsert_sync(rows)
    _update_sync_state("contacts", status="success")   # stores max(last_modified_time)
    return {"synced": total}
```

`_map_contact` extracts the indexed columns and stores the whole document:

```python
def _map_contact(c: dict) -> dict:
    return {
        "contact_id": str(c["contact_id"]),
        "contact_name": c.get("contact_name", ""),
        "company_name": c.get("company_name"),
        "contact_type": c.get("contact_type", "customer"),
        "status": c.get("status", "active"),
        "gst_no": c.get("gst_no"),
        "outstanding_receivable_amount": c.get("outstanding_receivable_amount"),
        "payment_terms": c.get("payment_terms"),
        "raw": c,
        "zoho_last_modified_time": _parse_zoho_ts(c.get("last_modified_time")),
        "synced_at": datetime.now(UTC),
    }
```

### Step 6 — Schedule it (`celery_app.py` beat_schedule)

```python
"contacts-incremental-sync": {
    "task": "app.tasks.contacts.incremental_sync",
    "schedule": crontab(minute="*/10"),
},
"contacts-full-sync": {
    "task": "app.tasks.contacts.full_sync",
    "schedule": crontab(minute="0", hour="2", day_of_week="sunday"),
},
```

Add `"app.tasks.contacts"` to the Celery `include` list.

### Step 7 — Verify

```bash
./manage.sh dev
docker exec celery-worker celery -A app.tasks.celery_app call app.tasks.contacts.full_sync
# watch it in Flower:  https://app.local/flower
# logs:                {service="celery-worker"} | json | logger="app.tasks.contacts"
docker exec -it postgres psql -U app -d app_db -c "SELECT count(*) FROM zoho_contacts;"
```

### Optional — Zoho webhooks for near-real-time

Polling every 10 min is the reliable baseline. For sub-minute freshness add a
webhook endpoint (`POST /api/zoho/webhooks/contacts`) that verifies a shared
secret and enqueues `incremental_sync` — webhooks *trigger* a sync; the sync
remains the source of truth (webhooks can be dropped; polling cannot).

---

## 3. Debezium: Postgres → Kafka → ClickHouse

Once a mirror table exists, Debezium streams every INSERT/UPDATE/DELETE to Kafka
with no application code. The wiring is already in the stack:

- Postgres runs `wal_level=logical` (compose `EXTRA_CONF`).
- The `debezium` service (Kafka Connect) is up alongside Kafka.
- Connector template: `deployment/config/debezium/zoho-mirror-connector.json`
  (plugin `pgoutput`, topic prefix `zoho-mirror`, unwrap transform → flat events,
  soft-delete rewrite).

### 3.1 Register / update the connector

Add the new table to `table.include.list` in the template, then:

```bash
./manage.sh register-debezium     # idempotent PUT
./manage.sh debezium-status       # connector + task state
```

Verify events are flowing (Kafka-UI at `localhost:8088`, or):

```bash
docker exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic zoho-mirror.public.zoho_contacts --from-beginning --max-messages 5
```

### 3.2 ClickHouse ingestion

Use a Kafka-engine table + materialized view (run in `clickhouse-client`):

```sql
-- 1. Kafka source (reads the Debezium-unwrapped JSON)
CREATE TABLE analytics.zoho_contacts_queue
(
    contact_id String,
    contact_name String,
    contact_type LowCardinality(String),
    status LowCardinality(String),
    outstanding_receivable_amount Nullable(Float64),
    zoho_last_modified_time Nullable(DateTime64(3)),
    __op LowCardinality(String),          -- c/u/d from the unwrap transform
    __source_ts_ms UInt64
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9092',
         kafka_topic_list = 'zoho-mirror.public.zoho_contacts',
         kafka_group_name = 'clickhouse-zoho-contacts',
         kafka_format = 'JSONEachRow',
         kafka_num_consumers = 1;

-- 2. Storage (ReplacingMergeTree dedupes on later versions)
CREATE TABLE analytics.zoho_contacts
(
    contact_id String,
    contact_name String,
    contact_type LowCardinality(String),
    status LowCardinality(String),
    outstanding_receivable_amount Nullable(Float64),
    zoho_last_modified_time Nullable(DateTime64(3)),
    is_deleted UInt8,
    _version UInt64
)
ENGINE = ReplacingMergeTree(_version)
ORDER BY contact_id;

-- 3. The pump
CREATE MATERIALIZED VIEW analytics.zoho_contacts_mv TO analytics.zoho_contacts AS
SELECT contact_id, contact_name, contact_type, status,
       outstanding_receivable_amount, zoho_last_modified_time,
       if(__op = 'd', 1, 0) AS is_deleted,
       __source_ts_ms AS _version
FROM analytics.zoho_contacts_queue;
```

Query with `FINAL` (or aggregate around versions):
`SELECT count() FROM analytics.zoho_contacts FINAL WHERE is_deleted = 0;`

### 3.3 The full data flow

```
Zoho Books ──(Celery sync, every 10 min)──► PostgreSQL zoho_* mirror
PostgreSQL ──(Debezium CDC, ~real-time)──► Kafka zoho-mirror.public.*
Kafka ──(Kafka engine + MV)──► ClickHouse analytics.*  ──► Grafana / BI / sockets
```

Why this shape: the apps read consistent relational data from Postgres; analytics
gets a near-real-time columnar copy without ever touching the OLTP database; and
Zoho's rate limits are consumed exactly once, by the sync workers.

---

## 4. Operational runbook

| Question | Where |
|---|---|
| Is the sync running? | Flower → `https://app.local/flower`; or `GET /api/zoho/sync/contacts` |
| Why did a sync fail? | Loki: `{service="celery-worker"} \| json \| level="error"` |
| Are we burning rate limit? | Loki: `{service=~"backend\|celery-worker"} \| json \| logger="app.zoho.ratelimit"` |
| Did the circuit open? | Loki: `zoho_circuit_opened`; calls fail fast with `zoho_circuit_open` |
| Token problems? | Loki: `logger="app.zoho.token"` — `zoho_refresh_throttle_hit` means a caching bug, investigate immediately |
| Is CDC flowing? | `./manage.sh debezium-status`; Kafka-UI topic `zoho-mirror.public.*` lag |
| End-to-end trace of one request | Grafana → Tempo: API → SQL → Zoho HTTP spans share one trace |

Failure modes handled automatically: expired/revoked access token (refresh +
retry), Zoho 429 (Retry-After backoff), Zoho 5xx (backoff + circuit breaker),
network blips (retry), prolonged outage (task autoretry: 1 m → 15 m, 5 attempts,
then visible as failed in Flower + Prometheus `celery_task_failed_total`).
