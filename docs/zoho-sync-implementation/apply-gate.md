# Apply gate, mixin split and bounded slices

**Status:** ✅ live for every pull through the v1 engine (Phase 4) ·
**Code:** `app/modules/zoho/sync/apply.py` (decision table + hashing),
`app/modules/zoho/sync/engine.py` (applies decisions, slices, detail skip),
`app/modules/zoho/sync/mixins.py` (mixin split),
`app/tasks/zoho_sync.py::execute_leased_run` (per-page commit, resume) ·
**Migration:** `20260919_0900_f79d022c961a_zoho_apply_gate.py` ·
**Tests:** `tests/zoho_core/test_apply_gate.py`, `test_slices.py`,
`tests/zoho_sync/test_engine.py`

---

## 1. Why

Before the gate, every listed record was written every time it was seen:

| Problem (v1) | Consequence |
|---|---|
| no version check | a late webhook or a lagging list page could overwrite newer data with older data |
| every apply is an UPDATE | identical payloads still produced WAL, a Debezium event and a search/Soketi update — for every record, every run |
| detail and list payloads treated alike | a thin list row replaced the full detail document in `zoho_raw` |
| detail call for every listed record | 1 list page of 200 → 200 detail calls, even when nothing changed (N+1 on the 45k/day budget) |
| "revive" of soft-deleted rows | claimed by the docstring, but `deleted_at` was never cleared |
| inbound apply set `sync_status='synced'` | a queued or failed **push** disappeared from view |

---

## 2. The decision table (`apply.decide`, pure)

| # | Check | Outcome | Row written? |
|---|---|---|---|
| 1 | no local row | `inserted` | ✅ |
| 2 | row carries a **sync tombstone** and the payload is not newer than it | `stale_ignored` | ❌ |
| 3 | row carries a sync tombstone and the payload is newer (or undated) | `resurrected` (clears `deleted_at` + `remote_deleted_at`) | ✅ |
| 4 | payload older than stored `zoho_last_modified_time` | `stale_ignored` (monotonic fence) | ❌ |
| 5 | same version and same hash | `unchanged` | ❌ |
| 6 | same version, thinner payload than the one stored | `unchanged` | ❌ |
| 7 | undated module (e.g. organizations) and same hash | `unchanged` | ❌ |
| 8 | otherwise | `updated`; `zoho_raw` replaced only if the payload is at least as rich | ✅ |

After mapping, the engine adds one more check: if the gate said `updated` but no
mapped column, no custom field and no raw document would actually change, the
apply is downgraded to `unchanged` and nothing is written.

**Sync tombstone** = `remote_deleted_at` set (by the guarded
`soft_delete_missing`), or the v1 marker `sync_status='deleted'` + `deleted_at`.
A row soft-deleted **by a user** (`deleted_at` only) is refreshed but never
revived — the sync does not undo a person's delete.

### 2.1 Provenance

| Source (`sync_source`) | Rank | Example |
|---|---|---|
| `nested:<parent>` | 0 | a currency object embedded in a contact |
| `list:<mode>` | 1 | a row from `GET /contacts` |
| `detail_fetch`, `webhook` | 2 | `GET /contacts/{id}` |

`zoho_raw`, `zoho_raw_hash`, `zoho_raw_synced_at` and `custom_fields` are
written only when the incoming rank ≥ the stored rank. Mapped columns still
follow a newer thin payload — the mapper never nulls a column whose key is
missing, so a thin payload only updates what it carries.

### 2.2 The no-op hash

`sha256` over the canonical payload (sorted keys, no whitespace) **minus
volatile keys** (glob, any depth). The default list is
`*_formatted, page_context, instrumentation`. Zoho re-renders display strings
such as `total_formatted` without any business change, and those must not count
as updates. The list can be set per module (`hash_volatile_keys` knob) or
fleet-wide (`ZOHO_SYNC_HASH_VOLATILE_KEYS`). `zoho_raw` still stores the full
document.

### 2.3 Legacy `sync_status`

An inbound apply sets `sync_status='synced'` only when no push is in flight or
failed: `queued`, `syncing` and `error` are kept, so push state stays visible.

---

## 3. Detail-call skip (N+1 saver)

For `detail_required` modules the engine loads the stored version of every
listed record with **one query per page**. When the stored row:

* is the detail document (`sync_source` rank 2),
* has the same `zoho_last_modified_time` as the list row, and
* is not tombstoned,

then the detail call is skipped. The record counts as `unchanged` and
`details_saved`. On a steady-state incremental or full scan, the only calls
spent are list pages plus details for records that actually changed. (This
needs the list row to carry `last_modified_time`; organizations have none, so
they are unaffected.)

---

## 4. "When to stop" — bounded slices

Each run is a **slice**. After every page the engine checks the budget. If a
budget is hit while Zoho still has more pages, the run ends **`yielded`**.

| Knob (per module, runtime-overridable) | Env default | Meaning |
|---|---|---|
| `max_run_seconds` | `ZOHO_SYNC_MAX_RUN_SECONDS=240` | wall-clock budget; capped at 480, well under Celery's 540 s soft limit |
| `max_pages_per_run` | `ZOHO_SYNC_MAX_PAGES_PER_RUN=0` | 0 = no limit |
| `max_records_per_run` | `ZOHO_SYNC_MAX_RECORDS_PER_RUN=0` | 0 = no limit |

| Stop | Run status | `stop_reason` | Resume point |
|---|---|---|---|
| scan finished (`has_more_page=false`) | `succeeded` / `partial` | — | next scan starts at page 1 |
| budget hit | `yielded` | `budget:max_run_seconds` · `budget:max_pages` · `budget:max_records` | full / unsorted: `next_page`; sorted incremental: the advanced watermark |
| governor refusal / switch | `yielded` | e.g. `governor:conserve`, `switch:engine_paused` | last committed page |
| code 45 | `suspended` | `quota_exhausted` | last committed page, next quota day |
| any other error | `failed` | — | last committed page (Celery retry policy decides) |
| lease lost | `abandoned` | — | the new lease holder continues |

### 4.1 Per-page transaction

`execute_leased_run` passes a `page_hook` to the engine. After each page it:

1. writes the lane cursor (`next_page`, `scan_started_at`, `state.mode`), fenced by `owner_run_id`;
2. **commits**, so the page's rows, their sync events and the cursor land atomically;
3. heartbeats the lease. If the lease is lost, the run stops with `abandoned`.

So a crash, a budget stop or a governor refusal loses at most one page. Before
this, a run was one transaction: a sync longer than Celery's soft time limit
was killed and **rolled back entirely**, and its lease (720 s) was never
extended.

For sorted incremental lanes the watermark (`zoho_sync_stats.last_incremental_cursor`)
advances with each page, so a yielded slice resumes from the watermark and not
from a page number.

### 4.2 Resume rules

A lane resumes at `cursor.next_page` only when:

* the cursor's `state.mode` equals the new run's mode — a `full` scan is never resumed by an `index` run;
* the scan started less than **36 h** ago (`_SCAN_MAX_AGE_HOURS`). An older scan starts over rather than joining snapshots from two different days (delta R16).

`soft_delete_missing` runs only for a scan that **started at page 1** in the
same slice. A multi-slice scan has no complete "seen" set, so it never
tombstones anything.

The planner resumes yielded lanes (**continuations**,
[`control-plane.md`](control-plane.md) §4.3).

---

## 4b. Batched page apply (Phase 5)

A page is applied in two phases:

| Phase | What happens | Isolation |
|---|---|---|
| 1 — materialise | per listed record: skip (detail current), queue (fan-out), or fetch the detail inline | per record: a failure counts an error, the page goes on |
| 2 — apply | **one** query loads every stored row of the page (`include_deleted`, live rows win); each payload goes through `decide()` against that cache; **one** flush writes the page | a DB error rolls back the page's SAVEPOINT and the page is re-applied **record by record**, each in its own savepoint, so only the bad record fails |

With SQLAlchemy 2's `insertmanyvalues`, the INSERTs for a page are one
statement with `RETURNING`, and the UPDATEs are an `executemany` grouped by
column set. Sync events and post-upsert hooks are **deferred** until after the
flush, when every row has its id. A duplicate `zoho_id` inside one page
matches the pending row from the cache, so it produces one row, not a unique
violation. In the record-by-record fallback, a unique violation (another lane
inserted the same record a moment earlier) is retried once as an update.

Nested child entities are still applied immediately (their local ids feed the
parent's FK columns), so pages of modules with nested rules flush a little
more often.

Measured in `tests/zoho_core/test_batch_apply.py`:
* 50 new taxes → 1 SELECT + 1 INSERT;
* 20 changed → 1 SELECT + ≤ 1 UPDATE executemany;
* v1 needed ≈ 2 statements *per record*.

**Why not literally `INSERT … ON CONFLICT DO UPDATE`** (target §9.2): the
gate's decisions (fence, provenance, tombstones, "missing key ≠ NULL") would
have to be re-expressed per payload-shape column set in SQL, and pre/post hooks
and nested rules need ORM rows. The ORM batch keeps a single decision
implementation (`apply.decide`) at about the same round-trip count. Revisit
only if profiling shows the ORM unit-of-work as the bottleneck.

---

## 5. Mixin split

`app/modules/zoho/sync/mixins.py` — columns only, composed per capability:

| Mixin | Columns | Use on |
|---|---|---|
| `ZohoIdentityMixin` | `zoho_id`, `public_id uuid` (unique, generated locally) | every mirrored or pushable table |
| `ZohoMirrorMixin` | `zoho_raw`, `zoho_raw_hash`, `zoho_raw_synced_at`, `zoho_last_modified_time`, `synced_at`, `sync_source`, `sync_version`, `remote_deleted_at`, `custom_fields` | every table fed by pull |
| `ZohoPushableMixin` | `sync_state`, `pending_command_id`, `last_pushed_at`, `last_push_error` | tables with push (Phase 8) |
| `ZohoApprovalMixin` | `approval_status`, `approval_requested_by/at`, `approved_by/at`, `rejection_reason` | modules with the approval gate |
| `ZohoWarehouseScopedMixin` | `location_zoho_id`, `warehouse_zoho_id`, `location_id`, `warehouse_id` | Inventory documents |
| `ZohoChildMixin` | `zoho_sub_id`, `position`, `zoho_raw`, `local_only` | line items / sub-records |
| `ZohoEntityMixin` | Identity + Mirror + legacy `sync_status` family, flags, `code`, `metadata` | **compatibility alias** — `zoho_organizations` only |

Each model declares its own partial unique index on the live `zoho_id`
(`WHERE deleted_at IS NULL AND zoho_id IS NOT NULL`). No mixin has listeners,
relationships or Zoho calls.

**Migration `f79d022c961a`** adds the Identity + Mirror columns to
`zoho_organizations` (existing rows get a generated `public_id` and
`sync_version = 0`). The first sync after deploy writes each row's hash once;
after that, identical payloads cause no UPDATE. The migration also adds
`resurrected`, `unchanged`, `stale_ignored`, `details_saved`, `start_page` and
`next_page` to `zoho_sync_runs`.

---

## 6. New counters

| Counter | On `SyncRunReport`, `zoho_sync_runs`, operator API | Meaning |
|---|---|---|
| `created` / `updated` / `resurrected` | ✅ | rows written |
| `unchanged` | ✅ | gate proved nothing changed (no write) |
| `stale_ignored` | ✅ | payload older than the stored version |
| `details_saved` | ✅ | detail calls not made (§3) |
| `start_page` / `next_page` | ✅ | slice position |

`zoho_sync_stats` (v1) folds `unchanged` + `stale_ignored` into `skipped_records`.

---

## 7. Open items

| # | Item | Phase |
|---|---|---|
| 1 | ~~Batched page apply~~ — done as an ORM batch (§4b); literal `ON CONFLICT` only if profiling asks for it | ✅ 5 |
| 2 | Rule 5: keep local owned fields while a push is pending (outbox v2 conflict precheck) | 8 |
| 3 | Rule 7: children replace-set by sub-id (`ZohoChildMixin` tables) | 6–7 |
| 4 | Rule 8: link by `public_id` when a pushed create's `zoho_id` arrives by pull first | 8 |
| 5 | Cross-slice seen-set so multi-slice full scans can reconcile deletions safely | 6 |
