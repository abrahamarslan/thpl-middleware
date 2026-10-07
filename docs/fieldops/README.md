# Field operations — shifts, pauses, visits, tasks and the location stream

> **2026-10-06 additions** (migrations `b7e4c1a9d3f2`, `c3d9a7e2f415`): `work_policies` was replaced by
> [policy layers](policy-layers.md); shift templates, scheduled shifts, stops, route endpoints and the hub of
> the day: [shift-templates.md](shift-templates.md); the Android wire contract:
> [android-contract.md](android-contract.md); summary: [field-app-integration-as-built.md](field-app-integration-as-built.md).

**Status:** ✅ built (2026-09-29) · **Schema:** `fieldops` (+ `core.idempotency_keys`) ·
**Migration:** `5d8c2e1f7a90` (reversible; takes over `user_location_pings`) ·
**Code:** `app/modules/fieldops/`, `app/modules/idempotency/`, `app/tasks/fieldops.py` ·
**Tests:** `tests/test_fieldops_logic.py` (49, pure), `tests/test_fieldops_api.py` (17, integration),
`tests/test_user_location.py` (legacy contract) · **Design:** [implementation spec](implementation-of-shift-visits-system.md),
[review of the original proposal](improvement-document.md)

This page is the as-built reference. The spec explains why things are the way they are; §9 below
lists where the build deliberately differs from the spec.

---

## 1. The model

```
fieldops.policy_layers ─ merged per setting (organization tree × role/team/hub/user) ─ frozen on each shift
                                     │
fieldops.devices ─ device_sessions ─ device_events            (device binding, capability, tracking health)
                                     │
fieldops.shifts ──┬─ shift_pauses   (a pause = a break, prayer, vehicle breakdown, no network …)
  one OPEN        ├─ shift_metrics  (derived KPIs, recomputable)
  (active|paused) └─ visits ──┬─ visit_participants (joint working)
  per user          one        └─ visit_tasks        (order, payment, sample … registry-validated)
                    in_progress
                    per user
fieldops.location_pings   THE stream: continuous fixes + labelled checkpoints (partitioned monthly)
  └─ user_live_locations  last-known projection (recency-guarded)
fieldops.ping_batches     one row per upload (idempotent batch replays)
fieldops.location_checks  every geofence/location verification (append-only)
fieldops.state_transitions every lifecycle/review transition (append-only)
fieldops.anomalies        the review queue's findings (idempotent detectors)
core.idempotency_keys     stored responses of client-keyed mutations (platform-wide)
```

**Every table has a bigint primary key and a `uuid`.** Entities the app creates (shifts, pauses,
visits, tasks, fixes, batches, sessions, device events) use the **client's UUIDv7** as their
`uuid`, so a replayed create finds the same row. Other tables get a server `uuidv7()`.

**Raw device time is kept everywhere it arrives.** `client_timestamp` (the device wall clock as
reported, untrusted) sits next to `occurred_at` (business time) and `received_at` (server receipt)
on fixes, batches, device events, tasks and transitions; shifts, pauses and visits keep
`start_client_timestamp` / `end_client_timestamp`.

### Shift lifecycle — with pauses

```
scheduled ─start─▶ active ⇄ paused ─end─▶ completed
                     │   └─────auto_close / supersede─▶ auto_closed   (review pending)
                     └─cancel─▶ cancelled
```

* `active` and `paused` are both **open**: `uq_shifts_one_open` allows one per user, so a paused
  worker cannot start a second shift.
* While paused: no visit can start (409 `shift_paused`), and — unless the policy sets
  `track_during_pause` — the app stops tracking (`shift_pauses.tracking_suspended`). A shift cannot
  be paused while a visit is in progress (409 `visit_in_progress`).
* Whether a pause is paid is policy (`work_policies.paid_pause_types`, default rest / meeting /
  training), frozen onto the pause as `is_paid`. `shifts.paid_minutes = wall clock − unpaid pauses`.
* `shifts.paused_since`, `pause_count`, `pause_minutes`, `unpaid_pause_minutes` summarise the
  pauses; the rows are the detail. Ending, auto-closing or superseding a paused shift closes its
  open pause in the same transaction.
* Anomalies: `long_pause` (> `max_pause_minutes`), `too_many_pauses` (> `max_pauses_per_shift`).

## 2. Time

Business time is `occurred_at`, derived by `clock.py` from three clocks:

| basis | when |
|---|---|
| `monotonic` | same boot: `received_at − (sent_elapsed − event_elapsed)` — immune to the user changing the clock |
| `wall_clock_corrected` | `client_timestamp + (received_at − sent_at)` — the device's skew measured at send |
| `device_wall_clock` | a legacy client sent no send-time headers: the raw device time |
| `server_receipt` | no usable device evidence |
| `manager` | a manager's correction |

Never in the future; older than 45 days falls back to receipt. The shift's business day
(`shift_date`) is taken in the **organization's** timezone (`organizations.timezone`, else the
tenant's), never the device's.

## 3. API

Headers the field app sends: `X-Device-Session` (from `POST /me/devices`), `X-Device-Sent-At`,
`X-Device-Elapsed-Ms`, `X-Device-Boot-Count`, and on mutations `X-Idempotency-Key` (optional). All
are optional; weaker evidence only means a weaker `time_basis`.

### Field app — `/api/me/…` (`fieldops.field_work:use`, held by `member`)

| Route | |
|---|---|
| `POST /me/devices` | register installation + session on every launch; `warnings` = what will break tracking |
| `POST /me/device-events` | tracking-health events (GPS off, permission changed, app killed …) |
| `GET /me/fieldops/policy` · `GET /me/fieldops/current` | effective policy + `can_telephonic`; open shift / pause / visit |
| `POST /me/shifts` | start (201; 200 = replay) — a scheduled shift by its uuid, else the template, else ad hoc; consent, location, selfie/odometer, start-place enforcement |
| `GET /me/shifts` · `GET /me/shifts/{uuid}` | cards (plan, endpoints, hub, stop counts; virtual template entries) · detail with stops + fence pack |
| `POST /me/shifts/{uuid}/handover` | move the open shift to this device |
| `POST /me/visits/{uuid}/start` | start a planned stop |
| `GET /me/fieldops/config` | the Android config (policy layers; ETag / 304) |
| `POST /me/shifts/{uuid}/pause` · `/resume` · `/end` | |
| `POST /me/visits` · `GET /me/visits?date=` | start (verification + enforcement) · a business day's visits |
| `POST /me/visits/{uuid}/end` · `/cancel` · `/join` | `join` = joint working (participant) |
| `POST /me/visits/{uuid}/tasks` · `POST /me/visit-tasks/{uuid}/void` | |
| `POST /me/location-pings` | batch ≤ 500, **always 200** with per-item results |
| `PATCH/GET /me/location` (+ `/api/auth/me/location`) | legacy single fix → a one-item batch |

Telephonic / video visits also need `fieldops.telephonic_visit:create` — in **no** template; each
organization grants it to the roles that phone customers.

### Managers — `/api/fieldops/…`

`GET /shifts` · `GET /shifts/{ref}` (pauses, visits, metrics, open anomalies) ·
`GET /shifts/{ref}/track` (`users.location:read`) · `GET /shifts/{ref}/metrics` ·
`POST /shifts/{ref}/metrics/recompute` · `PATCH /shifts/{ref}` (correction: `row_version`,
`reason`) · `POST /shifts/{ref}/review` · `DELETE /shifts/{ref}?reason=` · `GET /visits` ·
`GET /visits/{ref}` (tasks, participants, checks) · `PATCH /visits/{ref}` ·
`POST /visits/{ref}/review` · `POST /visits/{ref}/cancel` · `GET /live` · `GET /anomalies` ·
`POST /anomalies/{ref}/resolve` · `GET /review-queue` · `POST /shifts` · `/shifts/bulk` ·
`PATCH /shifts/{ref}/plan` · `POST /shifts/{ref}/cancel` · `POST /shifts/{ref}/stops` ·
`/shift-templates` · `/policy-settings` · `/policy-layers` · `GET /policies/resolve` · `POST /policies/preview`.

Reads pass two gates: `Perm(...)` (at the row's organization) and `scope.visible` — a team-scoped
manager sees their teams' members and direct reports, not the tenant. Outside the set is a 404.

### Error codes

`409`: `shift_already_active`, `shift_already_paused`, `shift_not_active`, `shift_not_paused`,
`shift_paused`, `visit_in_progress`, `visit_not_in_progress`, `visit_not_cancellable`,
`visit_cancelled`, `uuid_conflict`, `idempotency_key_reused`, `row_version_conflict`,
`invalid_transition`.
`422`: `location_required`, `manual_location_not_allowed`, `location_consent_required`,
`device_not_registered`, `selfie_required`, `selfie_not_found`, `odometer_required`,
`odometer_decreased`, `shift_required`, `visit_target_required`, `place_not_found`,
`account_not_found`, `justification_required`, `outside_geofence`, `invalid_task_payload`,
`task_type_not_allowed_for_channel`, `amount_not_allowed`, `reference_type_not_allowed`,
`reference_type_not_registered`, `late_task_window_passed`, `end_before_start`, `shift_open`.

## 4. Geofencing

`service/verify.py` is the one evaluator; `verification.py` holds the pure rules.

* Target: an active `geo.geofences` row on the visit's place (polygon beats circle) → else the
  place's coordinates with a radius scaled by provenance (`field_verified` = policy radius,
  `geocoded_only` = × `geocoded_radius_factor`) → else `not_configured` (never blocks).
* Evidence: the user's trusted fixes in [t − 120 s, t + 60 s], best accuracy first (mock,
  impossible-hop, duplicate and manual fixes are never evidence).
* Verdict: accuracy-aware — `inside` / `outside` only when the whole accuracy circle clears the
  boundary, else `uncertain`; no usable fix = `no_fix`; remote channels = `not_applicable`.
* Enforcement (`policy.geofence_enforcement`, overridable per fence by
  `geo.geofences.visit_enforcement`): advisory records; soft_block needs a justification;
  hard_block refuses (422) online. **A start that happened offline is never refused** — it is
  accepted and flagged (`hard_block_bypassed_offline`, review pending).
* `detect_dwell` (after a visit ends) sets `geofence_entry_at` / `geofence_exit_at` from runs of
  fixes lasting ≥ the fence's `dwell_threshold_s`; metrics use them when confident.

## 5. Background work (`app/tasks/fieldops.py`, beat in `celery_app.py`)

| Task | Schedule |
|---|---|
| `auto_close_shifts` — close open shifts past their cap; ghost shifts close at 0 min; stuck visits cancelled | 5 min |
| `link_orphan_pings` — fixes that arrived before their shift/visit | 10 min |
| `recompute_stale_metrics` — closed shifts without fresh metrics (lost enqueues, late data) | 15 min |
| `geocode_checkpoints` — address labels for checkpoints (only with `GEOCODING_ENABLED`; `integrations` queue) | 10 min |
| `mark_missed_visits` — planned visits whose window passed | hourly |
| `maintenance` — stream partitions ahead, retention, idempotency-key purge | daily 21:45 UTC |
| `compute_metrics(shift_id)`, `detect_dwell(visit_id)` | enqueued after shift end / visit end |

## 6. Policies

Policy layers — see [policy-layers.md](policy-layers.md). (Until 2026-10-06 this was
`fieldops.work_policies`, one whole row per organization × role.) Frozen on each shift (`policy_snapshot`). Key knobs: `requires_shift`,
`allow_visits_without_shift`, `require_location_consent` (DPDP), `require_start_selfie`,
`require_odometer`, `max_shift_hours`, `auto_close_grace_minutes`, `stale_shift_after_minutes`,
pause rules, tracking cadence, `geofence_enforcement`, radii and accuracy, anomaly thresholds.

## 7. Operations

* **Partitions:** `location_pings_pYYYYMM` for the current month and three ahead, created by the
  migration and then by the daily `maintenance` task (`partitions.py`). pg_partman is not used —
  the same doctrine as `zoho/control/retention.py`. A DEFAULT partition catches anything else.
* **Retention:** `compliance.data_retention_schedules('location_history')` is seeded at 180 days
  with **auto-purge OFF** — deleting location history is a DPDP decision (improvement-document D3).
  Turn it on by setting `auto_purge_enabled`; `maintenance` then drops whole old partitions and
  purges the DEFAULT partition by `occurred_at`.
* **Consent:** a shift needs an active `location_tracking` consent (`compliance.consent_records`)
  unless the policy turns `require_location_consent` off.
* **Deploying:** `alembic upgrade head` (copies `user_location_pings` into the stream, then drops it),
  then restart `celery-worker` and `celery-beat` (they do not hot-reload) so the new tasks and beat
  entries load.
* **CDC:** `public.user_location_pings` was removed from the Debezium connector's include list. The
  field-ops tables are not in it yet — see §9.

## 8. Tests

`tests/test_fieldops_logic.py` — clock, classification (shared case table
`tests/fixtures/fieldops_classify_cases.json`, the spec the mobile port is tested against),
enforcement matrix, track maths, state machines, task registry, policy snapshot.
`tests/test_fieldops_api.py` — lifecycle with pauses and paid time, one open shift, consent,
supersede, visit gates and the one-in-progress rule, soft block + justification, offline hard
block, unmapped places, late tasks, batch idempotency and live-location recency, clock clamping,
the ingest's constant query count, ghost auto-close with cascade, idempotency-key replay, field
vs telephonic metrics, manager scope and cross-tenant 404s, corrections, the legacy endpoint.

## 9. Differences from the spec, and what is not built yet

| Item | As built |
|---|---|
| Breaks | Generalised into **pauses** (`shift_pauses`, shift status `paused`) — a break is a pause type |
| `uuid` | On every table (the spec had none on some ledgers) |
| `client_timestamp` | The spec's `device_recorded_at` is named `client_timestamp`, and is also kept on transitions, tasks, events, batches |
| Time basis | Adds `device_wall_clock` (legacy client, no send headers) |
| Polygon fences | Own accuracy-aware rule (`classify_polygon`: distance to the edge vs accuracy) |
| pg_partman | Not used — app-managed monthly partitions (house doctrine) |
| `user_location_pings` | Dropped after the copy (the spec suggested a compatibility view; no reader outside this change existed) |
| Celery tasks | In `app/tasks/fieldops.py` (house convention), not in the module |
| Visit ↔ account | App-level existence proof through `core.entity_types` (no deferred trigger yet — `customer` is not registered until the contacts module lands) |
| **Not built** | Soketi live push (the live map polls `GET /fieldops/live`); raw batch archive to object storage (`ping_batches` keeps the sha256 and per-item results); manager override tokens for hard blocks; outlet geotag proposals; (the fence pack for Android geofences IS built — `GET /me/shifts/{uuid}`); Debezium/ClickHouse CDC of the field-ops tables (needs `publish_via_partition_root` for the stream — verify with Debezium 2.7 first); beat/journey plans (`plan_ref` is reserved) |
