# Circuit breaker v2

**Status:** ✅ live — used by `transport.py`; v1 `circuit_breaker.py` deleted (Phase 2) ·
**Code:** `app/modules/zoho/core/breaker.py` · **Tests:** `tests/zoho_core/test_breaker.py` (17)

---

## 1. Purpose

Stop hammering an endpoint group that is failing, and recover from the outage
with **exactly one** trial call rather than a thundering herd.

The breaker is a *local* safety net and is deliberately **fail-open**: if
Redis is unavailable, calls are allowed. The governor — not the breaker — is
the gate that fails closed, because exceeding Zoho's per-minute limit blocks
the whole organization.

---

## 2. What v1 got wrong (and this fixes)

| # | v1 behaviour | Effect | v2 |
|---|---|---|---|
| 1 | 429 recorded via `record_failure` (`client.py:161`) | normal throttling opened the circuit and blocked all traffic for the group | only `TRANSIENT`/`AMBIGUOUS` (5xx, timeouts, connection errors) count; `BREAKER_FAILURE_CATEGORIES` is the single source of truth |
| 2 | `record_success` closed a HALF_OPEN circuit from *any* caller | an in-flight request that started before the trip could close a circuit that was never probed | the probe holds a token; `_owns_probe()` compares it before closing or reopening |
| 3 | probe TTL 15 s < HTTP read timeout 30 s | a second probe started while the first was still in flight | `probe_ttl_seconds = ZOHO_TIMEOUT_SECONDS + 15` |
| 4 | a probe ending in a 400/404 neither closed nor reopened | 15 s blind spot per trial | a business error during the trial **closes** the circuit — Zoho answered, so it is up |
| 5 | fixed 30 s recovery | a long outage produced a probe every 30 s forever | recovery doubles per consecutive trip (30 s → 60 s → … capped at `ZOHO_CB_RECOVERY_MAX_SECONDS`) |
| 6 | key = `md5(full url)` (PHP engine) | every record had its own circuit; `min_calls` never reached | key = `"{api}:{first path segment}"` via `endpoint_group()` |

---

## 3. How it works

```
allow(group)
  ├─ CLOSED     → Admission(group)                      → call
  ├─ OPEN       → raise ZohoCircuitOpenError(retry_after=ttl)
  └─ HALF_OPEN  → SET probe NX PX ttl
                    ├─ won  → Admission(group, probe_id=…)  → the single trial
                    └─ lost → raise ZohoCircuitOpenError

record_success(admission, duration)
  ├─ probe & owns token → close (reason=probe_succeeded)
  └─ otherwise          → window += (slow if duration ≥ slow_seconds else ok) → evaluate

record_failure(admission, category, duration)
  ├─ probe & owns token → counts ? reopen (recovery ×2) : close (Zoho is answering)
  └─ otherwise          → counts ? window += fail → evaluate : ignore
```

**Evaluation** (only once the window holds ≥ `min_calls`):
open when `failures/total ≥ failure_ratio` **or** `slow/total ≥ slow_ratio`.
The window is a Redis ZSET scored by timestamp and pruned on every write, so
the rates are strictly "the last N seconds", independent of traffic volume
(this part of v1 was sound and is kept).

### 3.1 States

| State | How it is represented | Meaning |
|---|---|---|
| `CLOSED` | no state key, no meta hash | normal |
| `OPEN` | `zoho:cb:{group}:state` = "open" with TTL = current recovery | every call fast-fails |
| `HALF_OPEN` | state key expired, meta hash still present | one probe may run |

The meta hash outliving the state key is what makes the lapse readable as
HALF_OPEN; it expires after `recovery + 4×window` so a group that never gets
traffic again cannot leak keys.

---

## 4. Configuration (`app/core/conf.py`)

| Setting | Default | Meaning |
|---|---|---|
| `ZOHO_CB_WINDOW_SECONDS` | 60 | sliding window |
| `ZOHO_CB_MIN_CALLS` | 10 | never judge on noise |
| `ZOHO_CB_FAILURE_RATE` | 0.5 | trip threshold |
| `ZOHO_CB_SLOW_RATE` / `ZOHO_CB_SLOW_SECONDS` | 0.5 / 8.0 | slow-call detection |
| `ZOHO_CB_RECOVERY_SECONDS` | 30 | first cool-down |
| `ZOHO_CB_RECOVERY_MAX_SECONDS` | 300 | **new** — doubling cap |
| probe TTL | `ZOHO_TIMEOUT_SECONDS + 15` | derived, not configured |

### 4.1 Redis keys (DB 0)

| Key | Type | TTL |
|---|---|---|
| `zoho:cb:{group}:window` | zset (`outcome:nonce` → ts) | 2 × window |
| `zoho:cb:{group}:state` | string `"open"` | current recovery |
| `zoho:cb:{group}:meta` | hash (`trips`, `recovery_s`, `opened_at`) | recovery + 4 × window |
| `zoho:cb:{group}:probe` | string (probe id) | probe TTL |

---

## 5. Failure modes

| Failure | Behaviour |
|---|---|
| Redis unreachable | **fail open** — `allow()` returns a normal admission, `state()` reports CLOSED, one WARNING per occurrence (`zoho.breaker.storage_error`) |
| Probe token expires mid-call (slow Zoho) | the late outcome is ignored (`_owns_probe` fails); another probe may start — bounded by the TTL headroom |
| Worker dies holding the probe | probe key expires; the next caller becomes the probe |
| Group never recovers | recovery doubles to the cap; alerts fire on `zoho_breaker_state == 2` |
| Eviction of breaker keys under `allkeys-lru` | worst case the breaker forgets an open circuit (fails open) — acceptable; Phase 3 removes eviction for this instance |

---

## 6. Metrics & logs (wiring in Phase 2/4)

`snapshot(group)` → `{state, state_code (0/1/2), trips, recovery_seconds, window_calls, retry_after}`
feeds `zoho_breaker_state{group}`.

Events: `zoho.breaker.opened` (ERROR, with ratio and trip count),
`zoho.breaker.closed` (INFO, with reason), `zoho.breaker.probe_started`
(INFO), `zoho.breaker.storage_error` (WARNING).

---

## 7. Usage (as the transport does it)

```python
admission = await zoho_breaker.allow(endpoint_group(api, path))   # may raise
try:
    response = await send(...)
except ZohoError as err:
    await zoho_breaker.record_failure(admission, category=err.category, duration=elapsed)
    raise
await zoho_breaker.record_success(admission, duration=elapsed)
```

---

## 8. Tests

`tests/zoho_core/test_breaker.py` (real Redis, skips without it):
group keying · closed circuit allows · infrastructure failures open ·
**429/quota/validation/404/403 never open** (parametrised) · slow calls open ·
`min_calls` prevents noise trips · only one probe in HALF_OPEN · **only the
probe can close** (the v1 defect) · probe failure reopens with a longer
recovery and increments trips · probe business error closes · recovery
doubling capped · operator reset · fail-open when Redis is down.

---

## 9. Open questions

| # | Question | Impact | Resolution |
|---|---|---|---|
| 1 | Should the slow-call threshold be per purpose (list pages are legitimately slower than detail GETs)? | false trips during big list scans | measure `zoho_api_request_duration_seconds` after Phase 6, then consider `slow_seconds` per lane |
| 2 | Should Inventory and Books share a group when the resource is the same (e.g. `books:items` vs `inventory:items`)? | a failing Inventory does not pause Books calls today | keep separate; revisit if outages correlate |
| 3 | Do we want a "force open" operator action (planned maintenance)? | manual isolation of a failing group | fold into the admin API in Phase 4 |
