# Sync events — the record-level log

**Status:** ✅ live for pulls through the v1 engine ·
**Code:** `app/modules/zoho/control/events.py`, `models.py` (`ZohoSyncEvent`),
hooks in `app/modules/zoho/sync/engine.py` (`upsert_payload`, `_soft_delete_missing`) ·
**Tests:** `tests/zoho_core/test_sync_events.py`, `test_retention.py`, `test_operator_api.py`

---

## 1. Purpose

Answer, per record: **"what happened to invoice XYZ, when, why, and what
changed?"** — e.g. *organization 10229182 was UPDATED by run 8b21… at 11:02:
`name` "Zillium Inc" → "Zillium Renamed"*.

Loki keeps the forensic trail; this table is the queryable, retained,
operator-facing history.

---

## 2. What is recorded

| `event_type` | Emitted by | Recorded by default |
|---|---|---|
| `inserted` | apply gate — new mirror row | ✅ |
| `updated` | apply gate — at least one mapped column (or only the raw document: `changed_fields = ["zoho_raw"]`) changed | ✅ (with diff) |
| `resurrected` | apply gate — a sync tombstone revived by newer evidence | ✅ (with diff) |
| `stale_ignored` | apply gate — payload older than the stored version / tombstone (`message` = `older_than_stored` · `older_than_tombstone`) | ✅ |
| `unchanged` | apply gate — nothing changed (`message` = `same_hash` · `richer_payload_stored` · `no_stored_change`) | ❌ sampled at `ZOHO_SYNC_EVENTS_SAMPLE_UNCHANGED` (0 %) |
| `tombstoned` | guarded `soft_delete_missing` (also sets `remote_deleted_at`) | ✅ |
| `push_*`, `approval_*`, `conflict_*`, `record_error` | outbox v2 / approval gate / lanes | ⏳ reserved (retention classes already defined) |

Each row carries: `module, local_id, zoho_id, event_type, direction (pull|push|local),
source (e.g. list:full), run_id, changed_fields, diff, zoho_last_modified_time,
actor_user_id, request_id, trace_id` (+ error fields for failures).

### 2.1 The diff

* Only **mapped columns** (the module's field map), never `zoho_raw` or secrets.
* `{field: [old, new]}`, values serialised (dates ISO, decimals as strings) and
  truncated to 500 chars; at most 50 fields per event.
* **Personal data masked** — columns whose name contains `email, phone, mobile,
  gst, pan_no, tax_reg, vat_reg, address, street, zip, attention, bank, card,
  upi, vpa` keep only their last 4 characters.
* Numeric noise ignored: `Decimal("12.50")` vs `12.5` is not a change.

### 2.2 Transactional guarantee

Events are added to the **same session** as the mirror write, so an event
exists if and only if the change committed. A rolled-back run leaves no events.

---

## 3. Storage

`zoho_sync_events` — natively partitioned by day on `occurred_at` (UTC), with a
`DEFAULT` partition. Primary key `(id, occurred_at)`. Indexes:
`(module, local_id, occurred_at)`, `(module, zoho_id, occurred_at)`, `(run_id)`.

Retention: policy-driven per module × event class (default 30 d success,
180 d failure, 365 d conflict, 7 y approval, 90 d otherwise) — see
[`control-plane.md`](control-plane.md) §5.

---

## 4. Reading it

Operator API: `GET /api/zoho/admin/records/{module}/{ref}/events?by=local|zoho&event_type=&limit=`
(newest first). By run: filter `zoho_sync_events.run_id` (the run detail
endpoint links runs; SQL example below).

```sql
-- everything run 8b21… changed
SELECT occurred_at, module, zoho_id, event_type, changed_fields
FROM zoho_sync_events WHERE run_id = '8b2125ec-3f56-485d-b247-1a7ad569bfa4'
ORDER BY occurred_at;
```

---

## 5. Configuration

| Setting | Default |
|---|---|
| `ZOHO_SYNC_EVENTS_ENABLED` | true |
| `ZOHO_SYNC_EVENTS_SAMPLE_UNCHANGED` | 0.0 |
| `ZOHO_SYNC_EVENTS_PARTITION_DAYS_AHEAD` | 7 |

---

## 6. Open items

| # | Item |
|---|---|
| 1 | Add `zoho_sync_events` to Debezium's `table.include.list` → ClickHouse long-term history (Phase 3 infra change) |
| 2 | Push, approval, conflict and record-error events (Phases 6–8) |
| 3 | App-facing slim history for FSA/DLP record screens |
