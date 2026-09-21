# Transport — the single Zoho client

**Status:** ✅ built and **live** (the v1 sync engine now calls Zoho through it) ·
**Code:** `app/modules/zoho/core/transport.py`; shim `core/client.py` ·
**Tests:** `tests/zoho_core/test_transport.py` (20)

---

## 1. Purpose

The only code in the platform that speaks HTTP to Zoho. Every call — from the
API process or a Celery worker, Books or Inventory, pull or push — walks the
same pipeline, so every guarantee of the gates holds for every call.

It replaced three v1 modules, now **deleted**:

| Deleted | Why |
|---|---|
| `core/sync_client.py` | a second, synchronous client for Celery with its own policy: no circuit breaker, `time.sleep` up to 90 s, refresh token read from env only |
| `core/rate_limiter.py` | fixed-window per-minute counter + per-**process** semaphore that was held while sleeping; superseded by the governor |
| `core/circuit_breaker.py` | superseded by `breaker.py` (see [`circuit-breaker.md`](circuit-breaker.md)) |

---

## 2. The pipeline

```
ZohoClient.request(op)
 └─ loop per attempt
     1. breaker.allow(group)              raises ZohoCircuitOpenError  (no quota spent)
     2. governor.slot(op.priority)        raises quota / deferred / rate refusals
     3. token_manager.get_token()         single-flight refresh
     4. lease.mark_sent(); httpx request  connect 5 s, read ZOHO_TIMEOUT_SECONDS
     5. parse body (≤ 10 MB)              oversized → ZohoContractError
     6. ok?  → breaker.record_success → return ZohoResponse
        not ok → policy.classify → policy.decide
             RETRY                 sleep(full-jitter or Retry-After) → next attempt
             RETRY_WITH_NEW_TOKEN  invalidate(token) → next attempt (once)
             RAISE                 typed ZohoError (category-driven)
        code 45 → governor.mark_quota_exhausted()   Zoho's answer beats our counter
```

Every attempt is a new governor lease: retries cost calls, exactly as Zoho
counts them.

---

## 3. API

### 3.1 `ZohoOp` — one intended call (immutable)

| Field | Default | Meaning |
|---|---|---|
| `method`, `path` | — | `"GET"`, `"/invoices/{id}"` |
| `api` | `Api.BOOKS` | `Api.BOOKS` or `Api.INVENTORY` (base URL from settings) |
| `params`, `json`, `headers` | empty | `organization_id` is always added |
| `priority` | `Priority.INCREMENTAL` | governor class — **set it explicitly in new code** |
| `module`, `purpose` | `None`, `"unspecified"` | for logs/metrics (`list`, `detail`, `create`, `action`, `lookup`, …) |
| `deadline_s` | 60 | total wall-clock budget including retries and waits |
| `retry_safe` | `None` → derived | `True` only for upserts (`X-Upsert`) and idempotent actions — the only way a POST becomes retryable |

### 3.2 `ZohoClient`

| Method | Use |
|---|---|
| `request(op)` | the pipeline above → `ZohoResponse` |
| `iter_pages(op, per_page=200, start_page=1, max_pages=None, root=None)` | async iterator of `ZohoPage(records, page, per_page, has_more_page, response)`; **raises on any error**; stops only on `has_more_page == false`; a missing `page_context` is a `ZohoContractError`; `max_pages` stops quietly (slice budget) |
| `get/post/put/delete(path, params=, json=, **op_fields)` | v1-compatible helpers; extra keyword args become `ZohoOp` fields (`priority=`, `module=`, `api=`, …) |
| `paginate(path, params=, per_page=, max_pages=)` | v1-compatible: yields `ZohoResponse` per page — kept for the v1 engine |
| `aclose()` | close the httpx pool |

```python
from app.modules.zoho.core import Api, Priority, ZohoOp, zoho_client

op = ZohoOp("GET", "/picklists", api=Api.INVENTORY, priority=Priority.INCREMENTAL,
            module="picklists", purpose="list", params={"date_start": "2026-09-18"})
async for page in zoho_client.iter_pages(op, root="picklists"):
    ...
```

---

## 4. Behaviour that matters

| Situation | Result |
|---|---|
| POST + 5xx or read timeout | `ZohoAmbiguousOutcome` after **one** attempt — never retried (duplicate-record protection) |
| POST + connect error / connect timeout / pool timeout | retried — the request provably never arrived |
| `retry_safe=True` POST + 5xx | retried like a GET |
| GET/PUT/DELETE + 5xx | up to 4 attempts, full-jitter backoff, then `ZohoTransientError` |
| 401 | token invalidated (**only if it is still that token**), one retry |
| 429 code 44 / 1070 | retried if `Retry-After` / backoff fits the deadline, else `ZohoRateLimitedError` |
| 429 code 45 | `ZohoQuotaExhaustedError` + governor marked exhausted for the day |
| 404 / code 1002, 400, 403 | `ZohoNotFoundError`, `ZohoValidationError`, `ZohoForbiddenError` — not retried, not counted by the breaker |
| list page fails mid-scan | the exception propagates out of `iter_pages` — a partial scan is loud, never "complete" |
| body > 10 MB | `ZohoContractError` before parsing |
| non-JSON body (maintenance page) | wrapped into `{code: -1}` → `ZohoValidationError`, never a crash |

The transport reports every failed outcome to the breaker with its category;
the breaker alone decides which categories count.

---

## 5. Configuration

| Setting | Default | Meaning |
|---|---|---|
| `ZOHO_API_BASE_URL` | `https://www.zohoapis.in/books/v3` | `Api.BOOKS` |
| `ZOHO_INVENTORY_API_URL` | `https://www.zohoapis.in/inventory/v1` | `Api.INVENTORY` (was unused in v1) |
| `ZOHO_TIMEOUT_SECONDS` | 30 | read timeout per attempt |
| `ZOHO_CONNECT_TIMEOUT_SECONDS` | **5** (new) | fail fast when Zoho is unreachable |
| `ZOHO_ORGANIZATION_ID` | — | added to every request |
| `MAX_RESPONSE_BYTES` | 10 MB (constant) | OOM guard |

Retry budget constants live in `policy.py` (see [`errors-and-policy.md`](errors-and-policy.md)).

---

## 6. Logs

One event per attempt, all with `http_path_template` (numeric id segments →
`{id}`), never the raw path:

| Event | Level | When |
|---|---|---|
| `zoho.transport.call_completed` | INFO | success |
| `zoho.transport.retrying` | WARNING | a retry is scheduled (`reason`, `retry_in`) |
| `zoho.transport.call_failed` | WARNING | the client gives up; the *caller* logs the terminal ERROR once |
| `zoho.transport.page_budget_reached` | INFO | `max_pages` stopped a scan |

Fields: `module, http_method, http_path_template, api, purpose, priority,
http_status, attempt, duration_ms, zoho_request_id` (+ `error_category`,
`zoho_code`, `message`, `response_bytes` when relevant).

`X-Request-Id` sent to Zoho is the request's `request_id` (bound by
`RequestContextMiddleware`) or a generated `zoho-<12 hex>` in workers.

⏳ Sampling of 2xx GET logs and Prometheus instruments arrive with the metrics
work (Phase 4).

---

## 7. Compatibility with the v1 engine

`app/modules/zoho/sync/engine.py` and `app/tasks/zoho_sync.py` are unchanged
apart from the token-store binding (see [`auth.md`](auth.md) §5). They call
`ZohoClient().get(...)` / `.paginate(...)` exactly as before, and now:

* every call is governed (daily ceiling, rate, concurrency) and breaker-protected;
* `paginate()` raises `ZohoContractError` if a list response has no
  `page_context` (v1 silently ended the scan);
* the default priority for v1 calls is `INCREMENTAL` (background, paced).

---

## 8. Tests

`tests/zoho_core/test_transport.py` — `httpx.MockTransport` + stub gates, no
network, no Redis:

envelope parsing, org scoping, headers, lease marked sent and settled ·
Inventory base URL · priority forwarded · **POST never retried after 5xx or
read timeout** · POST connect error retried · declared-safe POST retried ·
GET transient retry then success · give-up after 4 attempts · 401 invalidates
exactly the used token and retries once · code 45 marks the governor exhausted ·
`Retry-After` honoured · typed business errors with templated paths ·
`iter_pages` walks to `has_more_page=false` with no extra request · **raises
mid-scan instead of ending quietly** · missing `page_context` → contract error ·
`max_pages` budget · legacy `paginate()` · oversized body refused · non-JSON
body handled.

---

## 9. Open questions

| # | Question | Resolution |
|---|---|---|
| 1 | Engine switches (global pause, per-module pause) belong at the front of the pipeline | Phase 4 control plane — the hook point is before `breaker.allow` |
| 2 | Should 2xx GET logs be sampled at 10 %? | yes, once volume is observed (Phase 4 logging processors) |
| 3 | Does Zoho return `Retry-After` on 429? **[verify]** | Phase 0 V11 — handled either way |
