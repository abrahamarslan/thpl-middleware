# Field operations — shifts, visits, tasks and the location stream (implementation spec)

**Status:** ✅ built 2026-09-29 (as-built reference: [README.md](README.md)) · **Schema:** `fieldops` (+ `core.idempotency_keys`) ·
**Module:** `app/modules/fieldops/` · **Review & rationale:** [improvement-document.md](improvement-document.md)
(findings `F-nn` are cited throughout) · **Depends on:** [tenancy](../tenancy/README.md),
[location hub](../geo/README.md), [geocoding](../geo/geocoding.md), [RBAC](../rbac-module.md), comments,
media, documents, compliance, fleet

This is the build spec. It answers *what exactly gets built*: tables, state machines, the time model,
ingestion, verification, auto-close, metrics, API, jobs, permissions, migrations, the mobile-client
contract and tests. The *why* for anything that departs from the pasted design is in the review.

> **Built.** The as-built reference is [README.md](README.md); its §9 lists every place the build
> differs from this spec. The largest change: **breaks were generalised into pauses** — a shift can
> be `paused` (meal, prayer, vehicle breakdown, no network …) and every section below now says so.
> Also: every table carries a `uuid`; the raw device time is `client_timestamp` everywhere; pg_partman
> is not used (app-managed partitions); `user_location_pings` was dropped after the copy.

---

## 0. The model in one picture

```
                      fieldops.work_policies ── resolved per user (base role × org tree)
                                  │  frozen onto each shift as policy_snapshot
                                  ▼
 fieldops.devices ─┐      fieldops.shifts ───────────────┬── fieldops.shift_pauses
 device_sessions   │  (one active per user)              ├── fieldops.shift_metrics   (derived, 1:1)
 device_events     │            │ 1..n                   └── media: shift_selfie, odometer
                   │            ▼
                   │      fieldops.visits ── account (core.entity_types) + place (geo.places)
                   │  (one in_progress per user)
                   │            │ 1..n            ├── fieldops.visit_participants  (joint working)
                   │            ▼                 ├── comments (notes) · media (photos) · documents (signatures)
                   │      fieldops.visit_tasks ── reference → order / payment / return … (core.entity_types)
                   │
                   └──▶ fieldops.location_pings  ◀── ONE stream: continuous fixes + labelled checkpoints
                         (partitioned, recorded_at)      shift_id / visit_id: nullable, independent
                                  │
                                  ├──▶ public.user_live_locations   (last-known projection, recency-guarded)
                                  ├──▶ fieldops.location_checks     (geofence verification ledger)
                                  └──▶ fieldops.ping_batches        (upload envelope + raw-body pointer)

 fieldops.state_transitions   every lifecycle / review transition of shifts, pauses, visits, tasks
 fieldops.anomalies           everything a manager must look at → the review queue
 core.idempotency_keys        replay-safe mutations (platform-wide; DLP reuses it)

 reused, unchanged: geo.places · geo.place_links · geo.geofences (dwell_threshold_s) ·
 geo.geocode_api_calls · compliance.consent_records / data_retention_schedules · fleet.vehicles ·
 comments · media · documents · activity.recorder · rbac
```

Five rules everything below follows:

1. **One stream.** Every coordinate a device reports lives in `fieldops.location_pings`. Shifts and
   visits store *timestamps*, never coordinates. A checkpoint is a stream row with `kind='checkpoint'`
   and a label (F-04, F-16).
2. **Business time is `occurred_at`**, derived from the device's monotonic clock where possible.
   `received_at` is only when the server learned about it (F-12).
3. **The device names things.** Every entity and every fix carries a client-generated UUIDv7. A replay
   is a no-op by construction (F-28). Transitions additionally go through `core.idempotency_keys` (F-29).
4. **Uncertainty is a value, not an error.** `uncertain`, `no_fix`, `not_configured` and
   `not_applicable` are first-class results. Absence of a fence never blocks (§8).
5. **The system never silently invents a number.** Anything estimated is marked (`*_time_basis`,
   `duration_basis`), sets `review_status='pending'`, and opens an anomaly (§10–11).

---

## 1. Module layout

Package-by-feature, the FBA five layers, plus the pure-function files the tests lean on:

```
app/modules/fieldops/
  __init__.py
  enums.py            every closed vocabulary below (StrEnum) + values() for CHECKs
  model/
    __init__.py
    policy.py         WorkPolicy
    device.py         Device, DeviceSession, DeviceEvent
    shift.py          Shift, ShiftBreak, ShiftMetrics
    visit.py          Visit, VisitParticipant, VisitTask
    stream.py         LocationPing, PingBatch, LocationCheck
    ledger.py         StateTransition, Anomaly
  schema/             Pydantic In/Out per aggregate (Slim list DTOs + Fat detail DTOs)
  crud/               SQL only (load_only for list paths; bulk INSERT … ON CONFLICT for the stream)
  service/
    policy.py         resolve_policy(user) → EffectivePolicy
    shifts.py         start / pause / resume / end / supersede / correct / review / auto_close
    visits.py         start / end / cancel / correct / review
    tasks.py          submit / void; task-type registry dispatch
    ingest.py         the ping batch pipeline (§6)
    devices.py        register / session upsert / events
    anomalies.py      open (idempotent by dedupe_key) / resolve
    metrics.py        compute_shift_metrics (§10)
  clock.py            PURE: derive occurred_at from the three clocks (§5)
  verification.py     PURE classify() + the one PostGIS evaluator (§8)
  trackmath.py        PURE: fix filtering, stationary/moving segmentation, coverage, distance
  state.py            PURE: allowed transitions per axis; transition() is the only writer
  task_types.py       registry: TaskTypeSpec(code, payload model, reference types, channels, media)
  idempotency.py      Idempotent() FastAPI dependency over core.idempotency_keys
  deps.py             row targets for Perm(..., target=…)
  api_me.py           /api/me/…     (the field app)
  api.py              /api/fieldops/…  (managers, admins)
  tasks.py            Celery entry points (thin; call service.* via app/tasks/_loop.run_async)
  lang/               translated messages (msg_key)
```

**Import direction** (`.importlinter` contract `fieldops-is-a-leaf`): `fieldops` may import `geo`,
`users` (models/deps), `rbac`, `comments`, `media`, `documents`, `compliance`, `vehicles`, `entities`.
**Nothing imports `fieldops`** except `app/router.py`, `alembic/env.py` and the Celery task registry.

The `PATCH/GET /api/me/location` routes **move** from `users/api.py` to `fieldops/api_me.py` (same
paths, same response shape), and `users.service.record_location` is deleted. Otherwise `users` would
have to import `fieldops` to reach the ingest, and the leaf contract would break. `UserLiveLocation`
stays in `users/model.py`; `fieldops` writes it.

---

## 2. Table inventory

Every table is one of the tenancy classes (`tests/test_tenancy.py` conformance).

| Table | Class | Mixins | Why it exists |
|---|---|---|---|
| `fieldops.work_policies` | ENTITY | `IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin` | obligations per org × role (F-23) |
| `fieldops.devices` | ENTITY | `BigIntPKWithUUIDv7Mixin, OrgEntityMixin, DeactivationMixin, SoftDeleteFilteredMixin` | device binding (F-30) |
| `fieldops.device_sessions` | LEDGER | `IntPKMixin, MultiTenantMixin, AppMetaMixin, TimestampMixin` | per-launch capability snapshot |
| `fieldops.device_events` | LEDGER | `IntPKMixin, MultiTenantMixin, AppMetaMixin` | tracking-health events |
| `fieldops.shifts` | ENTITY | `BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin` (+ `HasCommentsMixin`, `HasMediaMixin`) | the work session |
| `fieldops.shift_pauses` | ENTITY | `BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin` | pauses (breaks, prayer, breakdowns, outages); paid vs unpaid time |
| `fieldops.visits` | ENTITY | `BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin` (+ comments, media, documents) | one customer engagement |
| `fieldops.visit_participants` | ENTITY | `IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin` | joint working |
| `fieldops.visit_tasks` | ENTITY | `BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin` (+ media, documents) | what was done in the visit |
| `fieldops.location_pings` | LEDGER (partitioned) | `MultiTenantMixin, AppMetaMixin` (PK declared by hand) | THE stream (replaces `user_location_pings`) |
| `fieldops.ping_batches` | LEDGER | `IntPKMixin, MultiTenantMixin, AppMetaMixin` | upload envelope, raw pointer (F-20) |
| `fieldops.location_checks` | LEDGER | `IntPKMixin, MultiTenantMixin, AppMetaMixin` | verification history (§8) |
| `fieldops.state_transitions` | LEDGER | `IntPKMixin, MultiTenantMixin, AppMetaMixin` | lifecycle + review history (F-24) |
| `fieldops.anomalies` | ENTITY | `BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin` | the review queue (F-27) |
| `fieldops.shift_metrics` | LEDGER (derived, upserted) | `IntPKMixin, MultiTenantMixin, AppMetaMixin, TimestampMixin` | KPIs, recomputable |
| `core.idempotency_keys` | LEDGER | `IntPKMixin, LedgerMixin, TimestampMixin` | replay-safe mutations (F-29) |

`OrgEntityMixin` brings `StatusMixin`. Tables with their own lifecycle **override** `status`
(String(20), their own default and CHECK), exactly as media does. The inherited `is_verified` stays
unused on those tables.

Conventions that apply to every table below (not repeated per table):

* the user FK is composite `(tenant_id, user_id) → users(tenant_id, id)` (`uq_users_tenant_id`);
* FKs to other `fieldops` ENTITY tables are composite `(tenant_id, x_id) → x(tenant_id, id)`, with a
  `UniqueConstraint("tenant_id", "id")` on the target;
* uniqueness on soft-deletable tables is always a **partial** unique index (`deleted_at IS NULL`);
* timestamps are `timestamptz`; every business time has a `*_received_at` and a `*_time_basis`
  sibling where it came from a device;
* the Python attribute for any JSONB "metadata"-like column is never `metadata`.

---

## 3. Tables

### 3.1 `fieldops.work_policies`

A policy row targets an organization and optionally a role. Resolution is in §12.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `role_id` | bigint | ✓ | | `(tenant_id, role_id) → roles (tenant_id, id)`; NULL = the organization's default |
| `name` | varchar(120) | | | "Sales reps — Godhra" |
| `requires_shift` | bool | | `true` | visits and tracking need an active shift |
| `allow_visits_without_shift` | bool | | `false` | managers doing ad-hoc visits |
| `tracking_mode` | varchar(20) | | `'continuous'` | `off / checkpoints_only / continuous` |
| `ping_interval_s` | int | | 60 | while moving |
| `stationary_interval_s` | int | | 300 | while still (activity recognition) |
| `ping_min_distance_m` | int | | 50 | distance filter |
| `geofence_enforcement` | varchar(20) | | `'advisory'` | `advisory / soft_block / hard_block` |
| `default_visit_radius_m` | int | | 100 | used when no fence exists and the place is field-verified |
| `geocoded_radius_factor` | numeric(4,2) | | 2.50 | radius × factor for `geocoded_only` places |
| `max_fix_accuracy_m` | int | | 100 | fixes worse than this are not evidence |
| `allow_manual_location` | bool | | `true` | manual override with a reason when no GPS |
| `require_start_selfie` | bool | | `false` | |
| `require_odometer` | bool | | `false` | |
| `require_start_at_place_id` | bigint | ✓ | | e.g. must start the day at the hub (checked, advisory) |
| `earliest_start_local` / `latest_end_local` | time | ✓ | | in the organization's timezone |
| `max_shift_hours` | numeric(4,1) | | 12.0 | auto-close cap when there is no planned end |
| `auto_close_grace_minutes` | int | | 60 | |
| `stale_shift_after_minutes` | int | | 240 | the supersede rule (F-31) |
| `min_visit_minutes` | numeric(5,1) | | 2.0 | shorter visits → `short_visit` anomaly |
| `gap_flag_minutes` | int | | 30 | tracking gap anomaly |
| `clock_skew_flag_seconds` | int | | 300 | |
| `min_tracking_coverage_pct` | numeric(5,2) | | 70 | below → anomaly |

Constraints: CHECKs on the enums and positives;
`uq_work_policies_target_live` = unique `(tenant_id, organization_id, COALESCE(role_id, 0))
WHERE deleted_at IS NULL`.

### 3.2 `fieldops.devices`, `device_sessions`, `device_events`

**devices** (one row per app installation):

| Column | Type | Notes |
|---|---|---|
| `user_id` | bigint | owner |
| `installation_id` | varchar(64) | app-generated on first launch; **never IMEI/Android ID** |
| `platform` | varchar(10) | `android / ios / web` |
| `manufacturer`, `model`, `os_version` | varchar | |
| `app_id` | varchar(100) | package / bundle id (FieldMate vs DLP) |
| `push_token` | text | |
| `first_seen_at`, `last_seen_at` | timestamptz | |
| `is_primary` | bool | the user's field device |

`uq_devices_installation_live (tenant_id, installation_id) WHERE deleted_at IS NULL`;
`uq_devices_one_primary (tenant_id, user_id) WHERE is_primary AND deleted_at IS NULL`.

**device_sessions** (one row per app session; upserted by `uuid`, which the client generates at launch):

| Column | Type | Notes |
|---|---|---|
| `uuid` | uuid | client session id (unique per tenant) |
| `device_id`, `user_id` | bigint | |
| `started_at`, `last_seen_at` | timestamptz | server times |
| `client_app_version`, `client_build` | varchar(32) | **not** `app_version` — that column (AppMetaMixin) is the *server* version stamped by tenancy.py |
| `os_version`, `sdk_int` | varchar / int | |
| `boot_count` | int | Android `Settings.Global.BOOT_COUNT`; iOS: derived from uptime reset |
| `location_permission` | varchar(24) | `always / while_in_use / denied` |
| `precise_location` | bool | Android 12+ approximate-only grant |
| `battery_optimization_exempt`, `power_save_mode` | bool | the #1 cause of killed tracking on Indian OEM builds |
| `auto_time_enabled`, `auto_timezone_enabled` | bool | clock-tamper signal |
| `developer_options`, `is_rooted` | bool | |
| `integrity_verdict` | varchar(40) | Play Integrity / App Attest summary; `integrity_checked_at` |
| `network_type`, `carrier`, `locale`, `device_timezone` | varchar | diagnostics only; never used for business time |

**device_events** (append-only):

| Column | Type | Notes |
|---|---|---|
| `uuid` | uuid | client event id; `UNIQUE (tenant_id, uuid)` |
| `user_id`, `device_id`, `session_uuid` | | |
| `event_type` | varchar(40) | `gps_disabled / gps_enabled / permission_changed / airplane_on / airplane_off / power_save_on / power_save_off / time_changed / timezone_changed / app_restarted_after_kill / boot / mock_app_detected / low_battery / tracking_paused / tracking_resumed` |
| `occurred_at`, `received_at`, `time_basis` | | §5 |
| `details` | jsonb | e.g. `{"from":"always","to":"while_in_use"}` |

Index: `(tenant_id, user_id, occurred_at DESC)`.

### 3.3 `fieldops.shifts`

| Column | Type | Null | Notes |
|---|---|---|---|
| `uuid` | uuid | | **client-generated UUIDv7** (server default only if absent) |
| `user_id` | bigint | | |
| `device_id` | bigint | ✓ | the device the shift is bound to (F-30) |
| `policy_id` | bigint | ✓ | policy resolved at start |
| `policy_snapshot` | jsonb | | the effective policy values **frozen at start**; KPIs of an old shift are judged by the rules in force then |
| `shift_date` | date | | organization-timezone business day of `started_at` (F-14), frozen |
| `status` | varchar(20) | | `scheduled / active / paused / completed / auto_closed / cancelled` (active + paused = OPEN) |
| `paused_since` | timestamptz | ✓ | start of the current pause; set exactly when `status = 'paused'` |
| `pause_count` | int | | pauses taken |
| `review_status` | varchar(20) | | `not_required / pending / approved / rejected / corrected` |
| `planned_start_at`, `planned_end_at` | timestamptz | ✓ | roster / scheduler, when one exists |
| `started_at` | timestamptz | ✓ | `occurred_at` of the start (NULL only while `scheduled`) |
| `start_received_at` | timestamptz | ✓ | |
| `start_time_basis` | varchar(24) | ✓ | `monotonic / wall_clock_corrected / server_receipt` |
| `start_check` | varchar(20) | ✓ | location check vs `require_start_at_place_id` (§8), else `not_configured` |
| `ended_at`, `end_received_at`, `end_time_basis` | | ✓ | |
| `ended_by` | varchar(10) | ✓ | `user / system / manager` |
| `end_reason` | varchar(24) | ✓ | `user / auto_closed / superseded / cancelled / manager_correction` |
| `last_activity_at` | timestamptz | ✓ | max `occurred_at` of any ping/visit/task; maintained by Core UPDATE with `GREATEST`, **no row_version bump** (same precedent as media conversions and team tree bounds), so ingest never collides with a manager's edit |
| `wall_clock_minutes` | numeric(8,2) | ✓ | `ended_at − started_at` |
| `pause_minutes`, `unpaid_pause_minutes` | numeric(8,2) | ✓ | all pause time / the part deducted from paid time |
| `paid_minutes` | numeric(8,2) | ✓ | wall clock − unpaid pauses — the attendance/payroll number |
| `duration_basis` | varchar(20) | ✓ | `device_reported / system_estimated / manager_adjusted` |
| `vehicle_id` | bigint | ✓ | → `vehicles.id` (fleet) |
| `travel_mode` | varchar(20) | ✓ | `two_wheeler / four_wheeler / public_transport / walk / company_vehicle` |
| `odometer_start_km`, `odometer_end_km` | numeric(10,1) | ✓ | photos in media collection `odometer` |
| `cancellation_reason` | text | ✓ | |
| `notes` | text | ✓ | single current summary; the running note stream is comments |
| `reviewed_by`, `reviewed_at` | | ✓ | last review decision (history in `state_transitions`) |

Constraints and indexes:

```sql
CHECK (status IN (...)), CHECK (review_status IN (...)), CHECK (ended_by IN (...)) …
CHECK (ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at)
CHECK (status <> 'active' OR (started_at IS NOT NULL AND ended_at IS NULL))
CHECK (status NOT IN ('completed','auto_closed') OR ended_at IS NOT NULL)
CHECK (odometer_end_km IS NULL OR odometer_start_km IS NULL OR odometer_end_km >= odometer_start_km)
UNIQUE (tenant_id, id)                                                   -- composite FK target
CREATE UNIQUE INDEX uq_shifts_uuid_live ON fieldops.shifts (tenant_id, uuid);            -- replay guard (not partial: a soft-deleted uuid must stay taken)
CREATE UNIQUE INDEX uq_shifts_one_open ON fieldops.shifts (tenant_id, user_id)
       WHERE status IN ('active','paused') AND deleted_at IS NULL;
CREATE INDEX ix_shifts_user_date   ON fieldops.shifts (tenant_id, user_id, shift_date DESC) WHERE deleted_at IS NULL;
CREATE INDEX ix_shifts_org_date    ON fieldops.shifts (tenant_id, organization_id, shift_date, status) WHERE deleted_at IS NULL;
CREATE INDEX ix_shifts_review      ON fieldops.shifts (tenant_id, shift_date) WHERE review_status = 'pending' AND deleted_at IS NULL;
CREATE INDEX ix_shifts_autoclose   ON fieldops.shifts (last_activity_at) WHERE status = 'active' AND deleted_at IS NULL;
```

`BigIntPKWithUUIDv7Mixin` declares `uuid` `unique=True` globally. That is stronger than
`(tenant_id, uuid)` and fine for UUIDv7. Keep the mixin's constraint and skip the extra index if the
migration review prefers one.

### 3.4 `fieldops.shift_pauses`

A pause is anything that stops work without ending the shift: a meal break, prayer, a meeting, a
vehicle breakdown, bad weather, no network. While a shift is paused (`status = 'paused'`) no visit
can start, and unless the policy says `track_during_pause`, the app stops tracking.

| Column | Type | Notes |
|---|---|---|
| `uuid` | uuid | client-generated |
| `shift_id`, `user_id` | bigint | composite FK → shifts |
| `pause_type` | varchar(20) | `meal / rest / prayer / personal / meeting / training / vehicle_issue / weather / network_issue / other` |
| `reason` | text | free text |
| `is_paid` | bool | frozen from `policy.paid_pause_types` when the pause starts |
| `tracking_suspended` | bool | frozen from `not policy.track_during_pause` |
| `started_at`, `start_received_at`, `start_time_basis`, `start_client_timestamp` | | |
| `ended_at`, `end_received_at`, `end_time_basis`, `end_client_timestamp` | | NULL = open |
| `ended_by` | varchar(10) | `user / system / manager` |
| `end_reason` | varchar(20) | `resumed / shift_ended / auto_closed / manager` |

`uq_shift_pauses_one_open (tenant_id, shift_id) WHERE ended_at IS NULL AND deleted_at IS NULL`.
A visit cannot start while paused (409 `shift_paused`); a shift cannot pause while a visit is in
progress (409 `visit_in_progress`). Policy knobs: `max_pause_minutes` (→ `long_pause` anomaly),
`max_pauses_per_shift` (→ `too_many_pauses`), `paid_pause_types`, `track_during_pause`.

### 3.5 `fieldops.visits`

| Column | Type | Null | Notes |
|---|---|---|---|
| `uuid` | uuid | | client UUIDv7 |
| `user_id` | bigint | | the rep who owns the visit |
| `shift_id` | bigint | ✓ | NULL only when the policy allows visits without a shift |
| `device_id` | bigint | ✓ | |
| `channel` | varchar(12) | | `field / telephonic / video` |
| `status` | varchar(20) | | `planned / in_progress / completed / cancelled / missed` |
| `review_status` | varchar(20) | | as shifts |
| `source` | varchar(12) | | `planned / unplanned` |
| `plan_ref` | uuid | ✓ | the beat/journey-plan item this fulfils (beat plans are a later module; the column reserves the join) |
| `sequence_in_plan` | int | ✓ | |
| `purpose` | varchar(24) | | `sales_call / collection / delivery / service / merchandising / survey / prospecting / relationship` |
| `account_type` | varchar(64) | ✓ | FK → `core.entity_types.code` (`customer`, `prospect`, `hub`, `vendor`; F-25) |
| `account_id` | bigint | ✓ | proved by the deferred registry trigger (the `tax_assignments` precedent) |
| `place_id` | bigint | ✓ | → `geo.places` (composite tenant FK); the WHERE of the visit |
| `contact_person_ref` | uuid | ✓ | reserved for the contacts module (who was met) |
| `planned_start_at`, `planned_end_at` | timestamptz | ✓ | |
| `started_at`, `start_received_at`, `start_time_basis` | | ✓ | NULL only while `planned` / `missed` |
| `ended_at`, `end_received_at`, `end_time_basis` | | ✓ | |
| `geofence_entry_at`, `geofence_exit_at` | timestamptz | ✓ | from dwell detection (§8.5) |
| `visit_time_basis` | varchar(10) | ✓ | `button / geofence` — which pair KPIs used |
| `start_check`, `end_check` | varchar(20) | | `inside / outside / uncertain / no_fix / not_configured / not_applicable`; default `not_configured` |
| `distance_from_target_m` | numeric(10,1) | ✓ | at start |
| `start_justification_code` | varchar(40) | ✓ | required when soft-blocked: `shop_relocated / met_outside / gps_poor / customer_location_wrong / other` |
| `start_justification_note` | text | ✓ | |
| `manual_location_reason` | text | ✓ | when the start fix was manual (§8.2) |
| `outcome` | varchar(24) | ✓ | `order_taken / no_order / collection_only / delivered / closed_shop / owner_absent / follow_up / info_only` |
| `no_order_reason` | varchar(40) | ✓ | `stock_sufficient / price_issue / credit_hold / competitor / not_interested / other` |
| `follow_up_at` | timestamptz | ✓ | |
| `cancellation_reason` | varchar(40) | ✓ | incl. `shift_auto_closed`, `superseded` |
| `notes` | text | ✓ | current summary |
| `reviewed_by`, `reviewed_at` | | ✓ | |

```sql
CHECK (channel IN ('field','telephonic','video'))
CHECK (channel = 'field' OR (start_check = 'not_applicable' AND end_check IN ('not_applicable')))   -- F-26a
CHECK (status <> 'in_progress' OR (started_at IS NOT NULL AND ended_at IS NULL))
CHECK (status <> 'completed' OR ended_at IS NOT NULL)
CHECK (ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at)
CHECK ((account_type IS NULL) = (account_id IS NULL))
CHECK (account_id IS NOT NULL OR place_id IS NOT NULL OR channel <> 'field')    -- a field visit is SOMEWHERE
UNIQUE (tenant_id, id)
CREATE UNIQUE INDEX uq_visits_uuid ON fieldops.visits (tenant_id, uuid);
CREATE UNIQUE INDEX uq_visits_one_in_progress ON fieldops.visits (tenant_id, user_id)
       WHERE status = 'in_progress' AND deleted_at IS NULL;
CREATE INDEX ix_visits_shift   ON fieldops.visits (shift_id, started_at) WHERE deleted_at IS NULL;
CREATE INDEX ix_visits_user    ON fieldops.visits (tenant_id, user_id, started_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ix_visits_account ON fieldops.visits (tenant_id, account_type, account_id, started_at DESC)
       WHERE account_id IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_visits_place   ON fieldops.visits (place_id, started_at DESC) WHERE place_id IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_visits_review  ON fieldops.visits (tenant_id, started_at) WHERE review_status = 'pending' AND deleted_at IS NULL;
CREATE INDEX ix_visits_plan    ON fieldops.visits (plan_ref) WHERE plan_ref IS NOT NULL;
```

The partial unique on `in_progress` is the database-level "cannot be at two customers at once". It
holds across shifts because it is per user, not per shift. Joint working does **not** break it: the
accompanying manager is a *participant* (§3.6), not the owner of a second visit.

### 3.6 `fieldops.visit_participants`

`visit_id`, `user_id`, `participant_role` (`joint_working / trainee / observer / backup`), `joined_at`,
`left_at`. `uq_visit_participants_live (tenant_id, visit_id, user_id) WHERE deleted_at IS NULL`.
A participant's own pings during the visit carry the visit's context only if their app joined it
(`POST /api/me/visits/{uuid}/join`).

### 3.7 `fieldops.visit_tasks`

| Column | Type | Null | Notes |
|---|---|---|---|
| `uuid` | uuid | | client UUIDv7, the natural idempotency key (F-26c) |
| `visit_id` | bigint | | composite FK → visits |
| `user_id` | bigint | | who performed it (a participant may) |
| `task_type` | varchar(32) | | see the registry below |
| `status` | varchar(12) | | `submitted / voided` |
| `performed_at`, `received_at`, `time_basis` | | | **independent** of the visit window |
| `after_visit_end` | bool | | `performed_at > visit.ended_at` at submit time. Recorded, never rejected (a late payment still counts) |
| `payload` | jsonb | | validated by the task type's Pydantic model; `payload_version` smallint |
| `reference_type` | varchar(64) | ✓ | → `core.entity_types.code` (`sales_order`, `customer_payment`, `sales_return`, …) |
| `reference_id` | bigint | ✓ | resolved id in the owning module |
| `reference_uuid` | uuid | ✓ | client uuid of a document created offline (resolved later, like pings, F-17) |
| `amount` | numeric(18,2) | ✓ | order value / collected amount, for metrics without joining every module |
| `currency_code` | char(3) | ✓ | |
| `void_reason` | text | ✓ | |

`uq_visit_tasks_uuid (tenant_id, uuid)`; `ix_visit_tasks_visit (visit_id, task_type) WHERE deleted_at
IS NULL`; `ix_visit_tasks_reference (reference_type, reference_id) WHERE reference_id IS NOT NULL`.
No GIN on payload (F-26d).

**Task-type registry** (`task_types.py`, a registry over conditionals, per the coding standards):

| `task_type` | Payload (Pydantic) | Reference | Channels | Media |
|---|---|---|---|---|
| `take_order` | lines summary, delivery date | `sales_order` | field, telephonic, video | — |
| `record_no_order` | reason code, competitor, note | — | all | optional shelf photo |
| `collect_payment` | mode (cash/UPI/cheque/NEFT), instrument no., amount | `customer_payment` | field (telephonic: UPI link only) | receipt photo |
| `deliver` | invoice ref, items, POD | `delivery` | field | signature (documents), photo |
| `process_return` / `process_exchange` | invoice ref, lines, reason | `sales_return` | field | photo |
| `stock_check` | SKU → qty on shelf | — | field | shelf photo |
| `product_detailing` | products discussed, duration | — | field, video | — |
| `distribute_sample` | product, **batch no.**, quantity, recipient (pharma compliance record) | — | field | acknowledgement (documents) |
| `survey` | survey id + answers | — | all | optional |
| `merchandising` | display type, compliance flags | — | field | before/after photos |
| `customer_feedback` | rating 1–5, comment (replaces v3 `visit_feedback`) | — | all | — |
| `note` | free text (quick; long threads use comments) | — | all | — |

Adding a task type is one registry entry plus one CHECK migration. Nothing else changes.

### 3.8 `fieldops.location_pings` — the stream

Partitioned `RANGE (recorded_at)`, monthly, DEFAULT partition from day one (the lesson of migration
`3b7f0ae91c46`). The PK is declared by hand (it must include the partition key).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | bigint identity | | |
| `recorded_at` | timestamptz | | **partition key**: device fix time, clamped to `[received_at − 45 d, received_at + 10 min]` (F-13) |
| `client_ping_id` | uuid | | client UUIDv7 of the fix |
| `batch_id` | bigint | ✓ | → `ping_batches.id` (no FK: partition drops) |
| `user_id` | bigint | | FK → users (composite). Kept: user deletion is a soft delete, so the FK never fires on the hot path |
| `device_id` | bigint | ✓ | no FK |
| `device_session_uuid` | uuid | ✓ | |
| `shift_id`, `visit_id` | bigint | ✓ | **independent**, both set during a visit (F-16); no FK (F-17) |
| `shift_uuid`, `visit_uuid` | uuid | ✓ | as sent by the client; ids back-filled by `link_orphan_pings` |
| `kind` | varchar(12) | | `continuous / checkpoint / manual` |
| `checkpoint_label` | varchar(24) | ✓ | `shift_start / shift_end / shift_pause / shift_resume / visit_start / visit_end / task_submitted / sos` |
| `client_timestamp` | timestamptz | ✓ | raw device wall-clock time of the fix, unclamped (as built; spec draft: `device_recorded_at`) |
| `elapsed_realtime_ms` | bigint | ✓ | monotonic clock at the fix |
| `boot_count` | int | ✓ | |
| `sequence_no` | bigint | ✓ | per device session; gaps/reordering diagnostics |
| `received_at` | timestamptz | | server |
| `occurred_at` | timestamptz | | **business time** (§5) |
| `time_basis` | varchar(24) | | |
| `clock_skew_ms` | int | ✓ | `received_at − sent_at` estimate |
| `coordinates` | geography(Point,4326) | ✓ | NULL allowed for a checkpoint with no fix (`no_fix`) |
| `latitude`, `longitude` | numeric(10,7) | ✓ | **GENERATED** from `coordinates` (F-21) |
| `accuracy_m` | real | ✓ | horizontal, 68 % radius |
| `altitude_m`, `vertical_accuracy_m` | real | ✓ | |
| `heading_deg`, `heading_accuracy_deg` | real | ✓ | |
| `speed_mps`, `speed_accuracy_mps` | real | ✓ | |
| `provider` | varchar(10) | | `gps / fused / network / passive / manual` |
| `satellites` | smallint | ✓ | |
| `is_mock` | bool | | default false |
| `activity_type` | varchar(12) | ✓ | `still / walking / running / on_bicycle / in_vehicle / unknown` |
| `activity_confidence` | smallint | ✓ | 0–100 |
| `battery_pct` | smallint | ✓ | 0–100 |
| `is_charging`, `power_save` | bool | ✓ | |
| `network_type` | varchar(10) | ✓ | `wifi / cell_2g … 5g / none` |
| `quality_flags` | int | | bitmask, default 0 (below) |
| `manual_reason` | text | ✓ | required when `provider = 'manual'` |
| `place_id` | bigint | ✓ | checkpoints: resolved place (the visit's place, or nearest known within 50 m) |
| `geocode_call_id` | bigint | ✓ | checkpoints only: provenance in `geo.geocode_api_calls` |
| `address_label` | text | ✓ | checkpoints only: display snapshot (F-19) |
| `extras` | jsonb | ✓ | sparse vendor fields; NULL normally |
| `app_version`, `app_metadata` | | | AppMetaMixin (server version); kept for LEDGER conformance |

`quality_flags` bits (one registry in `enums.py`, one SQL view `fieldops.v_ping_flags` that expands them):

| bit | flag | set by |
|---|---|---|
| 1 | `low_accuracy` (> policy `max_fix_accuracy_m`) | ingest |
| 2 | `mock` | ingest (mirrors `is_mock` for bitmask queries) |
| 4 | `impossible_speed` (implied > 250 km/h from previous accepted fix) | ingest |
| 8 | `clock_skew` (\|skew\| > policy) | ingest |
| 16 | `clock_tampered` (fix GNSS time vs device clock disagree, or `auto_time_enabled = false`) | ingest |
| 32 | `partition_key_clamped` | ingest |
| 64 | `foreign_device` (not the shift's device) | ingest |
| 128 | `out_of_order` (sequence regression within a session) | ingest |
| 256 | `stale_replay` (occurred > 24 h before receipt) | ingest (diagnostic, not an error) |
| 512 | `duplicate_coordinates` (identical to 6 decimals ×N consecutive) | ingest |

```sql
CONSTRAINT pk_location_pings PRIMARY KEY (recorded_at, id)
CHECK (kind IN ('continuous','checkpoint','manual'))
CHECK (checkpoint_label IS NULL OR kind = 'checkpoint')
CHECK (checkpoint_label NOT IN ('visit_start','visit_end','task_submitted') OR visit_uuid IS NOT NULL)
CHECK (checkpoint_label NOT IN ('shift_start','shift_end','shift_pause','shift_resume') OR shift_uuid IS NOT NULL)
CHECK (provider <> 'manual' OR manual_reason IS NOT NULL)
CHECK (battery_pct IS NULL OR battery_pct BETWEEN 0 AND 100)
CHECK (accuracy_m IS NULL OR accuracy_m >= 0)
CREATE UNIQUE INDEX uq_location_pings_client ON fieldops.location_pings
       (tenant_id, user_id, client_ping_id, recorded_at);                              -- idempotency
CREATE INDEX ix_location_pings_user_time  ON fieldops.location_pings (tenant_id, user_id, occurred_at DESC);
CREATE INDEX ix_location_pings_shift      ON fieldops.location_pings (shift_id, occurred_at) WHERE shift_id IS NOT NULL;
CREATE INDEX ix_location_pings_checkpoint ON fieldops.location_pings (tenant_id, occurred_at) WHERE kind = 'checkpoint';
CREATE INDEX ix_location_pings_unlinked   ON fieldops.location_pings (received_at)
       WHERE (shift_uuid IS NOT NULL AND shift_id IS NULL) OR (visit_uuid IS NOT NULL AND visit_id IS NULL);
```

No GiST index (F-18). Every spatial question is asked of one user's time window, which the btree
narrows first.

**Sizing.** 500 field users × 1 fix/min × 10 h ≈ 300 k rows/day ≈ 9 M/month. At roughly
350 bytes per row including the four indexes, that is about 3 GB/month. Monthly partitions, dropped
at the retention horizon (D3: 180 days → ~18 GB steady state). This is comfortably within plain
PostgreSQL; TimescaleDB is not needed.

### 3.9 `fieldops.ping_batches`

| Column | Notes |
|---|---|
| `uuid` | client batch id; `UNIQUE (tenant_id, uuid)`. A re-sent batch returns the stored per-item result |
| `user_id`, `device_id`, `device_session_uuid` | |
| `sent_at`, `sent_elapsed_ms`, `sent_boot_count` | the device clocks at send (headers) |
| `received_at`, `ingest_ms` | |
| `item_count`, `accepted_count`, `duplicate_count`, `rejected_count` | |
| `results` | jsonb: `[{"client_ping_id", "status", "reason"}]` for non-accepted items only |
| `payload_sha256` | |
| `raw_object_key`, `raw_expires_at` | gzip'd body in the private Garage bucket (media storage disk), purged at expiry (default 30 d) |

### 3.10 `fieldops.location_checks`

One row per evaluation. Re-evaluation appends; the newest row per `(subject, phase)` is authoritative.

| Column | Notes |
|---|---|
| `subject_type`, `subject_id` | `visit / shift` |
| `phase` | `start / end / revalidation` |
| `evaluated_at`, `evaluator_version` | code version of `verification.py` (reproducibility) |
| `fix_client_ping_id`, `fix_recorded_at`, `fix_accuracy_m`, `fix_is_mock` | the evidence used |
| `evidence_count` | fixes considered in the window |
| `target_kind` | `polygon / circle / place_default / none` |
| `geofence_id`, `place_id`, `radius_m` | |
| `distance_m` | 0 when a polygon covers the point |
| `result` | `inside / outside / uncertain / no_fix / not_configured / not_applicable` |
| `enforcement` | the policy mode applied |
| `action_taken` | `recorded / justification_required / blocked / override_accepted / bypassed_offline` |

Index `(subject_type, subject_id, phase, evaluated_at DESC)`.

### 3.11 `fieldops.state_transitions`

| Column | Notes |
|---|---|
| `subject_type`, `subject_id`, `subject_uuid` | `shift / visit / visit_task / shift_pause` |
| `axis` | `lifecycle / review` |
| `from_state`, `to_state` | |
| `reason_code`, `note` | |
| `occurred_at`, `received_at`, `time_basis` | |
| `actor_user_id`, `actor_label` | `system:fieldops-autoclose` etc. for jobs |
| `source` | `device / server / system / manager` |
| `request_id`, `idempotency_key` | trace a transition back to the exact request |
| `changes` | jsonb: `{"field": [before, after]}` for corrections |

Index `(subject_type, subject_id, occurred_at)`. `state.transition()` is the **only** code that
changes a `status` / `review_status`, and it writes this row in the same transaction.

### 3.12 `fieldops.anomalies`

| Column | Notes |
|---|---|
| `anomaly_type` | the list in §11 |
| `severity` | `info / warning / critical` |
| `subject_type`, `subject_id` | `shift / visit / visit_task / place / device` |
| `user_id`, `shift_id` | denormalised for the queue filters |
| `detected_at`, `detector` | `system:fieldops-<detector>` |
| `evidence` | jsonb (distances, gap window, fix ids…) |
| `dedupe_key` | e.g. `long_gap:shift:123:2026-09-28T10:05` — `uq_anomalies_dedupe (tenant_id, dedupe_key) WHERE deleted_at IS NULL`, so every detector is idempotent |
| `state` (overrides `status`) | `open / acknowledged / resolved / dismissed` |
| `resolved_by`, `resolved_at`, `resolution_code`, `resolution_note` | |

Index `(tenant_id, organization_id, state, detected_at DESC)`.

### 3.13 `fieldops.shift_metrics`

One row per shift, upserted by `compute_shift_metrics`. Recomputable at any time (after a correction,
after late pings, after a `metrics_version` bump).

| Group | Columns |
|---|---|
| provenance | `shift_id` (unique), `computed_at`, `metrics_version`, `inputs_hash` (skip the write when unchanged, HashGuard idea) |
| time | `wall_clock_minutes`, `pause_minutes`, `paid_minutes`, **`engaged_minutes`**, `visit_minutes`, `travel_minutes`, `idle_minutes`, `first_visit_at`, `last_visit_at` |
| tracking health | `fix_count`, `accepted_fix_count`, **`tracking_coverage_pct`**, `longest_gap_minutes`, `mock_fix_count`, `low_accuracy_fix_count`, `clock_skew_max_s` |
| movement | `gps_distance_km`, `map_matched_distance_km` (Valhalla, when configured), `odometer_distance_km` |
| visits | `visits_planned`, `visits_completed`, `visits_missed`, `visits_unplanned`, `field_visits`, `telephonic_visits`, `video_visits`, `productive_visits` (outcome `order_taken`) |
| geofence | `visits_checked` (had a target), `visits_inside`, `visits_outside`, `visits_uncertain`, `geofence_compliance_pct` (= inside / checked; NULL when nothing was checkable, never 0) |
| commercial | `orders_field`, `orders_telephonic`, `order_value_field_base`, `order_value_telephonic_base`, `collections_base`, `base_currency` |
| review | `anomaly_count_open` |

Field and telephonic are **separate columns everywhere**. That is the brief's point: phone orders must
not inflate field coverage.

### 3.14 `core.idempotency_keys`

| Column | Notes |
|---|---|
| `user_id` | |
| `key` | uuid (client ULID/UUIDv7) |
| `route` | e.g. `POST /api/me/visits/{uuid}/end` |
| `request_fingerprint` | sha256(method + route + canonical body) |
| `state` | `in_flight / completed` |
| `response_status`, `response_body` | jsonb, the stored envelope |
| `entity_type`, `entity_uuid` | what it created/changed |
| `expires_at` | now + 30 d |

`UNIQUE (tenant_id, user_id, key)`; `ix_idempotency_keys_expires (expires_at)`.

---

## 4. State machines

`state.py` holds the tables; `transition(subject, axis, to, *, reason, actor, occurred_at, source)`
validates, writes the new state, stamps the lifecycle timestamps and appends `state_transitions`. It
is the only writer.

**Shift lifecycle**

```
scheduled ──start──▶ active ──end──────────▶ completed
    │                  │ └──auto_close────▶ auto_closed      (review_status → pending)
    └──cancel──▶ cancelled ◀──cancel── (active, manager only, no visits)
                       └──supersede──▶ auto_closed (end_reason = superseded, F-31)
```

**Visit lifecycle**

```
planned ──start──▶ in_progress ──end──▶ completed
   │ └──(day ends)──▶ missed            │
   └──cancel──▶ cancelled ◀──cancel─────┘   (incl. cascade: reason shift_auto_closed)
```

**Review axis** (shifts and visits): `not_required → pending → approved | rejected | corrected`.
`corrected` = a manager changed times. The change is in `state_transitions.changes`, the shift's
`duration_basis` becomes `manager_adjusted`, and metrics are recomputed.

**Cascade on auto-close.** In the same transaction: every `in_progress` visit under the shift →
`cancelled`, `cancellation_reason = 'shift_auto_closed'`, `ended_at = its own last activity` (or its
start); any open pause → ended at the shift's `ended_at`. The brief's orphan-visit problem cannot
occur because it all happens in one transaction.

**Visits with no shift** (policy allows): a visit that starts while no shift is active and
`requires_shift = true` → **422 `shift_required`**. With `requires_shift = false` the visit stands
alone (`shift_id NULL`).

---

## 5. The time model (`clock.py`)

Inputs per request/batch (headers) and per item (body):

```
X-Device-Sent-At:      2026-09-28T13:10:04.120+05:30   device wall clock when the request was sent
X-Device-Elapsed-Ms:   84211934                         monotonic clock at send
X-Device-Boot-Count:   212
X-Device-Session:      <uuid>
X-Idempotency-Key:     <uuid>                           mutations only
item: device_recorded_at, elapsed_realtime_ms, boot_count
```

```python
def derive_occurred_at(*, received_at, sent_at, sent_elapsed_ms, sent_boot,
                       item_wall, item_elapsed_ms, item_boot) -> Derived:
    if item_elapsed_ms is not None and sent_elapsed_ms is not None and item_boot == sent_boot \
            and item_elapsed_ms <= sent_elapsed_ms:
        occurred = received_at - timedelta(milliseconds=sent_elapsed_ms - item_elapsed_ms)
        basis = "monotonic"
    elif item_wall is not None and sent_at is not None:
        occurred = item_wall + (received_at - sent_at)          # skew correction
        basis = "wall_clock_corrected"
    else:
        occurred, basis = received_at, "server_receipt"
    occurred = min(occurred, received_at)                        # nothing happened in the future
    skew_ms = int((received_at - sent_at) / ms) if sent_at else None
    return Derived(occurred, basis, skew_ms)
```

Network latency sits inside `received_at − sent_at` (typically well under a second, and bounded by the
request timeout), which is far below any KPI's resolution. The same function stamps pings, shift/visit
starts and ends, pauses, tasks and device events, so a visit's `started_at` and its `visit_start`
checkpoint are guaranteed to agree.

`shift_date = (occurred_at AT TIME ZONE COALESCE(org.timezone, tenant default, 'Asia/Kolkata'))::date`
at start, frozen. A shift that crosses midnight stays on its start day.

---

## 6. Ping ingestion (`service/ingest.py`)

`POST /api/me/location-pings`: body `{batch_uuid, pings: [...≤ 500]}`, `Content-Encoding: gzip`
accepted (a small request-decompression dependency; bodies above 1 MB decompressed are refused).

```
0. Idempotent batch: ping_batches.uuid exists → return its stored results (200).        [1 query]
1. Validate items (Pydantic): ranges, NaN/inf refused, manual ⇒ reason, ≤ 500 items.
   Invalid items are REJECTED per item; the rest proceed.
2. Resolve contexts: one SELECT of shifts/visits by the batch's distinct shift_uuid/visit_uuid.  [1 query]
3. Per item (pure, trackmath/clock):
     occurred_at, time_basis, skew
     recorded_at = clamp(device_recorded_at, received − 45 d, received + 10 min)  (flag bit 32)
     quality flags: accuracy, mock, speed vs previous accepted fix (in batch, else user_live_locations),
                    skew, tamper, foreign device, out-of-order, stale replay, duplicate coordinates
4. Clamped items only: Redis SET NX fieldops:ping:{tenant}:{client_ping_id} (DB 0, TTL 45 d);
   an existing key → duplicate (F-13).
5. INSERT … ON CONFLICT (tenant_id, user_id, client_ping_id, recorded_at) DO NOTHING
   RETURNING client_ping_id    → accepted = returned; duplicates = sent − returned − rejected.   [1 query]
6. Live projection: newest accepted, non-mock fix by occurred_at →
   INSERT INTO user_live_locations (…, recorded_at = :occurred_at) ON CONFLICT (tenant_id, user_id) DO UPDATE …
   WHERE excluded.recorded_at > user_live_locations.recorded_at          (recency guard, F-26m)   [1 query]
   (the live row has no occurred_at column; its recorded_at now holds the corrected occurred_at —
    update the column comment "Device clock" → "Corrected fix time (fieldops clock.py)" in M2)
7. Core UPDATE fieldops.shifts SET last_activity_at = GREATEST(last_activity_at, :max_occurred)
   WHERE id = ANY(:shift_ids)          (no row_version bump)                                     [1 query]
8. INSERT ping_batches (counts, per-item non-accepted results, sha256, raw key).                 [1 query]
9. COMMIT. After commit: write raw gzip to Garage (best effort; a failure leaves raw_object_key NULL
   and logs fieldops.raw_archive_failed); enqueue reverse_geocode_checkpoint for new checkpoints;
   publish live position to Soketi (throttled 1 per user per 15 s).
```

The query count per batch is constant (about 7) regardless of batch size. The N+1 regression test
asserts this (§17).

**Response (always 200):**

```json
{"code": 0, "msg": "ok", "request_id": "…",
 "data": {"batch_uuid": "…", "accepted": 487, "duplicates": 11, "rejected": 2,
          "results": [{"client_ping_id": "…", "status": "rejected", "reason": "latitude_out_of_range"},
                      {"client_ping_id": "…", "status": "duplicate"}]}}
```

The client drops `accepted` and `duplicate` items from its queue, drops `rejected` items too (they are
unfixable and already logged server-side), and retries only on transport errors or 5xx.
`duplicate` counts as success.

**Rate limits.** The inbound slowapi gate applies per user (a stricter per-route limit, e.g. 30 batch
requests/min). Items implying more than 1 fix/second within a session are accepted but flagged; they
are not errors. Abuse → 429 through the existing handler.

**`PATCH /api/me/location`** (the existing single-fix route) becomes a one-item batch through the same
pipeline, so older app builds keep working and write the new stream.

---

## 7. Shift, visit and task flows

Every mutating `/api/me` route takes `Idempotent()`: it looks up `core.idempotency_keys` for the
`X-Idempotency-Key`. Same fingerprint → replay the stored response. Different fingerprint →
`409 idempotency_key_reused`. Otherwise it runs the handler and stores the response in the same
transaction as the change.

### 7.1 Start shift — `POST /api/me/shifts`

```json
{"uuid": "0192…", "occurred": {"device_recorded_at": "…", "elapsed_realtime_ms": 84000000, "boot_count": 212},
 "fix": {"client_ping_id": "…", "latitude": 22.7788, "longitude": 73.6144, "accuracy_m": 12, "provider": "fused",
         "is_mock": false, "…": "…"},
 "manual_location": null,
 "vehicle_id": null, "travel_mode": "two_wheeler", "odometer_start_km": 18342.5,
 "selfie_media_uuid": null}
```

1. `policy = resolve_policy(user)`. `requires_shift = false` for this user → the route still works (a
   manager may choose to run shifts), with nothing enforced.
2. **Consent gate:** an active `compliance.consent_records` row `location_tracking` for the user, else
   **422 `location_consent_required`** (the app shows the notice and records consent through the
   compliance API).
3. Device binding: resolve `X-Device-Session` → device; unknown → `422 device_not_registered`.
4. `occurred_at` via `clock.py`. Window check against `earliest_start_local` (advisory → anomaly
   `early_start`).
5. **Location:** `fix` present → it becomes a `checkpoint` ping (`shift_start`) in the stream, in this
   transaction. No fix and `allow_manual_location` → `manual_location.reason` required, else **422
   `location_required`**. No fix and no manual → 422.
6. Start-place check (when `require_start_at_place_id`): the §8 evaluator → `start_check`, advisory only.
7. Selfie / odometer required by policy and missing → 422 naming the field.
8. INSERT the shift (`status = 'active'`, `policy_snapshot`, `shift_date`). A unique violation on
   `uq_shifts_one_open` → the **supersede rule** (F-31): same device and the active shift's
   `last_activity_at + stale_shift_after_minutes < occurred_at` → auto-close it (`superseded`, review
   pending, anomaly) and retry once. Otherwise **409 `shift_already_active`** with
   `data.active_shift` (uuid, started_at, device).
9. `state_transitions` + `activity.recorder` (`shift_started`). **201** with the shift (Fat DTO).

### 7.2 End shift — `POST /api/me/shifts/{uuid}/end`

The body carries occurred clocks, `fix`, and `odometer_end_km`. Order of operations: end the open pause;
refuse while a visit is `in_progress` (**409 `visit_in_progress`** with its uuid; the app offers "end
visit"); write the `shift_end` checkpoint; compute `wall_clock/pause/paid_minutes` and
`duration_basis = device_reported`; `status = completed`. After commit: enqueue
`compute_shift_metrics` + `detect_shift_anomalies`. Ending an already-ended shift with the same
idempotency key replays; with a new key → **409 `shift_not_active`**.

### 7.3 Pause / resume — `POST /api/me/shifts/{uuid}/pause`, `POST /api/me/shifts/{uuid}/resume`

Pause: the shift must be `active` and have no visit in progress; a `shift_pauses` row opens, the
shift moves to `paused` (`paused_since` set, `pause_count + 1`), a `shift_pause` checkpoint goes into
the stream. Resume: the open pause ends (`resumed`), the shift returns to `active`, a
`shift_resume` checkpoint is written, and a pause longer than `max_pause_minutes` opens
`long_pause`. Ending (or auto-closing) a paused shift closes the pause at the shift's end.

### 7.4 Start visit — `POST /api/me/visits`

```json
{"uuid": "…", "shift_uuid": "…", "channel": "field", "purpose": "sales_call",
 "account": {"type": "customer", "id": 1234}, "place_uuid": "…", "plan_ref": null,
 "occurred": {…}, "fix": {…}, "manual_location": null,
 "justification": null, "override_token": null}
```

1. Channel gate: `telephonic` / `video` require **`fieldops.telephonic_visit:create`** (else 403 through
   the RBAC handler). Their `start_check = not_applicable`, but a fix is still recorded when present,
   for stream continuity.
2. Shift gate (§4): `requires_shift` and no open shift → **422 `shift_required`**; a paused shift → 409 `shift_paused`.
3. Resolve account (registry trigger proves it) and place. A field visit needs account **or** place.
4. Write the `visit_start` checkpoint (the fix) with `visit_uuid` and `shift_uuid`.
5. **Verify** (§8) → a `location_checks` row → `start_check`, `distance_from_target_m`.
6. Apply enforcement (§8.4): may return **422 `justification_required`** (soft block; `data` carries
   `result`, `distance_m`, allowed reason codes) or **422 `outside_geofence`** (hard block;
   `data.override` explains the manager override). With a valid `justification` or `override_token`
   the visit proceeds, flagged.
7. INSERT the visit (`in_progress`). Violating `uq_visits_one_in_progress` → **409 `visit_in_progress`**
   with `data.active_visit`. The rule is global per user, across shifts.
8. After commit: nothing heavy. Dwell detection runs at end.

### 7.5 End visit — `POST /api/me/visits/{uuid}/end`

Body: occurred, fix, `outcome`, `no_order_reason`, `follow_up_at`. Writes the `visit_end` checkpoint and
an `end` location check (advisory, whatever the mode: ending is never blocked), then sets
`completed`. After commit: `detect_dwell(visit)` with a 5-minute countdown so trailing pings can
arrive, plus a debounced shift metrics recompute.

### 7.6 Tasks — `POST /api/me/visits/{uuid}/tasks`, `POST /api/me/visit-tasks/{uuid}/void`

The registry validates `payload` against the `task_type` model and checks channel eligibility.
`performed_at` is derived by `clock.py` and is **not** bounded by the visit window. `after_visit_end`
records the fact. Allowed for a visit in `in_progress` or `completed` within `policy.late_task_window`
(default 12 h); a `cancelled` visit → 409. Writes a `task_submitted` checkpoint when a fix is sent.
When the task creates a document in another module (an order created offline), `reference_uuid` holds
the client uuid until that module resolves it.

---

## 8. Location verification (`verification.py`)

### 8.1 Target resolution (one query)

```
visit.place_id → geo.geofences WHERE place_id = :place AND status='active' AND deleted_at IS NULL
                 AND (valid_from IS NULL OR valid_from <= :t) AND (valid_to IS NULL OR valid_to > :t)
                 ORDER BY (boundary IS NOT NULL) DESC LIMIT 1         -- polygon beats circle
             → else geo.places.coordinates with radius
                   = policy.default_visit_radius_m                     if verification_status = 'field_verified'
                   = policy.default_visit_radius_m × geocoded_factor   if 'geocoded_only'
                   → not_configured                                    if unverified / no coordinates
                   → not_configured + anomaly disputed_place           if 'disputed'
```

`geo.geofences` gains **one nullable column**, `visit_enforcement` (`advisory / soft_block / hard_block`),
a per-fence override of the policy for sensitive sites. It is the only change to the `geo` schema.

### 8.2 Evidence

The checkpoint fix sent with the action, plus every stream fix of the user in
`[t − 120 s, t + 60 s]`, excluding `is_mock` and bits `impossible_speed | duplicate_coordinates`. The
best fix is the lowest `accuracy_m`. None usable → `no_fix`. A **manual** location is recorded, but
it is never evidence: the result is `no_fix`, with `manual_location_reason` on the visit.

### 8.3 Classification (pure, table-tested)

```python
def classify(distance_m: float | None, radius_m: float | None, accuracy_m: float | None,
             *, channel: str, max_accuracy_m: float) -> Result:
    if channel != "field":                        return "not_applicable"
    if radius_m is None:                          return "not_configured"
    if distance_m is None or accuracy_m is None or accuracy_m > max_accuracy_m:
                                                  return "no_fix"
    if distance_m + accuracy_m <= radius_m:       return "inside"
    if distance_m - accuracy_m > radius_m:        return "outside"
    return "uncertain"
```

The spatial part is one SQL statement:
`ST_Distance(target_geog, fix_geog)`, with `CASE WHEN ST_Covers(boundary, fix) THEN 0`, for the
polygon case. Geography, so the distance is ellipsoidal. No Python-side geodesy (F-05).

### 8.4 Enforcement matrix

| mode ↓ / result → | `inside` | `uncertain`, `no_fix` | `outside` | `not_configured`, `not_applicable` |
|---|---|---|---|---|
| `advisory` | ok | ok | ok + anomaly `outside_geofence` (warning) | ok |
| `soft_block` | ok | ok (+ `info` anomaly when `no_fix`) | **justification required** → ok, `review_status = pending` | ok |
| `hard_block` | ok | treated as soft_block | **422 `outside_geofence`**; manager `override_token` accepted | ok |

**Offline replay** (`start_received_at − started_at > 2 min` means the device decided offline): the
server re-evaluates. If it would have blocked, the visit is **accepted** with
`action_taken = bypassed_offline` and a `hard_block_bypassed_offline` anomaly (critical). The app
evaluates locally with the fence pack (§14.4) using the same `classify` rules. The Python function is
the spec the Kotlin/TS port is tested against, using shared fixtures (`tests/fixtures/classify_cases.json`).

**Override tokens.** A manager (with `fieldops.visit:approve` on the rep's organization) issues a
short-lived signed token (JWT, 15 min, bound to rep + place) via `POST /api/fieldops/visit-overrides`.
It is typically shown as a code over the phone. The token id goes into `location_checks`.

### 8.5 Dwell (`geofence_entry_at` / `geofence_exit_at`)

A Celery job after `visit_end` (and again when late pings for the window arrive):

```
fixes = user's accepted fixes in [started_at − 15 min, ended_at + 15 min], ordered by occurred_at
entry = first fix of the first run of consecutive inside-fixes spanning ≥ fence.dwell_threshold_s
exit  = first fix of the first run of outside-fixes after entry spanning ≥ dwell_threshold_s
confidence = high (≥ 3 fixes, median accuracy ≤ 30 m) / medium / low
```

KPIs use `entry … exit` only when both exist with confidence ≥ medium, and set
`visit_time_basis = geofence`. Otherwise they use the button presses (`button`). No target → button.

### 8.6 Outlet geotagging (phase 3)

`propose_geotags` (nightly): places with no coordinates or `geocoded_only`, with ≥ 3 field visits by
≥ 2 distinct users whose best fixes are ≤ 30 m accurate and cluster within 50 m. It opens a
`place_geotag_proposal` anomaly carrying the centroid, member fixes and spread. Resolving it with
`accept` calls the geo service: set `coordinates`, `mark_verified(method='field_visit')`. Moving
coordinates clears prior verification (geo README §4), as it should.

---

## 9. Auto-close (`service/shifts.auto_close`)

Beat every 5 minutes, `system_scope` actor `system:fieldops-autoclose`:

```sql
SELECT id FROM fieldops.shifts
 WHERE status = 'active' AND deleted_at IS NULL
   AND now() > COALESCE(planned_end_at, started_at + (policy_snapshot->>'max_shift_hours')::numeric * interval '1 hour')
             + (policy_snapshot->>'auto_close_grace_minutes')::int * interval '1 minute'
 FOR UPDATE SKIP LOCKED          -- two beat workers never close the same shift
```

Per shift, in one transaction:

```
cap            = COALESCE(planned_end_at, started_at + max_shift_hours) + grace
last_activity  = GREATEST(max accepted ping occurred_at in the shift,
                          max visit ended_at / started_at under it,
                          max task performed_at under it, max pause ended_at)
effective_end  = LEAST(COALESCE(last_activity, started_at), cap)
ended_at = effective_end; ended_by = system; end_reason = auto_closed; status = auto_closed
duration_basis = system_estimated; review_status = pending
cascade (§4); anomalies: auto_closed (warning); ghost_shift (critical) when last_activity IS NULL
     or effective_end − started_at < 5 min; long_gap when the last gap > policy.gap_flag_minutes
```

A shift with no activity closes at `started_at`: duration 0 and flagged as a ghost, never a false
16-hour day. Late pings that arrive **after** auto-close still land in the stream with the shift's
context; `compute_shift_metrics` runs again and the anomaly evidence records the late data, but
`ended_at` does not move without a manager (`corrected`).

---

## 10. Metrics (`service/metrics.py`, `trackmath.py`)

Triggered on shift end/auto-close, on correction, and debounced (Redis lock, 2 min) when late pings or
tasks arrive for a closed shift. `inputs_hash` skips the write when nothing changed.

1. **Fix filter:** accepted = not mock, `accuracy ≤ policy.max_fix_accuracy_m`, no
   `impossible_speed`/`duplicate_coordinates`.
2. **Segmentation:** consecutive fixes → `moving` when displacement / Δt > 0.8 m/s, or
   `activity_type ∈ (in_vehicle, on_bicycle, walking)` with confidence ≥ 60; else `stationary`.
3. **Time buckets** over `[started_at, ended_at]`, minus pauses:
   `visit_minutes` = Σ visit durations (geofence-verified bounds where §8.5 allows, else button),
   clipped to the shift and **merged** where visits overlap in time (overlap is impossible by the
   index for one user, but participants' joint visits are not counted twice);
   `travel_minutes` = moving minutes outside visits;
   `idle_minutes` = stationary minutes outside visits and pauses;
   **`engaged_minutes = visit_minutes + travel_minutes between the first and last visit`**, the
   productivity number, separate from `paid_minutes`, the attendance number.
4. **Coverage:** buckets of `policy.ping_interval_s × 2` during `paid` time that have ≥ 1 fix, divided
   by all buckets. The stationary interval is used while stationary. `longest_gap_minutes` is the
   largest gap.
5. **Distance:** Σ haversine between consecutive accepted fixes (`geo/distance.py`), ignoring hops
   inside the accuracy radius. When `ROUTING_PROVIDER=valhalla` is configured, the map-matched
   distance goes in a separate column and never replaces the raw one.
6. **Visits / geofence / commercial** aggregates as listed in §3.13, split by channel.
   `geofence_compliance_pct` has `visits_checked` as its denominator, so an organization with no fences
   gets NULL, not 0 %.

`metrics_version` is a constant in `metrics.py`. Bumping it plus `POST
/api/fieldops/shifts/metrics/recompute?date_from=` recomputes history under the new algorithm, and old
numbers stay explainable.

---

## 11. Anomalies and the review queue

| `anomaly_type` | Severity | Detector / when |
|---|---|---|
| `ghost_shift` | critical | auto-close, no activity |
| `auto_closed` | warning | auto-close |
| `superseded_shift` | warning | start rule F-31 |
| `long_gap` | warning | metrics: gap > `gap_flag_minutes` during paid time |
| `low_tracking_coverage` | warning | metrics: coverage < `min_tracking_coverage_pct` |
| `tracking_disabled` | warning | device events: GPS off / permission downgraded during a shift |
| `mock_location` | critical | ingest: ≥ 3 mock fixes in a shift, or any on a checkpoint |
| `impossible_speed` | warning | ingest |
| `clock_skew` / `clock_tampered` | warning | ingest / device session (`auto_time_enabled = false`) |
| `foreign_device` | warning | ingest |
| `outside_geofence` | warning | verification (advisory) |
| `justified_outside` | info | verification (soft block with justification) |
| `hard_block_bypassed_offline` | critical | verification on replay |
| `manual_location` | info | start with manual location |
| `short_visit` | info | visit < `min_visit_minutes` |
| `visit_without_shift` | info | when allowed by policy |
| `late_task` | info | task after visit end beyond 1 h |
| `early_start` / `late_end` | info | policy window |
| `disputed_place` | warning | verification target is disputed |
| `place_geotag_proposal` | info | nightly (§8.6) |

The **review queue** (`GET /api/fieldops/review-queue`) = open anomalies ∪ shifts/visits with
`review_status = 'pending'`, grouped by shift, filtered to what the caller may see (§13). Resolving the
last open anomaly of a shift does **not** auto-approve it. Approval is an explicit act
(`POST /api/fieldops/shifts/{ref}/review`).

---

## 12. Policy resolution (`service/policy.py`)

```
user → base role (users.role_id) + home organization (users.organization_id)
for org in [home, parent, …, root]  (hierarchy_path, nearest first):
    row = policy WHERE organization_id = org AND role_id = user.role_id   → return
    row = policy WHERE organization_id = org AND role_id IS NULL          → return
return CODE_DEFAULTS   (the column defaults in §3.1)
```

* **Base role only**, deliberately. A contextual grant ("acting team manager in branch B") does not
  change a person's obligations (F-23).
* Cached per user in Redis DB 0 (`fieldops:policy:{tenant}:{user}`, TTL 300 s), invalidated by a
  per-tenant epoch bumped on any policy write, the RBAC cache pattern.
* The shift freezes it (`policy_snapshot`). Changing a policy mid-day affects the **next** shift.
* `GET /api/me/fieldops/policy` returns the effective policy plus capability flags (`can_telephonic`,
  computed from the caller's grants) so the app can show or hide channels.

---

## 13. RBAC

**Catalogue additions** (`rbac/catalogue.py`, one block under "operations"):

```python
*_p("fieldops", "field_work", "use", "the field app: own shifts, visits, tasks and location"),
*_p("fieldops", "telephonic_visit", "create", "telephonic and video visits"),
*_p("fieldops", "shift", "read update delete approve manage", "shifts"),
*_p("fieldops", "visit", "read update delete approve manage", "visits"),
*_p("fieldops", "anomaly", "read approve", "field-ops anomalies (approve = resolve)"),
*_p("fieldops", "policy", "create read update delete manage", "field work policies"),
```

Others' tracks and the live map reuse the existing **`users.location:read`**. That permission was
deliberately withheld from `member` (rbac-module F2) and stays that way.

**Templates** (`rbac/templates.py`):

| Template | Gains |
|---|---|
| `member` | `fieldops.field_work:use` (a new feature, added directly, **not** to `_OPERATIONAL`, the comments precedent) |
| `team_manager` | `fieldops.shift:read/approve`, `fieldops.visit:read/approve`, `fieldops.anomaly:read/approve`, `users.location:read` |
| `department_head` | the above + `fieldops.policy:read` |
| `auditor` | reads come automatically (`codes_matching(actions={"read"})`) |
| `admin` / `owner` | computed: everything |

`fieldops.telephonic_visit:create` is in **no template**. Each organization grants it to its own
explicit role(s), e.g. `sales_rep`, through the roles API. That is exactly "in an organization I should
be able to allow certain roles to do telephonic visits".

**Row targets:** manager routes on `{ref}` declare
`Perm("fieldops.shift:approve", target=org_of("fieldops:Shift", param="ref"))`, so a branch-A manager
cannot approve branch-B shifts (`tests/test_rbac_routes.py` fails CI otherwise).

**Data scope (D8).** RBAC reads are tenant-wide today. For location data that is not acceptable, so
the manager list/track/live routes add an **explicit team filter**: a caller without an org-level grant
sees only users in teams they manage (`teams` membership with a manager team-role) or who report to
them (`hr.employment_records.reporting_manager_user_id`). The filter is one function,
`fieldops/scope.py::visible_user_ids(actor)`. Flag it as the first consumer when RBAC data scope is
built.

---

## 14. API

All responses use the `{code, msg, data, request_id}` envelope. Lists return `PageModel` of **Slim**
DTOs backed by `load_only()`; details return **Fat** DTOs with explicit `selectinload`s. Public ids are
uuids. Actions are `POST …/{action}` sub-resources: they are transitions, not field edits, and each
carries an idempotency key.

### 14.1 Field app — `/api/me/…` (`fieldops.field_work:use`)

| Route | Notes |
|---|---|
| `POST /me/devices` | register/upsert device + session (on every app launch) |
| `POST /me/device-events` | batch, idempotent by event uuid |
| `GET /me/fieldops/policy` | effective policy + capability flags |
| `GET /me/fieldops/fence-pack?date=` | today's targets for offline verification: planned + recent accounts' places, fences, radii (§14.4) |
| `POST /me/shifts` | start (§7.1) → 201 / 409 `shift_already_active` / 422 `location_required`, `location_consent_required`, `device_not_registered`, `selfie_required`, `odometer_required` |
| `POST /me/shifts/{uuid}/end` | 200 / 409 `visit_in_progress`, `shift_not_active` |
| `POST /me/shifts/{uuid}/pause` · `POST /me/shifts/{uuid}/resume` | 409 `shift_already_paused` / `shift_not_paused` / `visit_in_progress` |
| `GET /me/fieldops/current` | open shift + open pause + in-progress visit (the app's resume call) |
| `GET /me/shifts?date_from=&date_to=` | own history (Slim) |
| `POST /me/visits` | start (§7.4) → 201 / 409 `visit_in_progress`, `shift_paused` / 422 `shift_required`, `justification_required`, `outside_geofence` / 403 channel |
| `POST /me/visits/{uuid}/end` · `/cancel` · `/join` | |
| `GET /me/visits/current` · `GET /me/visits?date=` | |
| `POST /me/visits/{uuid}/tasks` · `POST /me/visit-tasks/{uuid}/void` | registry-validated |
| `POST /me/location-pings` | batch (§6), always 200 with per-item results |
| `PATCH /me/location` · `GET /me/location` | existing routes, moved; one-item shim |

### 14.2 Managers — `/api/fieldops/…`

| Route | Permission | Notes |
|---|---|---|
| `GET /shifts?user=&team=&date_from=&date_to=&status=&review_status=` | `fieldops.shift:read` | Slim; team-filtered (§13) |
| `GET /shifts/{ref}` | `fieldops.shift:read` | Fat: pauses, visits (Slim), metrics, open anomalies |
| `GET /shifts/{ref}/track?simplify_m=10` | `users.location:read` | GeoJSON LineString of accepted fixes (server-side `ST_Simplify` on geometry) + checkpoint markers |
| `PATCH /shifts/{ref}` | `fieldops.shift:update` | correction: `started_at`/`ended_at`, **`reason` required**, `row_version` → 409 on mismatch; review → `corrected` |
| `POST /shifts/{ref}/review` | `fieldops.shift:approve` | `approve / reject` + note |
| `POST /shifts/{ref}/metrics/recompute` · `GET /shifts/{ref}/metrics` | `fieldops.shift:read` / `manage` | |
| `DELETE /shifts/{ref}?reason=` | `fieldops.shift:delete` | soft delete, audited; refused while `active` |
| `GET /visits` · `GET /visits/{ref}` · `PATCH /visits/{ref}` · `POST /visits/{ref}/review` | `fieldops.visit:*` | as shifts |
| `GET /visits/{ref}/checks` | `fieldops.visit:read` | the `location_checks` history |
| `POST /visit-overrides` | `fieldops.visit:approve` | hard-block override token (§8.4) |
| `GET /anomalies?state=&type=&severity=` · `POST /anomalies/{ref}/resolve` | `fieldops.anomaly:read/approve` | |
| `GET /review-queue` | `fieldops.shift:approve` | §11 |
| `GET /live` | `users.location:read` | team-filtered snapshot from `user_live_locations` + on-shift/on-visit state |
| `GET/POST/PATCH/DELETE /policies` | `fieldops.policy:*` | `row_version` on PATCH |
| Geofences | — | existing `/api/geofences` (`geo.geofence:*`) |

### 14.3 Error vocabulary

`409`: `shift_already_active`, `visit_in_progress`, `shift_not_active`, `visit_not_in_progress`,
`shift_paused`, `shift_already_paused`, `shift_not_paused`, `idempotency_key_reused`, `row_version_conflict`.
`422` (`FieldOpsRuleError`): `location_required`, `location_consent_required`, `device_not_registered`,
`shift_required`, `justification_required`, `outside_geofence`, `selfie_required`,
`odometer_required`, `invalid_task_payload`, `task_type_not_allowed_for_channel`, `account_not_found`.
`403`: RBAC. `429`: slowapi. All raised through the existing exception hierarchy
(`ConflictError`, an `AppError` subclass), never a bare `HTTPException`.

### 14.4 The fence pack

`GET /me/fieldops/fence-pack?date=` returns, for the caller's planned visits of the day plus accounts
visited in the last 30 days: `place_uuid`, point, `radius_m` (already scaled by verification), polygon
(simplified GeoJSON), enforcement, `dwell_threshold_s`. It is cached per user per day with an ETag.
The app evaluates offline with the ported `classify`.

---

## 15. Background work

All tasks are thin wrappers in `app/modules/fieldops/tasks.py` → `service.*` via
`app/tasks/_loop.run_async` (never `asyncio.run` / NullPool in new tasks), inside `rbac.context.system_scope`
with a `system:fieldops-*` actor. Queue `default`, except geocoding, which goes to `integrations`
(external HTTP).

| Task | Trigger | Notes |
|---|---|---|
| `fieldops.auto_close_shifts` | beat 5 min | §9, `SKIP LOCKED` |
| `fieldops.link_orphan_pings` | beat 10 min | back-fill `shift_id`/`visit_id` from uuids (partial index `ix_location_pings_unlinked`) |
| `fieldops.compute_shift_metrics` | shift end / correction / debounced late data | §10 |
| `fieldops.detect_shift_anomalies` | after metrics | idempotent via `dedupe_key` |
| `fieldops.detect_visit_dwell` | visit end + 5 min countdown | §8.5 |
| `fieldops.reverse_geocode_checkpoint` | after ingest commit | geocoding service (cache, licence, breaker); **queue `integrations`**; skipped while `GEOCODING_ENABLED=false` |
| `fieldops.mark_missed_visits` | beat, org-local end of day | `planned` → `missed` |
| `fieldops.propose_geotags` | nightly | phase 3 |
| `fieldops.maintenance` | beat daily | as built: app-managed partitions (`partitions.py`: current month + 3 ahead), retention, idempotency purge — pg_partman is NOT used (house doctrine, `zoho/control/retention.py`: the scratch image does not ship it) |
| `fieldops.purge_raw_batches` | nightly | Garage objects past `raw_expires_at` |
| `core.purge_idempotency_keys` | nightly | `expires_at < now()` |
| `fieldops.retention` | nightly | drop partitions past `data_retention_schedules('location_history')`, and purge the DEFAULT partition by `occurred_at` |

---

## 16. Events, analytics, realtime

* **CDC:** add `fieldops.shifts`, `fieldops.visits`, `fieldops.visit_tasks`, `fieldops.shift_metrics`,
  `fieldops.anomalies` and `fieldops.location_pings` to the Debezium `table.include.list` → Kafka →
  ClickHouse. **Partitioned table trap:** the publication must set `publish_via_partition_root = true`,
  or Debezium emits per-partition topics (`…location_pings_p2026_09`) and a new month silently lands
  on a topic nobody consumes. Verify against Debezium 2.7 before enabling; the connector's
  `publication.autocreate.mode` may need to be `filtered` or the publication created by migration.
* **Search:** none initially (no type-ahead need). If added: the standard three steps.
* **Realtime:** after ingest commit, publish `{user_uuid, lat, lng, accuracy, occurred_at, state}` to
  Soketi, private channel `private-org-{org_uuid}-fieldops-live`, throttled to 1 per user per 15 s.
  Channel auth checks `users.location:read` + the team filter. Live-map consumers must treat it as
  best-effort and refetch `GET /api/fieldops/live` on reconnect.
* **Domain events:** none published by application code; CDC is the event source (Kafka doctrine).
  Downstream consumers (e.g. a future incentive engine) subscribe to the CDC topics.

---

## 17. Migrations

Three revisions, chained on the current head (`alembic heads`; random revision ids). Every model is
registered in `alembic/env.py`.

**M1 `fieldops_foundation`**
* `CREATE SCHEMA fieldops`; `core.idempotency_keys`; `work_policies`, `devices`, `device_sessions`,
  `device_events`.
* Register entity types in `core.entity_types`: `shift`, `visit`, `visit_task` (for comments/media/
  documents), `prospect`. `customer` comes with the contacts module.
* Opt `visit` and `shift` into comments (`commentable_entity_types`).
* Ensure a `compliance.data_retention_schedules` row `location_history` exists (180 d, `delete`,
  `auto_purge_enabled = false` until D3 is decided).
* `geo.geofences.visit_enforcement` (nullable + CHECK).

**M2 `fieldops_stream`**
* `fieldops.location_pings` (partitioned, DEFAULT partition, indexes), `fieldops.ping_batches`.
* **Copy** `public.user_location_pings` → `fieldops.location_pings`: `client_ping_id = gen_random_uuid()`
  (legacy rows have none), `device_recorded_at = recorded_at`, `occurred_at = recorded_at`,
  `time_basis = 'wall_clock_corrected'`, `received_at` kept, `kind = 'continuous'`, `provider = COALESCE(location_source,'gps')`.
  A row-count guard fails the migration on mismatch.
* Replace `public.user_location_pings` with a **view** of the same name and columns over the new
  table (D7), dropped one release later.
* `partman.create_parent('fieldops.location_pings', 'recorded_at', '1 month', p_premake => 3)` **only
  when the extension exists** (`SELECT 1 FROM pg_extension WHERE extname='pg_partman'`). The scratch DB
  has none, and the DEFAULT partition keeps the table correct without it. Verify the installed version:
  5.x syntax shown (F-26e).
* `user_live_locations`: no schema change; the recency guard lives in the upsert.

**M3 `fieldops_work`**
* `shifts`, `shift_pauses`, `visits`, `visit_participants`, `visit_tasks`, `location_checks`,
  `state_transitions`, `anomalies`, `shift_metrics`.
* The deferred owner-existence trigger for `visits (account_type, account_id)` and
  `visit_tasks (reference_type, reference_id)`, reusing the registry's `target_schema`/`target_table`
  probe (the `tax.assert_owner_scope` pattern).
* Partial indexes are hand-checked. Autogenerate drops `postgresql_where` on occasion.

Downgrades: M3 and M1 are reversible. M2's downgrade restores `user_location_pings` from the new table
(lossy for new columns), and says so in its docstring.

---

## 18. Mobile client contract (FieldMate / DLP)

* **Ids:** UUIDv7 for every entity, fix, batch, session and event (ULID bytes are acceptable. Send the
  canonical uuid text).
* **Queue:** a local outbox (Drizzle/SQLite), FIFO **per entity**. Mutations on an entity are sent
  before pings that reference it where possible, but the server tolerates either order (F-17).
  Retries use exponential backoff with jitter, and the idempotency key is reused on each retry.
* **Every request:** `X-Device-Session`, `X-Device-Sent-At`, `X-Device-Elapsed-Ms`,
  `X-Device-Boot-Count`; mutations add `X-Idempotency-Key`.
* **Every fix and event:** `device_recorded_at` (`Location.getTime()`), `elapsed_realtime_ms`
  (`getElapsedRealtimeNanos()/1e6`), `boot_count`, `sequence_no`, accuracy fields,
  `is_mock` (`isMock()` on API 31+, else `isFromMockProvider()`; iOS 15+
  `sourceInformation.isSimulatedBySoftware`).
* **Checkpoint fixes:** request a fresh high-accuracy fix at the button press (timeout 20 s) and send
  it in the mutation body. Do **not** also queue it in the stream (a duplicate is harmless: same
  `client_ping_id`).
* **Tracking:** only while a shift is active (purpose limitation: stop the service on shift end).
  Fused provider; `ping_interval_s` moving / `stationary_interval_s` still, gated by activity
  recognition; distance filter `ping_min_distance_m`. Android: foreground service with
  `foregroundServiceType="location"` (mandatory on Android 14+), background location only after the
  Play-policy prominent disclosure, and a guided battery-optimisation exemption. Most killed tracking
  on Indian OEM builds is battery management, so the app records `app_restarted_after_kill`.
* **Batching:** flush every 5 minutes or 200 fixes, whichever comes first, immediately on
  shift/visit transitions, and gzip the body.
* **Consent:** show the DPDP notice and record `location_tracking` consent before the first shift.

---

## 19. Observability

* Loggers: `structlog.get_logger("app.fieldops.<area>")` with areas `ingest`, `shifts`, `visits`,
  `verification`, `metrics`, `autoclose`; a `config/logging/modules/fieldops.yaml` for levels.
  Structured keys only; never coordinates at INFO (personal data), only ids and counts.
* Prometheus (via the backend `/metrics` instrumentator + custom counters/histograms):
  `fieldops_pings_ingested_total{status}`, `fieldops_ingest_batch_seconds`, `fieldops_ping_lag_seconds`
  (received − occurred, which exposes offline delay), `fieldops_autoclose_total{reason}`,
  `fieldops_verification_total{result,enforcement}`, `fieldops_anomalies_open{type}`.
* Grafana: an ingest lag/volume panel; tracking-coverage distribution from ClickHouse.

---

## 20. Tests

| Layer | Tests |
|---|---|
| Pure | `clock.derive_occurred_at` (monotonic, rebooted, missing clocks, future cap, clamp); `verification.classify` (the shared case table); `trackmath` (segmentation, coverage, gaps, impossible speed, distance ignoring jitter); `state` (every allowed/forbidden transition); task-type registry (every type has a model; channel rules); policy resolution order (pure over an in-memory tree) |
| Route smoke | every new path in `app.openapi()["paths"]` (`tests/test_health.py`); `tests/test_rbac_routes.py` passes (Perm + targets) |
| Mocked boundary | Redis first-seen guard (`mocker`); geocoding service (`mocker.patch.object`); Soketi publish; Garage raw archive failure is non-fatal |
| Integration (scratch PG) | start/end shift happy path; **one active shift** (409) and the supersede rule; **one in-progress visit** across shifts (409); cascade on auto-close; ghost shift → 0 min + anomaly; auto-close cap with and without `planned_end_at`; **ping replay is a no-op** (same batch twice, and same items in a new batch); clamped far-future clock goes to DEFAULT and does not break a later partition; orphan pings get linked; live location recency guard (an old replay does not regress it); telephonic without permission → 403, with it → `not_applicable`; enforcement matrix incl. offline bypass; idempotency key reuse with a different body → 409; late task after visit end recorded with `after_visit_end`; metrics field vs telephonic separation; `geofence_compliance_pct` NULL when nothing checkable; migration copy row-count + compat view; tenant isolation (another tenant's shift uuid → 404) |
| N+1 | ingest query count constant for batch sizes 1, 50 and 500; `GET /shifts` list query count constant for 1 vs 50 rows |
| Tenancy | new tables appear in the conformance classes; `_TEST_TABLES` in `tests/conftest.py` extended |

---

## 21. Rollout

| Phase | Scope | Exit criterion |
|---|---|---|
| **P0 Foundations** | M1; policies API; devices/sessions/events; idempotency dependency; `clock.py` | a device registers; a replayed mutation returns the stored response |
| **P1 Shifts + stream** | M2 + shifts/pauses part of M3; batch ingest; `/me/location` shim; auto-close; consent gate; live map | a week of real shifts with coverage and gaps visible; zero duplicate pings under forced replays |
| **P2 Visits + tasks + verification** | visits, tasks, participants, `location_checks`, enforcement (advisory everywhere), fence pack, dwell, checkpoint geocoding | visits verified against fences/places; offline bypass path exercised |
| **P3 Metrics + review** | `shift_metrics`, anomalies, review queue, manager corrections, CDC → ClickHouse, geotag proposals | managers clear the queue daily; geotag coverage rising |
| **P4 Planning** (separate spec) | beat / journey plans (`plan_ref`), missed-visit logic, route optimisation (OR-Tools roadmap), incentives off CDC | — |

Ratchet `geofence_enforcement` per role from `advisory` to `soft_block` once geotag coverage of that
role's accounts passes ~70 % (D4).

---

## 22. Definition of done (per phase)

- [ ] Every table is ENTITY/LEDGER per §2 and passes `tests/test_tenancy.py`; composite tenant FKs on every user/entity reference.
- [ ] Uniqueness on soft-deletable tables is partial; the two "one active" partial uniques exist and are tested.
- [ ] No `metadata` attribute name; client app version is `client_app_version`, never `app_version`.
- [ ] Every relationship declares a loader strategy (`raise_on_sql` default; `selectinload` in detail paths); every list endpoint is Slim + `load_only()`.
- [ ] `state.transition()` is the only status writer; every transition writes `state_transitions`.
- [ ] Ingest query count constant (N+1 test); replay idempotency tested.
- [ ] Logs structured under `app.fieldops.*`, no coordinates at INFO.
- [ ] Permissions added to `rbac/catalogue.py` and templates; `test_rbac_routes.py` green.
- [ ] Celery tasks use `run_async` + `system_scope`; beat entries added in `app/tasks/celery_app.py`; celery-worker/beat restarted after deploy.
- [ ] No new host port, Redis DB index, image or network. The Redis keys are DB 0 with `fieldops:` prefixes. Partitions are managed by the app (no pg_partman, no new GUCs).
- [ ] Docs updated: `docs/geo/README.md` §10–11 (the telemetry layer now exists, and `user_location_pings` has moved), `docs/MODULES.md`, `docs/PROJECT_STRUCTURE.md`, `docs/rbac-module.md` (catalogue), `deployment/config/debezium/zoho-mirror-connector.json` (P3), this spec's status line.
