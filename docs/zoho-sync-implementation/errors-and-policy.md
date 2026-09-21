# Error model & retry policy

**Status:** ✅ built (Phase 2) · **Code:** `app/modules/zoho/core/errors.py`,
`app/modules/zoho/core/policy.py`, shim `core/exceptions.py` ·
**Tests:** `tests/zoho_core/test_policy.py` (34 cases)

---

## 1. Purpose

Two small modules that decide, once and in one place, **what a Zoho failure
means** and **what happens next**. Everything else in the platform (transport,
lanes, outbox, webhooks) branches on the resulting `ErrorCategory`, never on
raw HTTP status codes.

This removes three defects the previous engines shipped with:

| Defect | Where it came from | Fixed by |
|---|---|---|
| POST retried after the request was already sent → duplicate invoices/payments | PHP engine fixed it, the first Python client reintroduced it (`client.py:169-178`) | `classify()` returns `AMBIGUOUS` for non-idempotent writes whose outcome is unknown; `decide()` never retries it |
| 429 counted as a circuit-breaker failure → normal throttling opened the circuit | `client.py:161` | `BREAKER_FAILURE_CATEGORIES` excludes `RATE_LIMITED`/`QUOTA_EXHAUSTED` |
| Every failure logged/retried differently per call site | engine + tasks + repositories | one category → one decision → one log shape |

---

## 2. Where it lives

```
app/modules/zoho/core/
├── errors.py       ErrorCategory, exception hierarchy, fingerprints, Zoho code map
├── policy.py       Outcome → classify() → decide() (pure, no I/O)
└── exceptions.py   backwards-compatibility shim (old import path)
```

---

## 3. How it works

### 3.1 Categories

`ErrorCategory` (in `errors.py`) is the vocabulary of the whole platform:

| Category | Meaning | Retryable | Counts for breaker | Typical source |
|---|---|---|---|---|
| `TRANSIENT` | may succeed later | ✅ | ✅ | 5xx on a retry-safe op, connect errors, Zoho code 1000 |
| `RATE_LIMITED` | throttled | ✅ (delayed) | ❌ | 429 code 44 / 1070, local rate refusal |
| `QUOTA_EXHAUSTED` | daily ceiling gone | ❌ (next quota day) | ❌ | 429 code 45, governor hard stop |
| `CIRCUIT_OPEN` | breaker refused locally | ✅ (delayed) | ❌ | breaker |
| `AUTH` | token problem | ✅ (once) | ❌ | 401 |
| `AUTH_REVOKED` | refresh token gone | ❌ | ❌ | `invalid_code`/`invalid_grant` |
| `AMBIGUOUS` | write sent, outcome unknown | ❌ (resolve by lookup) | ✅ | POST + 5xx/read timeout |
| `NOT_FOUND` | record gone | ❌ | ❌ | 404, Zoho code 1002 |
| `VALIDATION` | Zoho rejected the payload | ❌ | ❌ | 400 |
| `CONFLICT` | remote changed since our base | ❌ | ❌ | push pre-check |
| `FORBIDDEN` | scope/permission | ❌ | ❌ | 403 |
| `CONTRACT` | 2xx with an undocumented shape | ❌ | ❌ | missing root key / `page_context` |
| `BUG` | unclassified | ❌ | ❌ | anything else |

### 3.2 Exceptions

All subclass `ZohoError` → `UpstreamError`, so the global handlers already
render them in the `{code, msg, data, request_id}` envelope.

```
ZohoError (base, category=BUG)
├── ZohoUnclassifiedError        code "zoho_api_error"
├── ZohoTransientError           503
├── ZohoRateLimitedError         503
│   ├── ZohoQuotaExhaustedError  503 + resets_at
│   └── ZohoBudgetDeferred       internal: background work paused (not a failure)
├── ZohoCircuitOpenError         503
├── ZohoAuthError                502
│   ├── ZohoAuthThrottledError   (8 refreshes/10 min guard)
│   └── ZohoAuthRevokedError     engine pauses
├── ZohoAmbiguousOutcome         502 — resolved by identity lookup
├── ZohoNotFoundError            404
├── ZohoValidationError          400
├── ZohoConflictError            409
├── ZohoForbiddenError           403
└── ZohoContractError            502
```

**`ZohoApiError` is an alias of `ZohoError`.** The v1 hierarchy had it as the
base of everything and existing call sites (`engine.py` run loop, Celery
`autoretry_for`) depend on `except ZohoApiError` catching all Zoho failures.
Aliasing keeps that true; new code raises the typed classes.

### 3.3 Fingerprints

`err.fingerprint()` → stable 16-char key from class + status + Zoho code +
*normalised* message (ids → `<id>`, numbers → `<n>`, quoted values → `'?'`):

```python
ZohoValidationError("Invoice 982000000567114 does not exist").fingerprint()
== ZohoValidationError("Invoice 982000000567115 does not exist").fingerprint()
```

Used by: log grouping, `zoho_record_errors` uniqueness, dead-letter triage,
alert dedupe.

`err.log_fields()` returns the standard structured fields every terminal log
event must carry.

### 3.4 Classification (`policy.classify`)

Input is an `Outcome` — method, whether the op is retry-safe, HTTP status,
Zoho code, exception, and whether the request was actually sent.

The decisive rule:

```python
# 5xx / read timeout on a write we cannot replay safely
return ErrorCategory.TRANSIENT if outcome.retry_safe else ErrorCategory.AMBIGUOUS
```

`is_retry_safe(method, declared=None)`:

* `GET/HEAD/PUT/DELETE` → safe (we always send absolute values, never increments);
* `POST` → **unsafe by default**;
* `declared=True` lets an adapter mark a POST safe — an `X-Upsert` upsert or an
  idempotent status transition (`POST /invoices/{id}/status/sent`).

Pre-send transport errors (`ConnectError`, `ConnectTimeout`, `PoolTimeout`)
are `TRANSIENT` even for POST: the request provably never arrived.

### 3.5 Decisions (`policy.decide`)

Returns `Decision(action, delay, category, reason)` where action is
`RETRY`, `RETRY_WITH_NEW_TOKEN` or `RAISE`.

| Situation | Decision |
|---|---|
| 401, first time | `RETRY_WITH_NEW_TOKEN` (invalidate the cached token, retry once) |
| `TRANSIENT`/`RATE_LIMITED`, attempts left, wait fits the deadline | `RETRY` after full-jitter backoff (`U(0, min(8 s, 0.5·2ⁿ))`) or `Retry-After` |
| attempts exhausted | `RAISE` (`attempts_exhausted`) |
| wait would exceed the caller's deadline | `RAISE` (`deadline_exceeded`) — the durable layer retries instead |
| anything else (`AMBIGUOUS`, `VALIDATION`, `QUOTA_EXHAUSTED`, …) | `RAISE` |

Budget: `MAX_ATTEMPTS = 4` (1 + 3 retries), base 0.5 s, cap 8 s. Long waits
are never slept in a worker — they become `next_attempt_at` rows.

---

## 4. Configuration

None. Both modules are pure; thresholds are module constants
(`MAX_ATTEMPTS`, `BACKOFF_BASE_SECONDS`, `BACKOFF_CAP_SECONDS`) so the retry
budget is a code review, not an environment variable.

---

## 5. Failure modes

| Situation | Behaviour |
|---|---|
| Zoho returns an undocumented error code | 4xx → `VALIDATION`, 5xx → `TRANSIENT`; the transport increments `zoho_unknown_error_code_total{code}` so the map gets curated |
| 2xx with `code != 0` | mapped through `ZOHO_CODE_CATEGORY` (e.g. 1002 → `NOT_FOUND`), else `VALIDATION` |
| 2xx with `code == 0` reaching `classify()` | `BUG` — success must never be classified as an error |
| Exception type we do not know | `BUG`, raised, never retried |

---

## 6. Metrics & logs

Not emitted here (pure modules). The transport uses:
`error_category`, `error_class`, `error_fingerprint`, `http_status`,
`zoho_code`, `retry_after` from `log_fields()`, and
`zoho_api_errors_total{group,category,zoho_code}`.

---

## 7. Tests

`tests/zoho_core/test_policy.py`:

* 24-row classification table (statuses, Zoho codes, transport exceptions);
* POST is not retry-safe by default; `declared=True` flips it;
* `AMBIGUOUS` is never retried in the client;
* transient retries then gives up at `MAX_ATTEMPTS`;
* `Retry-After` honoured when it fits, `deadline_exceeded` when it does not;
* 429 (any code) never in `BREAKER_FAILURE_CATEGORIES`;
* 401 retries once with a new token, then raises;
* backoff bounded and jittered;
* fingerprints group ids/numbers, `log_fields()` shape.

---

## 8. Open questions

| # | Question | Impact | Resolution |
|---|---|---|---|
| 1 | Does Zoho count 429-rejected calls against the daily quota? **[verify]** | governor accounting (currently: yes, conservative) | Phase 0 V10 |
| 2 | Are there Zoho codes beyond 44/45/1000/1002/1070 we should map explicitly? | fewer `BUG`/`VALIDATION` fallbacks | curate `ZOHO_CODE_CATEGORY` from `zoho_unknown_error_code_total` in production |
| 3 | Which POST actions are genuinely idempotent (`/status/sent`, `/status/void`, `/active`)? **[verify]** | lets those be retried instead of resolved | Phase 0, per adapter |
