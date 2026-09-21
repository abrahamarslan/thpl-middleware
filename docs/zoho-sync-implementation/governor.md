# The governor — daily quota, per-minute rate, org-wide concurrency

**Status:** ✅ live — every Zoho call acquires a lease via `transport.py` (Phase 2) ·
**Code:** `app/modules/zoho/core/governor.py`, `core/pacing.py`,
`core/lua/governor_acquire.lua`, `core/lua/governor_release.lua` ·
**Tests:** `tests/zoho_core/test_governor.py` (15), `tests/zoho_core/test_pacing.py` (10)

---

## 1. Purpose

One gate that answers **"may this call go out right now?"** for every Zoho
request — pull, push, webhook refresh, reports, operator actions.

Why one component instead of the three the first design had (rate limiter,
daily quota, concurrency semaphore):

* they are one decision, and splitting them leaked reservations between steps;
* three Redis round-trips per call became one atomic script;
* only a single owner of the counters can implement a **hard stop and resume**.

What it protects against, with the numbers from Zoho's own docs:

| Limit | Value | Zoho's response | Consequence if we breach it |
|---|---|---|---|
| Daily calls | **45,000** (our contract; published plans cap at 1,000–10,000) | HTTP 429 code **45** | the integration stops until the next day — the binding constraint |
| Per-minute | 100 per organization | HTTP 429 code **44** | Zoho **blocks the organization**, including humans in the Zoho web UI |
| Concurrent | ~10 (soft, paid plans) | HTTP 429 code **1070** | throttled |

---

## 2. Quota day & pacing (`pacing.py`)

Pure, testable arithmetic, deliberately separate from Redis.

### 2.1 `quota_day(now, timezone, day_start) -> QuotaDay`

Which Zoho "day" we are in: key (`20260918`), start, end, TTL for counters,
`resets_at_iso()`. Zoho's real reset schedule is **[verify]** (Phase 0 V15) —
until it is known the boundary is configurable (`Asia/Kolkata`, `00:00`) and
resume waits `ZOHO_QUOTA_SAFETY_LAG_MINUTES` past it.

An unknown timezone falls back to UTC with an ERROR log rather than refusing
to start (slim images sometimes ship without tzdata).

### 2.2 `allowance(now, day, ceiling, curve, …) -> int`

How many **background** calls may have been spent by now. A hard ceiling alone
lets a morning backfill starve the evening.

| Curve | Shape | When |
|---|---|---|
| `none` | everything unlocked immediately | tests, tiny modules |
| `linear` | fraction of the day elapsed | 24 h operations |
| `business` (default) | 70 % of the allowance spread over 07:00–21:00, 30 % over the night | FSA/DLP hours, heavy reconcile at night |

`carry_pct` (default 5 %) lets short bursts through; the ceiling is never
exceeded. Only `INCREMENTAL` and `RECONCILE` are paced — pushes, refreshes and
interactive traffic obey the state machine only.

---

## 3. How admission works

```
caller ──► Governor.acquire(priority) ──► Lua (atomic)
                                           1. state vs priority
                                           2. daily ceiling for that priority
                                           3. pacing curve (background only)
                                           4. per-minute token bucket
                                           5. org-wide concurrency leases
                                           6. reserve: reserved+=1, token-=1, lease added
      ◄── Lease ────────────────────────────┘
caller sends the request, lease.mark_sent()
caller ──► Governor.release(lease) ──► Lua: lease removed; reserved-=1; used+=1 (only if sent)
```

Cheap refusals come first, so a paused or over-budget engine burns neither
quota nor rate tokens. Concurrency is taken **last**, so a lease is never held
while waiting for rate tokens (the v1 rate limiter held its semaphore while
sleeping up to 90 s).

### 3.1 Priorities

| Priority | Rank | Who | Max wait for a slot | Rate reserve it must leave | Paced |
|---|---|---|---|---|---|
| `INTERACTIVE` | 0 | user-facing requests, operator actions, `critical` pushes | 2 s | 0 % | no |
| `PUSH` | 1 | outbox dispatcher | 10 s | 10 % | no |
| `REFRESH` | 2 | webhook / write-back / record-error refreshes | 5 s | 20 % | no |
| `INCREMENTAL` | 3 | scheduled change feeds, window scans | 5 s | 35 % | yes |
| `RECONCILE` | 4 | full scans, backfills, reports | 0 s | 50 % | yes |

### 3.2 States

Derived from `used + reserved` against the thresholds:

| State | Threshold (default @45,000) | Still allowed |
|---|---|---|
| `OPEN` | < 36,000 | everything |
| `CONSERVE` | ≥ 36,000 (80 %) | all but `RECONCILE` |
| `ESSENTIAL` | ≥ 41,850 (93 %) | `INTERACTIVE`, `PUSH`, `REFRESH` |
| `RESERVED_ONLY` | ≥ 44,000 (97.8 %) | `INTERACTIVE` only, from the 1,000-call reserve |
| `EXHAUSTED` | ≥ 45,000 **or Zoho code 45** | nothing — resumes next quota day |

For a literal "stop everything at 45,000": set `ZOHO_QUOTA_HARD_PCT = 1.0`
and `ZOHO_QUOTA_RESERVE_CALLS = 0`.

### 3.3 What callers see

| Refusal | Exception | What the caller does |
|---|---|---|
| state pauses this priority | `ZohoBudgetDeferred(reason="state:conserve")` | lane yields, planner reschedules; command stays `pending` |
| daily ceiling / code 45 | `ZohoQuotaExhaustedError(resets_at=…)` | work suspends until the next quota day |
| pacing curve | `ZohoBudgetDeferred(reason="pacing")` | lane yields; retried later the same day |
| rate / concurrency after waiting | `ZohoRateLimitedError(data={"reason": …})` | short backoff, then retry (R1/R4) |

### 3.4 Accounting

* **Reserve on acquire, commit on release** — concurrent workers can never
  overshoot the ceiling, and a call that was refused before being sent
  (breaker, serialisation error) is refunded.
* Zoho counts *attempts*, so a 429 or 500 response still commits a call
  (`lease.mark_sent()` is called as soon as bytes go out).
* `release()` is idempotent by lease id: redis-py retries on timeout, and a
  replayed settle must not double-count.
* A minute-bucket token is **not** refunded when a request is not sent — the
  bucket protects Zoho's per-minute limit, and being slightly conservative
  there is intentional.

---

## 4. Configuration

All in `app/core/conf.py` (Layer 1). Runtime overrides (Layer 3, system
settings) arrive with the config resolver; the contract limit stays env-only.

| Setting | Default | Bounds | Meaning |
|---|---|---|---|
| `ZOHO_GOVERNOR_ENABLED` | `true` | — | off → every acquire returns a no-op lease (v1 behaviour) |
| `ZOHO_CONTRACT_DAILY_LIMIT` | 45000 | — | ceiling no override may exceed |
| `ZOHO_DAILY_HARD_LIMIT` | 45000 | ≤ contract | engine ceiling |
| `ZOHO_QUOTA_SOFT_PCT` / `_ESSENTIAL_PCT` / `_HARD_PCT` | 0.80 / 0.93 / 0.978 | strictly increasing | state thresholds |
| `ZOHO_QUOTA_RESERVE_CALLS` | 1000 | ≥ 0 | interactive reserve above the hard threshold |
| `ZOHO_RATE_LIMIT_PER_MINUTE` | **80** (was 90) | 1–90 | token-bucket refill |
| `ZOHO_RATE_BURST` | 10 | 1–60 | bucket capacity |
| `ZOHO_MAX_CONCURRENT_REQUESTS` | **6** (was 8) | 1–9 | org-wide, not per process |
| `ZOHO_QUOTA_DAY_TIMEZONE` / `_DAY_START` | `Asia/Kolkata` / `00:00` | — | day boundary **[verify]** |
| `ZOHO_QUOTA_SAFETY_LAG_MINUTES` | 30 | — | delay resume past the boundary |
| `ZOHO_PACING_CURVE` | `business` | none/linear/business | background pacing |
| `ZOHO_BUSINESS_HOURS` / `ZOHO_PACING_BUSINESS_SHARE` / `ZOHO_PACING_CARRY_PCT` | `07:00-21:00` / 0.7 / 0.05 | — | curve shape |
| `ZOHO_GOVERNOR_LEASE_TTL_SECONDS` | 40 | > read timeout | crashed holders expire |
| `ZOHO_GOVERNOR_EXPECTED_PROCESSES` | 8 | ≥ 1 | divisor for the degraded fallback |

`GovernorConfig` validates the bounds at construction: `daily_hard_limit`
above the contract limit, or thresholds out of order, raise at startup.

### 4.1 Redis keys (DB 0)

| Key | Type | TTL | Contents |
|---|---|---|---|
| `zoho:gov:{pool}:day:{yyyymmdd}` | hash | day + 2 h | `used`, `reserved`, `used_bg`, `p{rank}`, `state`, `exhausted` |
| `zoho:gov:{org}:minute` | hash | 120 s | `tokens`, `ts` |
| `zoho:gov:{org}:inflight` | zset | 300 s | lease id → expiry ms |

⚠ These keys must survive: Redis currently runs `--maxmemory-policy
allkeys-lru`, which may evict them (and the Celery broker). Phase 3 splits the
instance; until then the governor degrades as below when keys vanish.

---

## 5. Failure modes

| Failure | Behaviour |
|---|---|
| Redis unreachable | **degraded mode**: per-process bucket at `rate/expected_processes`, concurrency `limit/expected_processes`, and **all background work refused**. Logged once per minute (`zoho.governor.degraded`). Never unlimited. |
| Redis evicts the day hash | counters would restart at 0 for that day. **Mitigated (Phase 4):** every planner tick raises the Redis counters back to the durable `zoho_quota_days` figures (`Governor.reseed`, raise-only Lua; [`control-plane.md`](control-plane.md) §4.4). Residual risk ≤ 1 minute of traffic; the Phase 3 Redis split removes eviction entirely |
| Zoho returns code 45 while our counter is low | `mark_quota_exhausted()` sets `exhausted=1`; Zoho's answer always wins |
| A worker crashes holding a lease | the lease expires after `lease_ttl_seconds` and is purged by the next acquire |
| Clock skew between workers | rate refill uses `now_ms` passed by the caller; a skewed worker only affects its own refill, never the shared counters |
| `release()` lost (process killed) | reservation leaks until the day key expires; the in-flight lease expires on TTL. Phase 4 adds a reaper that reconciles `reserved` against the in-flight set |

---

## 6. Metrics & logs (planned wiring in Phase 2/4)

`snapshot()` returns everything `/metrics` and the admin API need:
state, used, reserved, remaining, thresholds, background allowance, rate
tokens, in-flight count, `resets_at`, `healthy`.

Planned instruments: `zoho_quota_used{pool,priority}`, `zoho_quota_state`,
`zoho_quota_remaining`, `zoho_rate_tokens`, `zoho_inflight`,
`zoho_quota_deferred_total{reason,module}`.

Log events: `zoho.governor.state_changed`, `zoho.governor.quota_exhausted`
(CRITICAL), `zoho.governor.degraded` (ERROR, once/min).

---

## 7. Usage

```python
from app.modules.zoho.core.governor import Priority, zoho_governor

async with zoho_governor.slot(Priority.PUSH, module="invoices") as lease:
    response = await http.request(...)   # bytes are about to leave
    lease.mark_sent()                    # → counts against the daily quota
```

`acquire()` blocks only for rate/concurrency, and only for the priority's
wait budget. Quota, state and pacing refusals raise immediately — background
work must yield, not queue.

---

## 8. Tests

`tests/zoho_core/test_governor.py` (real Redis, skips without it):

reserve/commit accounting · refund when not sent · idempotent release ·
context manager settles on exceptions · state escalation across all four
thresholds · daily ceiling never exceeded · code 45 overrides the counter ·
new quota day resumes automatically · minute bucket refuses when drained ·
priority reserves keep room for interactive traffic · concurrency capped
org-wide · expired leases do not block forever · pacing defers background but
not push · degraded mode allows foreground and stops background · disabled
governor is a no-op.

`tests/zoho_core/test_pacing.py`: day keys across timezones and non-midnight
boundaries, UTC fallback, clamped fractions, curve shapes, carry, malformed
business-hours strings.

---

## 9. Open questions

| # | Question | Impact | Resolution |
|---|---|---|---|
| 1 | Is the 45,000 shared across Books + Inventory or per product? **[verify]** | one pool vs two | Phase 0 V14 — the config already supports pools |
| 2 | Exact daily reset time/timezone **[verify]** | when suspended work resumes | Phase 0 V15 |
| 3 | Do 429s count against the daily quota? **[verify]** | accounting accuracy | Phase 0 V10 |
| 4 | Per-minute limit: per org across both APIs, or per API? | one bucket vs two | Phase 0 (both docs say "per organization") |
| 5 | Should `reserved` be reconciled against the in-flight set periodically? | leaked reservations after hard kills | Phase 4 reaper |
