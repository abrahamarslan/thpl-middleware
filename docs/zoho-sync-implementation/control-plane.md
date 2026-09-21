# Control plane — switches, run leases, planner, retention, metrics

**Status:** ✅ live (Phase 4, first half) ·
**Code:** `app/modules/zoho/control/` (`switches.py`, `runs.py`, `planner.py`,
`retention.py`, `metrics.py`, `events.py`, `models.py`),
`app/tasks/zoho_sync.py`, `app/tasks/celery_app.py` ·
**Migrations:** `d4e5f6a7b8c9` (control tables), `e6f7a8b9c0d1` (settings tables) ·
**Tests:** `tests/zoho_core/test_switches.py`, `test_runs.py`, `test_planner.py`,
`test_planner_tick.py`, `test_retention.py`, `test_sync_events.py`, `test_operator_api.py`

Companion docs: [`sync-events.md`](sync-events.md) (record-level log),
[`operator-api.md`](operator-api.md) (endpoints).

---

## 1. Purpose

Decide **what runs, when, whether it may, and record what happened** — with
Postgres as the source of truth for anything that must survive a crash, and
Redis only for what can be lost.

It replaces three v1 mechanisms that caused overlapping and wasted runs:

| v1 | Problem | Replaced by |
|---|---|---|
| Beat `zoho-sync-dispatcher` every 5 min | no "already running" guard → the same module could run twice in parallel | planner (every minute) + DB-enforced run lease |
| Beat `zoho-full-sync-weekly` Sunday 03:00 | forced every module into a full scan at the same instant | per-module `weekly_full` planner lane, capped by the run limit and paused by the governor |
| `zoho_sync_stats.last_sync_time` as "last run" | overwritten by every run, no history | `zoho_sync_runs` (one row per run, with counters and errors) |

---

## 2. Engine switches (`switches.py`)

Checked by the transport **before any other gate** — a paused engine spends no
quota, takes no rate token and never touches the circuit breaker.

| Switch | Stored in | Set by | Blocks |
|---|---|---|---|
| `engine_paused` | settings key `zoho.control.engine_paused` + Redis mirror | operator | background pull **and** push; interactive calls still pass |
| `pull_enabled` = false | `zoho.control.pull_enabled` | operator | background reads |
| `push_enabled` = false | `zoho.control.push_enabled` | operator | **all** writes (interactive too — a push is a push) |
| `webhooks_enabled` | `zoho.control.webhooks_enabled` | operator | webhook processing (inbox, Phase 7) — default **off** |
| `paused_modules` | `zoho.control.paused_modules` (list) | operator | background traffic for those modules |
| `auth_paused` | Redis `zoho:control:auth_paused` | token manager on `invalid_code`/`invalid_grant` | **everything**, until a successful reconnect clears it |

* Durable switches go through `system_settings_service.set_setting` — every change
  is in `setting_audit_logs` with actor and IP — and are mirrored to the Redis hash
  `zoho:control:switches`. Each process caches the snapshot for
  `ZOHO_SWITCH_CACHE_SECONDS` (5 s).
* Lost mirror (eviction/restart) → rebuilt from Postgres on the next read.
* Refusal → `ZohoEngineDisabled` (a `ZohoBudgetDeferred`): runs end `yielded`,
  users get 503 `zoho_engine_disabled`.

---

## 3. Run leases & cursors (`runs.py`)

| Guarantee | Mechanism |
|---|---|
| At most one running run per module × lane | partial unique index `uq_zoho_sync_runs_one_running (module, lane) WHERE status='running'`; the loser of the INSERT race gets `None` and exits (`zoho.run.skipped reason=lane_busy`) |
| A dead worker never blocks a lane | lease expiry (`ZOHO_RUN_LEASE_SECONDS`, 720 s > Celery `task_time_limit` 600 s); the next acquirer marks it `abandoned`; the planner reaps expired leases every tick |
| A zombie cannot corrupt state | heartbeat/finish/cursor writes filter on `lease_owner` / `owner_run_id`; a fenced write updates 0 rows (`zoho.run.fenced`, `CursorFenced`) |
| Leases are visible immediately | acquired and finished in their **own** transactions, never inside the sync transaction |

Run statuses: `running · succeeded · partial · yielded · suspended · failed · abandoned · cancelled`.

| Outcome inside the run | Status | Celery retry? | What happens next |
|---|---|---|---|
| engine finished, no record errors | `succeeded` | — | next run after the interval |
| engine finished with record errors | `partial` | — | same |
| a slice budget was hit (`max_run_seconds` / `max_pages_per_run` / `max_records_per_run`) | `yielded` (`stop_reason` = `budget:…`, `next_page` set) | no | **continuation** on the next tick (§4.3) |
| governor pacing/state or a switch refused | `yielded` (`stop_reason` = reason) | no | continuation after `ZOHO_CONTINUATION_BACKOFF_SECONDS` (300 s), if the governor allows |
| daily ceiling / code 45 | `suspended` | no | due again immediately, but the planner skips it until the governor reopens (next quota day) |
| lease lost mid-run (heartbeat fenced) | stops at the next page, `abandoned` (set by whoever took over) | no | the new holder continues |
| any other exception | `failed` (+ category/fingerprint, partial counters) | per `_RETRY_KW` (transient only) | planner schedules the next attempt; committed pages are kept |

**Cursors** (`zoho_sync_cursors`, PK module × lane) now carry the slice
position of every leased run: `next_page`, `scan_started_at`, `state.mode`. They
are written after each page in the page's own transaction and fenced by
`owner_run_id`. Each page also **heartbeats** the lease, so a long scan no
longer outlives its 720 s lease. Resume rules are in
[`apply-gate.md`](apply-gate.md) §4. The incremental watermark of the v1
engine stays in `zoho_sync_stats` and advances page by page for sorted lanes.

---

## 4. Planner (`planner.py`, task `planner_tick`, Beat every 60 s)

Each tick:

1. **reap** expired leases → `abandoned`;
2. **reseed the governor** from `zoho_quota_days` if Redis lost today's counters
   (§4.4), then **snapshot** it and upsert `zoho_quota_days` (counts only ever go
   up, so a Redis reset can't lower the durable figure);
3. read the **switches**, the **runtime module config**
   ([`config-resolver.md`](config-resolver.md)) and **write pressure** (§4.5);
4. **plan** (pure function), including **continuations** of yielded slices
   (§4.3), and enqueue `sync_module_run(module, lane, mode, "planner")`;
5. **publish** `zoho:health` (governor, switches, token, planner summary) for
   `/metrics` and the operator API.

### 4.1 Lanes for the v1 engine modules

| Lane | Due when | Mode | Governor priority | Paused at |
|---|---|---|---|---|
| `scheduled` | `now − last start ≥ sync_interval_minutes` (effective config) | module's configured strategy | `INCREMENTAL` | `ESSENTIAL` and above |
| `weekly_full` | last full started before the most recent weekly slot (`ZOHO_WEEKLY_FULL_WEEKDAY`/`_HOUR`, org timezone) | `full` | `RECONCILE` | `CONSERVE` and above |
| `manual` | operator/API request | requested | `REFRESH` | `RESERVED_ONLY` and above |

* Modules already on the `full` strategy, or with `weekly_full_enabled=false`, get no `weekly_full` lane.
* **No catch-up storms:** due is computed from the last start in Postgres, so a
  6-hour outage produces one run per lane, and a missed weekly slot produces
  one catch-up, not one per missed week.
* Runs ending `abandoned` or `suspended` don't count as "last start" — they are
  retried.
* Candidates are ordered freshness-first (`INCREMENTAL` before `RECONCILE`), then
  most overdue, and capped by `ZOHO_PLANNER_MAX_CONCURRENT_RUNS` (2), counting
  runs already in progress.
* Every skip has a reason in the tick summary: `module_disabled`,
  `switch:<name>`, `governor:<state>`, `lane_running`, `write_pressure:<why>`,
  `concurrency_cap`.

### 4.3 Continuations

A lane whose **latest** run ended `yielded` (and has not been superseded by a
later run) is resumed with the **same mode**:

| `stop_reason` | Due at |
|---|---|
| `budget:*` | at once (`finished_at`) — the slice model working as intended |
| anything else (governor, switch) | `finished_at + ZOHO_CONTINUATION_BACKOFF_SECONDS` (300 s), so a paused engine is not re-polled every minute |

Continuations apply to every lane, including `manual`, and still pass through
every gate (switches, governor state, write pressure, concurrency cap). This
fixes a v1 gap: a `weekly_full` run that the governor paused on Sunday used to
count as "this week's full" and was never resumed.

### 4.4 Governor reseed

`reseed_governor` reads today's `zoho_quota_days` row and raises the Redis day
counters (`used`, `used_bg`, `exhausted`) to at least those values. This runs
in one Lua script and only ever raises (`Governor.reseed`). If Redis is flushed
or restarted mid-day, the governor would otherwise hand the day's quota out a
second time, even though Zoho's own counter did not reset. The worst case is
the calls made between the last tick and the Redis loss (≤ 1 minute of
traffic). The reseed is logged as `zoho.governor.reseeded`.

### 4.5 Write pressure

Background lanes yield (`write_pressure:<why>`) when:

| Probe | Threshold | Why |
|---|---|---|
| max lag of an **active** logical replication slot (Debezium) | `ZOHO_WRITE_PRESSURE_MAX_SLOT_LAG_MB` (512) | a 50k-row reconcile piles WAL behind a slow consumer and delays search/Soketi |
| depth of the `integrations` Celery queue | `ZOHO_WRITE_PRESSURE_MAX_QUEUE_DEPTH` (5000) | queued detail fetches are already behind |

Inactive slots are ignored: pausing Zoho doesn't help a stopped connector and
must not block the business. A probe that fails counts as "no pressure". Set a
threshold to 0 to disable that probe.

### 4.2 Celery tasks

| Task | Queue | Purpose |
|---|---|---|
| `app.tasks.zoho_sync.planner_tick` | integrations | Beat every 60 s, `expires=55` (a late tick is dropped, never stacked) |
| `app.tasks.zoho_sync.sync_module_run` | integrations | one leased run; client default priority = lane priority, module attributed |
| `app.tasks.zoho_sync.sync_module` | integrations | operator/API trigger → `sync_module_run(lane="manual")` (kept for existing callers) |
| `app.tasks.zoho_sync.retention_maintenance` | integrations | Beat 21:15 UTC (02:45 IST) |
| `app.tasks.zoho_sync.sync_all_due` | integrations | **deprecated** alias of `planner_tick` so queued messages drain safely |

The run logic is `execute_leased_run(db, client, …)` — callable without Celery,
which is how the tests drive it.

---

## 5. Retention (`retention.py`)

Policies live in `zoho_retention_policies` (seeded by the migration, editable
through the operator API). The **most specific** matching policy wins:
module + class › module › class › `*`.

| Table | Default | Mechanism |
|---|---|---|
| `zoho_sync_events` `*` | 90 d | batched DELETE, 10,000 rows per batch, 60 s budget |
| `zoho_sync_events` `success` | 30 d | same |
| `zoho_sync_events` `failure` | 180 d | same |
| `zoho_sync_events` `conflict` | 365 d | same |
| `zoho_sync_events` `approval` | 2555 d (7 y; API refuses < 365) | same |
| `zoho_sync_runs` | 90 d | DELETE of finished runs |
| `zoho_quota_days` | 400 d | DELETE by day key |

Partitions of `zoho_sync_events` (native RANGE, one per UTC day):

* created for today + `ZOHO_SYNC_EVENTS_PARTITION_DAYS_AHEAD` (7) every night;
  a `DEFAULT` partition catches anything else so inserts never fail;
* dropped when older than the longest policy, **or** older than the shortest
  policy and empty after the purge (so a 7-year approval class does not pin every
  day for 7 years — E15);
* native partitioning, not `pg_partman`: the scratch test image doesn't ship
  pg_partman and the behaviour needed is small.

Not implemented yet: legal holds (`zoho_retention_holds`), ClickHouse archive
before purge (`archive` column is stored but not acted on).

---

## 6. `soft_delete_missing` guard (Phase 1 remainder)

The v1 engine could soft-delete every local row missing from one FULL list scan.
Now:

1. **off** unless `ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING=true` (logs
   `zoho.sync.soft_delete_missing_skipped`);
2. the missing set is computed in Python from live ids — no `NOT IN` with every
   seen id (asyncpg's 32,767-parameter limit);
3. **mass-delete guard**: refuses (CRITICAL `zoho.sync.mass_delete_guard`) when
   more than `max(ZOHO_SYNC_MASS_DELETE_MIN=50, ZOHO_SYNC_MASS_DELETE_PCT=2 % × live)`
   rows would go;
4. every tombstone writes a `tombstoned` sync event.

Evidence-based deletion (two scans + a verifying 404) arrives with the
reconcile lane (Phase 6).

---

## 7. Metrics (`metrics.py`)

A background task in the **API** process copies `zoho:health` into gauges every
15 s; scrapes never run SQL or call Zoho.

| Gauge | Labels |
|---|---|
| `zoho_quota_used`, `zoho_quota_remaining`, `zoho_quota_limit`, `zoho_quota_background_allowance` | `pool` |
| `zoho_quota_state` (0 open … 4 exhausted) | `pool` |
| `zoho_rate_tokens`, `zoho_inflight` | — |
| `zoho_switch` (1 = on) | `name` = engine_paused, pull_disabled, push_disabled, auth_paused, modules_paused (count) |
| `zoho_token_ttl_seconds`, `zoho_token_refreshes_in_window` | — |
| `zoho_planner_last_tick_timestamp`, `zoho_planner_running_runs`, `zoho_health_snapshot_age_seconds` | — |

Suggested alerts: `zoho_health_snapshot_age_seconds > 180` (planner/Beat down),
`zoho_quota_state >= 3`, `zoho_switch{name="auth_paused"} == 1`.
Per-call counters/histograms from workers (Prometheus multiprocess) are still
Phase 3.

---

## 8. Configuration

| Setting | Default | Meaning |
|---|---|---|
| `ZOHO_PLANNER_ENABLED` | true | off → ticks do nothing (nothing scheduled) |
| `ZOHO_PLANNER_MAX_CONCURRENT_RUNS` | 2 | running pull runs across all modules |
| `ZOHO_RUN_LEASE_SECONDS` | 720 | lease; must exceed Celery `task_time_limit`; heartbeated after every page |
| `ZOHO_CONTINUATION_BACKOFF_SECONDS` | 300 | delay before resuming a slice the governor/a switch stopped (§4.3) |
| `ZOHO_WRITE_PRESSURE_MAX_SLOT_LAG_MB` / `_MAX_QUEUE_DEPTH` | 512 / 5000 | §4.5 (0 = probe off) |
| `ZOHO_CONFIG_CACHE_SECONDS` | 10 | runtime-config re-check interval ([`config-resolver.md`](config-resolver.md)) |
| `ZOHO_SYNC_MAX_RUN_SECONDS` / `_MAX_PAGES_PER_RUN` / `_MAX_RECORDS_PER_RUN` | 240 / 0 / 0 | slice budgets ([`apply-gate.md`](apply-gate.md) §4) |
| `ZOHO_SYNC_HASH_VOLATILE_KEYS` | `*_formatted,page_context,instrumentation` | keys the no-op hash ignores |
| `ZOHO_WEEKLY_FULL_WEEKDAY` / `_HOUR` | 6 (Sun) / 3 | weekly full slot, org timezone (`ZOHO_QUOTA_DAY_TIMEZONE`) |
| `ZOHO_SWITCH_CACHE_SECONDS` | 5 | per-process switch cache |
| `ZOHO_SYNC_EVENTS_ENABLED` | true | record-level events |
| `ZOHO_SYNC_EVENTS_SAMPLE_UNCHANGED` | 0.0 | share of no-op applies recorded |
| `ZOHO_SYNC_EVENTS_PARTITION_DAYS_AHEAD` | 7 | partitions created ahead |
| `ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING` | false | §6 |
| `ZOHO_SYNC_MASS_DELETE_MIN` / `_PCT` | 50 / 0.02 | §6 guard |
| `ZOHO_OPERATOR_EMAILS` | "" | operator allow-list ([`operator-api.md`](operator-api.md)) |

---

## 9. Deploying (WSL Docker stack)

1. Rebuild the backend image; recreate `backend`, `celery-worker`, `celery-beat`.
2. `alembic upgrade head` → creates the control tables **and the previously
   missing settings tables** (E12).
3. Recreate **Beat** so it drops the old `zoho-sync-dispatcher` /
   `zoho-full-sync-weekly` entries (its schedule file is in `/tmp`, so a new
   container starts clean). Messages already queued for `sync_all_due` run the
   planner instead — harmless.
4. Set `ZOHO_OPERATOR_EMAILS` for whoever operates the integration.
5. Optional: run `retention_maintenance` once
   (`celery -A app.tasks.celery_app call app.tasks.zoho_sync.retention_maintenance`)
   to create the first week of event partitions immediately.

---

## 10. Open items

| # | Item | Phase |
|---|---|---|
| 1 | ~~Per-process event loop for workers (ADR‑3)~~ — done for every async task ([`worker-event-loop.md`](worker-event-loop.md)) | ✅ 5 |
| 2 | ~~Governor counter reseed from `zoho_quota_days`~~ | ✅ §4.4 |
| 3 | Breaker states on `/metrics` (available in the operator API today) | 5 |
| 4 | Lanes C/W/L/F using `zoho_sync_cursors` (slices + heartbeat are already in place) | 6 |
| 5 | Legal holds and ClickHouse archive for retention | 8 |
| 6 | Weighted fair queuing between modules of the same priority (delta R7) | 6 |
