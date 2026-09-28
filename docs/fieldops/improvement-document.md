# Field operations (shifts · visits · location stream) — design review & improvements

**Status:** 📝 review of the proposed design — **now built** ([as-built reference](README.md)) · **Schema:** `fieldops` ·
**Companion:** [implementation-of-shift-visits-system.md](implementation-of-shift-visits-system.md) — the build spec
that applies every decision below · **Depends on:** [tenancy](../tenancy/README.md),
[location hub](../geo/README.md), [geocoding](../geo/geocoding.md), [RBAC](../rbac-module.md)

This document reviews the pasted design — the idea brief, *Schema v2 (audit-compliant)*, *Schema v3
additions* and `geo_utils.py` — against the code that is already running in `th-middleware`. It
says what to **keep**, what to **change**, and what to **drop because the platform already has it**.
Every finding is numbered (`F-nn`) so the build spec can cite it.

---

## 0. Verdict in one paragraph

The **domain model is right** and most of it survives: one location stream in which checkpoints are
labelled rows; shifts contain visits, visits contain tasks; one active shift and one in-progress visit
per user, enforced by partial unique indexes; auto-close that never invents a 16-hour shift; wall-clock
duration and engaged minutes reported separately; geofencing that is advisory by default; telephonic
visits as a channel; client idempotency keys for offline replay. What does **not** survive is the
physical schema. It was written for a single-tenant database that does not exist here. It duplicates
five things the platform already runs (places, geofences, the geocode cache, the location-history
table, the geo utility module). It has no `tenant_id`/`organization_id` anywhere. And its time model
treats `server_received_at` as the time business events happened, which is wrong for an offline-first
app: a shift started offline at 09:00 and synced at 19:00 would begin at 19:00.

| Area | Keep | Change | Drop (already exists) |
|---|---|---|---|
| Location stream | one stream, checkpoints = labelled rows | time model, partition key, dedupe, context columns, index set | `fieldops.location_pings` as a *second* table — **evolve `user_location_pings`** into it |
| Shifts / visits | entities, state machines, partial uniques | tenancy, NOT NULL status, orthogonal review axis, no JSONB history | `revision_history`, `status_history` JSONB |
| Geofencing | optional, advisory-first, `geofence_entry_at` | evidence-based verification (accuracy-aware, windowed, dwell) | `fieldops.geofences` → **`geo.geofences`** |
| Geocoding | async, never on the write path | checkpoints only, licence-bound cache | `fieldops.geocode_cache` → **`geo.geocode_api_calls`** |
| Places | — | — | v3 `geo.places` / `geo.place_relationships` → **both already live** |
| Notes / photos / signatures | — | — | `visit_notes` → **comments module**; media → **media module**; signatures → **documents** |
| Roles | "some roles need shifts / may phone customers" | policy table + RBAC permission, not columns on `roles` | — |
| `geo_utils.py` | accuracy/ordering lessons | pure classification function only | the module itself → **`geo/distance.py` + geocoding service + PostGIS** |

---

## 1. What already exists and must be reused (duplication findings)

Prime directive 2 of the master prompt: *extend, don't duplicate.* Five pieces of the proposal
re-create running code.

### F-01 · `geo.places` and `geo.place_relationships` already exist (v3 §1–2) — **drop from v3**

`app/modules/geo/model/place.py` is live (migration `4f2f2a8c7898`) and is richer than the v3 table:
the geography point is the only stored coordinate, `latitude`/`longitude`/`geohash8` are GENERATED
columns, there is a 25 m near-duplicate probe, `VerificationMixin` (`unverified / geocoded_only /
field_verified / disputed`), an Indian postal block (landmark, sub-locality, taluka, GST state code),
geocode provenance and `admin_boundary_id`. `geo.place_relationships` is also live, with distance and
bearing computed at write time. The v3 `address_id` (the 25-char `generate_address_id()` string) is
not needed: places are addressed by `uuid`. **Design Rule Zero** (docs/geo/README.md §1) also rules
out v3's intent of "one row per known customer address": a place has no owner. A customer reaches its
place through `geo.place_links (owner_type='customer', link_type='site')`.

### F-02 · `geo.geofences` already exists — **drop `fieldops.geofences`**

`app/modules/geo/model/reference.py::Geofence` has polygon **or** centre + radius, `place_id`
(fence_type `place_radius`), `valid_from/valid_to`, `status`, `DeactivationMixin`, soft delete and,
most importantly, **`dwell_threshold_s`**: the jitter guard that stops a single bouncing fix from
firing an entry. The proposal's table has none of that and adds a second definition of "the zone
around a customer". The only thing it adds that `geo.geofences` lacks is `enforcement`. That belongs
in the field-ops **policy** (F-23), with an optional per-fence override, because enforcement is a
rule about *who* is being checked, not about the shape.

API already live: `GET /api/geofences/containing?latitude=&longitude=` answers "which fences contain
this point" (polygons and circles in one GiST-served query).

### F-03 · `geo.geocode_api_calls` is the geocode cache — **drop `fieldops.geocode_cache`**

`docs/geo/geocoding.md` §5: one table serves as cache, audit trail and spend ledger. Reverse lookups
are already snapped (`ReverseQuery.normalized()`, ~11 m). It is **per tenant on purpose**, because a
request hash contains someone's address. It carries **`expires_at` per provider licence**: Google
permits caching geocode results for 30 days. The proposed cache is global (a cross-tenant leak), has
no expiry (a licence breach for Google results), and snaps to a grid the pasted code and the pasted
prose disagree about (F-19).

### F-04 · `user_location_pings` + `user_live_locations` already exist — **evolve, don't add a second stream**

`app/modules/users/model.py` has both:

* `user_live_locations`: one hot row per user, upserted on every fix, isolated from `users`. This is
  what dispatch and beat planning read.
* `user_location_pings`: append-only, `RANGE (recorded_at)` partitioned, a DEFAULT partition
  (migration `3b7f0ae91c46`, which records *why*: a partitioned parent with no partition rejects
  every INSERT), pg_partman as the operating plan, retention through `compliance.data_retention_schedules`
  (`location_history`).

Writer: `users.service.record_location` via `PATCH /api/me/location`, one fix per request.

Adding `fieldops.location_pings` beside it would give the platform two location histories, and every
consumer (retention, DPDP erasure, analytics, the live map) would need to know which one to read.
**Decision:** `fieldops.location_pings` *becomes* the one history table. It is created in the
`fieldops` schema with the columns in the build spec. `user_location_pings` rows are copied into it
by the migration and the old table is dropped one release later. `PATCH /api/me/location` becomes a
one-item shim over the new batch ingestion. `user_live_locations` stays exactly where it is, as the
last-known-position projection of the stream.

### F-05 · `geo_utils.py` duplicates `geo/distance.py`, the geocoding service and PostGIS — **don't vendor it**

| `geo_utils.py` piece | Already in the platform | Disposition |
|---|---|---|
| `haversine_distance`, `initial_bearing`, units | `app/modules/geo/distance.py` (`haversine`, `distance_m`, `bearing`, `destination`, `bounding_box`, `within`, `Unit`) | reuse |
| `geodesic_distance` via **geopy** | **geopy was rejected** (geocoding.md §9: needs aiohttp, which the repo removed; no Valhalla) | reject |
| `is_within_polygon_geofence` via shapely | PostGIS `ST_Covers` on `geography` in the geofence query; shapely is available (geoalchemy2) for in-memory work | server check in SQL (F-21) |
| `Geocoder` (retry, backoff, in-memory cache) | `app/modules/geo/geocoding/service.py`: cache, retries, fixed-window limiter, Redis circuit breaker, fallback chain, cost ledger, key scrubbing | reuse |
| `generate_address_id` | places use `uuid`; no `address_id` column exists | reject |
| `Coordinates` value object | WKT ↔ lat/lng conversion happens once at the schema boundary (`users/crud.point`, geo service) | reject; keep the convention |

The file's stated reason for existing is a real bug: two PHP code paths disagree about what "inside"
means. That bug lives in the **legacy PHP service layer**, not in this platform. The fix here is
structural rather than a utility file. The build spec has exactly **one** evaluator,
`app/modules/fieldops/verification.py`, which runs one PostGIS query and one pure classification
function. It is the only code that writes a location-check result.

Two ideas from the file are worth keeping, and both are kept: *longitude first in every geometry
constructor*, and *reject NaN explicitly* (`nan < -90` is False). The Pydantic schemas carry
`Field(ge=…, le=…, allow_inf_nan=False)`.

### F-06 · Notes, photos, signatures, status history — **existing modules cover them**

| v3 table | Platform module | Why reuse |
|---|---|---|
| `visit_notes` (multi-entry stream, visibility) | **comments** (`HasCommentsMixin`, `core.entity_types` registry, ownership RBAC, moderate routes) | it *is* a polymorphic note stream; register entity type `visit` |
| `visit_feedback` (rating, comments) | a `visit_tasks` row, `task_type='customer_feedback'` | feedback is something done during a visit; it gets the task's idempotency, timing and payload validation for free |
| media: product photos, verification photos, shift selfie, odometer photo | **media** (`HasMediaMixin`, per-collection conversion policy, Garage) | one image pipeline |
| signatures, proof documents | **documents** (`HasDocumentsMixin`, `document_links`) | one document store |
| `visit_status_history` | `fieldops.state_transitions` (one ledger for shifts **and** visits) | same shape twice is two tables to keep in sync |
| `visit_verifications` | `fieldops.reviews` is folded into `state_transitions` + review columns | a review decision *is* a transition of the review axis (F-13) |

---

## 2. Tenancy and conventions

### F-07 · No `tenant_id` / `organization_id` on any table — **blocking**

Every table in this platform is ENTITY, LEDGER or an *explained* GLOBAL, enforced by the conformance
test in `tests/test_tenancy.py`. Field operations are always owned by a branch, so every `fieldops`
table uses the strict scope (`MultiTenantMixin` / `OrgEntityMixin`: `organization_id NOT NULL`,
composite FK `(tenant_id, organization_id) → organizations(tenant_id, id)`). The session events in
`app/database/tenancy.py` then filter every ORM read by tenant and stamp tenant, organization,
`created_by(_name)` and the server `app_version` on write.

### F-08 · FKs to `users(id)` must be tenant-safe

`users` exposes `uq_users_tenant_id (tenant_id, id)` precisely as the target of children's composite
FKs. `shifts.user_id`, `visits.user_id` and the rest use `(tenant_id, user_id) → users(tenant_id, id)`,
so a shift can never belong to another tenant's user.

### F-09 · Column naming follows the mixins, not the paste

`created_by_id` → `created_by`, `updated_by_id` → `updated_by`, `deleted_by_id` → `deleted_by`, plus
`deleted_reason` (`SoftDeleteMixin`). The same mapping was applied to the tax paste (a ledger of it
lives in `tests/test_tax_schema.py`). The machine-actor convention the proposal recommends
(`system:<worker>`) **is already the platform rule** (`AuditMixin` docstring: `created_by` NULL,
`created_by_name` e.g. `system:zoho-sync`). Adopt it as-is: `system:fieldops-autoclose`,
`system:fieldops-metrics`, `system:fieldops-verifier`.

### F-10 · Triggers that duplicate the ORM — **drop `set_updated_at` and `bump_row_version`**

`TimestampMixin` already sets `updated_at` via `onupdate=func.now()`. `RowVersionMixin` already makes
every ORM UPDATE `… WHERE row_version = :seen` and increments it (`version_id_col`); Core updates bump
it explicitly (documented in the mixin). A trigger that *also* bumps `row_version` creates a second
source of truth. Today it happens to compute the same value, which is exactly the kind of coincidence
that breaks silently the day someone writes a Core UPDATE that bumps it too.

### F-11 · `status` nullable ("PD-1: NULL == unspecified") — **make it NOT NULL**

"Nullable by doctrine" (prime directive 3) is for **Zoho mirror** business columns that must survive a
thin payload. Shifts and visits are app-owned state machines. A NULL status is a row that is neither
active nor closed: the partial unique index `WHERE status = 'active'` ignores it, the auto-close job
never selects it, and a report `GROUP BY status` grows a mystery bucket. Status is NOT NULL with a
CHECK, and every write goes through the state-machine function.

---

## 3. Time: the most important correction

### F-12 · `server_received_at` is not when things happened — **adopt a three-clock model**

The brief says *"business logic (ordering, duration) uses server time"*. For an app whose whole premise
is working offline in rural Gujarat, that is wrong in the common case. A rep with no signal starts the
shift at 09:02, visits six chemists and syncs at 18:40 from the distributor's Wi-Fi. By server receipt
time all of that happened in one second at 18:40. The brief is right that the device *wall clock* is
untrustworthy, since users change it and it drifts. The answer is to *correct* it, not to discard it:

| Clock | Source | Trust |
|---|---|---|
| `device_recorded_at` | the fix/event's wall-clock time on the device (`Location.getTime()` for fixes) | untrusted: user-settable, drifts |
| `elapsed_realtime_ms` + `boot_count` | Android `SystemClock.elapsedRealtime()` / `Location.getElapsedRealtimeNanos()`; iOS `ProcessInfo.systemUptime` | **monotonic, not user-settable**, resets on reboot |
| `received_at` | server `now()` at ingest | authoritative, but it is *receipt* time |

Every batch and every mutating request carries headers giving the device's clocks **at send time**
(`X-Device-Sent-At`, `X-Device-Elapsed-Ms`, `X-Device-Boot-Count`). The server then derives one
`occurred_at` per row, choosing the best evidence available:

1. **monotonic** (same `boot_count`): `occurred_at = received_at − (sent_elapsed − event_elapsed)`.
   This is immune to the user changing the wall clock and is the normal case.
2. **wall-clock corrected** (rebooted since the event): `occurred_at = device_recorded_at + (received_at − sent_at)`.
   This is the Segment/analytics-SDK `originalTimestamp` correction.
3. **server receipt**: when neither is usable.

The derivation is capped at `received_at` (nothing happened in the future), stored with
`time_basis ∈ {monotonic, wall_clock_corrected, server_receipt}` and `clock_skew_ms`, and flagged when
|skew| exceeds the policy threshold. **All business logic** (ordering, durations, auto-close
`effective_end`, KPI windows, `shift_date`) uses `occurred_at`. `received_at` remains the audit fact
of when the server learned it. One pure function (`fieldops/clock.py`) computes this for pings **and**
for shift/visit/task events, so the two can never disagree.

Also note: for GPS-provider fixes, `Location.getTime()` is usually satellite-derived UTC and survives a
user changing the phone's clock. Fused/network fixes do not guarantee this, so it is a
cross-check signal (`fix_time` vs device clock → `clock_tampered` flag), not a replacement for the
monotonic path.

### F-13 · Partition key and dedupe cannot both be `server_received_at`

Schema v2 keys the table `PRIMARY KEY (id, server_received_at)` and partitions on `server_received_at`,
with a **non-unique** `(user_id, sync_client_id)` index. A replayed batch gets a new
`server_received_at`, so it may land in a different partition. A unique index on a partitioned table
must include the partition key, so there is no index that can reject the duplicate. Offline replay,
the one thing idempotency exists for, would double-count every ping.

**Decision** (matching what `user_location_pings` already does): partition on **`recorded_at`, the
device fix time as reported**. It is stable across replays because the device stores it, so
`UNIQUE (tenant_id, user_id, client_ping_id, recorded_at)` makes a replay a no-op
(`ON CONFLICT DO NOTHING`). Two guards handle absurd device clocks:

* the partition key is **clamped** to `[received_at − 45 days, received_at + 10 min]`, and the raw value
  is kept in `device_recorded_at`. This matters because pg_partman cannot create next month's
  partition while the DEFAULT partition holds rows that belong in it ("updated partition constraint
  for default partition would be violated"). One phone set to 2027 would otherwise break partition
  maintenance for everyone;
* a clamped row's key is no longer stable across replays, so those (rare, already-flagged) rows also
  pass a Redis first-seen guard (`SET NX fieldops:ping:{tenant}:{client_ping_id}`, DB 0, TTL 45 d).

### F-14 · `shift_date` from a hard-coded IST offset → the organization's timezone

`org_management.organizations.timezone` exists ("Operational IANA timezone, overriding the tenant
default"). `shift_date = (started_occurred_at AT TIME ZONE org_tz)::date`, frozen at shift start. The
brief's instinct (*never the device's reported timezone*) is right and is kept. Using the
organization's timezone instead of a constant costs nothing for THPL (`Asia/Kolkata`) and keeps the
second tenant from inheriting India's payroll day.

### F-15 · `started_at DEFAULT now()` on visits

Same class of bug as F-12: a visit synced late starts when it syncs. `started_at` is the corrected
`occurred_at` of the start action and is always supplied by the service, never defaulted by the
database.

---

## 4. The location stream

### F-16 · Owner columns: neither polymorphic pair nor exclusive arc — **two nullable context columns**

The brief proposes `pingable_type/pingable_id`. v2 switched to an exclusive arc,
`CHECK (num_nonnulls(shift_id, visit_id) = 1)`. Both are wrong for this data:

* **Contexts nest.** A fix taken during a visit is also a fix during the shift. The exclusive arc
  forces a choice, and then "all fixes of shift S" must union visit-owned rows back in through a join
  on `visits`.
* **The brief itself wants pre-shift pings** (id NULL). `num_nonnulls(...) = 1` forbids them. The v2
  DDL contradicts the brief it implements.
* A polymorphic pair has no FK at all and forces a type discriminator into every query.

**Decision:** `shift_id` and `visit_id`, both nullable, set **independently** (a visit fix carries
both). Checkpoint labels are constrained to the context they need
(`visit_start` ⇒ `visit_id IS NOT NULL`, `shift_start` ⇒ `shift_id IS NOT NULL`).

### F-17 · No hard FKs from the partitioned stream to `shifts`/`visits`

Offline queues do not guarantee that a shift-start request reaches the server before the pings
recorded after it. The device queue is FIFO per endpoint, but a batch upload can race a retrying
mutation. Pings therefore carry the **client UUIDs** of their context (`shift_uuid`, `visit_uuid`).
The ingest resolves them to ids in one lookup per batch, and leaves an unresolved context NULL with
the uuid kept. A sweep (`link_orphan_pings`, every 10 min) back-fills ids once the entity arrives.
The resolved `shift_id`/`visit_id` columns are plain BIGINTs with no FK constraint. Retention also
drops whole partitions, and FKs from a partitioned child only get in the way of that.

### F-18 · Index set: seven indexes on a stream is write amplification

v2 declares per-partition: GiST on location, BRIN, three btrees on context, a checkpoint index and the
sync index. The stream is written far more than it is read, and most reads are "one user's fixes in a
time window". The spec keeps **four**:

| Index | Serves |
|---|---|
| `UNIQUE (tenant_id, user_id, client_ping_id, recorded_at)` | idempotency (it doubles as the per-user time index when the leading columns match) |
| `(tenant_id, user_id, occurred_at DESC)` | track replay, auto-close `effective_end`, metrics |
| `(shift_id, occurred_at) WHERE shift_id IS NOT NULL` | shift track, metrics |
| `(tenant_id, occurred_at) WHERE kind = 'checkpoint'` | review queue, checkpoint geocoding |

**No GiST on the stream.** "Which pings fell inside fence F" is always asked within one user's time
window (verification, dwell detection), and the btree on `(tenant_id, user_id, occurred_at)` narrows
it to a few hundred rows before `ST_Covers` runs. A spatial index over hundreds of millions of points
that no query uses spatially first is pure write cost. Revisit only if a "who was near X" query appears
(heat-maps, audits); ClickHouse is the better home for that anyway.

### F-19 · Reverse-geocode checkpoints, not the stream; store a snapshot, not a permanent copy

The brief grid-snaps to ~50 m cells. `geo_utils._grid_snap(precision=5)` is ~1 m. The repo's
`ReverseQuery.normalized()` is ~11 m. Three answers to one question. More importantly, reverse
geocoding **every continuous ping** is unnecessary: nobody reads the street address of a fix taken
while riding between villages. **Only checkpoint rows are reverse-geocoded**, through the existing
geocoding service (which owns snapping, cache, licence expiry and cost). The checkpoint row keeps
`geocode_call_id` (provenance) and `address_label` (a display snapshot). `formatted_address` is not
copied onto every ping. That copy would also outlive Google's 30-day caching window, which
`geo.geocode_api_calls` exists to enforce (F-03).

### F-20 · Raw payload: at the batch level, not per ping

Enterprises keep the raw upload for dispute resolution ("the app says I was there"). Storing raw JSON
on each ping row roughly doubles a hot table for data that is read perhaps once a year. The spec adds
**`fieldops.ping_batches`** (LEDGER): one row per upload with the envelope (device clocks, session,
counts accepted / duplicate / rejected, per-item reject reasons, `payload_sha256`). The gzip'd raw body
goes to object storage (Garage, private bucket) under a retention window, referenced by key. Per-ping
vendor extras that have no column go into a sparse `extras` JSONB, NULL in the normal case.

### F-21 · Geometry: follow `geo.places` — geography stored, lat/lng generated

v2 stores `lat`/`lng` NUMERIC and derives `location` by trigger on INSERT **or UPDATE** (on an
"append-only" table). The platform pattern (`geo.places`) is the inverse and removes the drift risk:
`coordinates geography(Point,4326)` is written, and `latitude`/`longitude` are `GENERATED ALWAYS AS
(ST_Y/ST_X(coordinates::geometry)) STORED`. That means no trigger, no second source of truth, and one
place (the ingest mapper) that builds points, longitude first.

---

## 5. Shifts and visits

### F-22 · Lifecycle and review are two axes, not one status

v3 adds `pending_approval` and `rejected` to `visits.status`. A visit that was *completed* and is then
*rejected by a manager* has not stopped being completed: the rep was there and the order exists.
Merging the axes makes `status = 'completed'` mean "completed and not under review". Every KPI query
then has to know about the approval workflow, and the partial unique index on `in_progress` gets
states it must not care about. **Decision:**

```
status        (lifecycle)  shifts: scheduled → active → completed | auto_closed | cancelled
                           visits: planned → in_progress → completed | cancelled   (+ missed for planned)
review_status (review)     not_required → pending → approved | rejected | corrected
```

Anything the system estimates (auto-close, offline-bypassed hard block, mock location, big gap) sets
`review_status = 'pending'` and opens an **anomaly** (F-27). This replaces v2's single `requires_review`
boolean, which could not express "reviewed and rejected".

### F-23 · `requires_shift` on the role, telephonic "for certain roles" → a policy table plus one permission

Two different kinds of rule are in play, and the platform already has a home for one of them:

* **What a user MAY do** is a permission. It is additive, unioned across the base role, contextual
  grants and team memberships (docs/rbac-module.md). "May take telephonic visits" is exactly that:
  `fieldops.telephonic_visit:create` in `rbac/catalogue.py`, granted per organization to the roles
  that should have it (e.g. an org's `sales_rep` role). This is **already per organization and per
  role** with no new mechanism.
* **What a user MUST do** is an obligation: must run a shift, must be tracked, must be inside the fence.
  Obligations do not compose by union. If a user holds a contextual grant of a second role, "requires
  shift" must not silently switch on or off. A boolean on `roles` would also put a field-ops column on
  a tenancy-core table (`.importlinter`: tenancy core must not know feature modules).

**Decision:** `fieldops.work_policies`, org-scoped rows that target a role (or `NULL` for the org
default) and are resolved by the user's **base role in their home organization**, walking up the
organization tree. Columns: `requires_shift`, `tracking_mode`, ping cadence, `geofence_enforcement`,
radii, accuracy threshold, max shift hours, auto-close grace, selfie/odometer requirements, whether
visits outside a shift are allowed. The hierarchical settings module cannot hold this. Its contexts
are `global / tenant / user`, with no organization and no role, and these rules are structured, not
key/value.

### F-24 · JSONB `revision_history` on shifts repeats the anti-pattern v3 criticises

v3 correctly pulls `visits.status_history` out of JSONB (a read-modify-write that loses concurrent
updates and bloats the hot row via TOAST), yet v2 keeps `revision_history jsonb` on **shifts** and
**visits**. Both go. Transitions go to `fieldops.state_transitions`; manager corrections are
transitions with a `corrections` diff; business audit goes to `activity.recorder.record_activity`, as
everywhere else.

### F-25 · Visit ↔ customer: `customers(id)` does not exist yet

No `customers` table exists (Zoho contacts are Phase 6, on hold by user decision). Visits therefore
reference their counterparty through the **shared entity registry**, the same primitive `tax_assignments`,
`entity_aliases`, custom fields and comments use: `account_type → core.entity_types.code` plus
`account_id`. Register `customer` when the contacts module lands, and `prospect` for new-outlet visits.
The *where* of the visit is always `place_id → geo.places`, which exists today. A prospecting visit
may have a place and no account. As with tax assignments (not comments), visits are business records,
so the deferred owner-existence trigger is used.

### F-26 · Smaller correctness defects in the pasted DDL

| # | Defect | Fix |
|---|---|---|
| a | `ck_visits_telephonic_no_geofence` allows `not_configured` for telephonic | telephonic ⇒ `not_applicable` only |
| b | `visits.estimate_id`, `order_placed` | an order is a `visit_task` referencing the order module; `outcome` replaces the boolean |
| c | `uq_visit_tasks_idempotency (visit_id, idempotency_key)` | idempotency is per **user** (and platform-wide, F-29); `visit_tasks.uuid` = client UUID is the natural key |
| d | `GIN (payload jsonb_path_ops)` on tasks | nothing queries into payload generically; typed columns (`reference_type/id`, `amount`) cover it |
| e | `partman.create_parent(p_interval => 'monthly')` | pg_partman **5.x** (the image installs `postgresql-18-partman`) takes `'1 month'`; `'monthly'` was 4.x syntax. Verify the version before writing the migration |
| f | DPDP erasure "redacts `lat` to NULL" on an append-only table | erasure = retention partition drop + an anonymising UPDATE on the (few) rows inside the window, recorded in `kyc_audit_logs`; the table is append-only *for the application*, not for the compliance job |
| g | `created_by_name` on every ping | the stream carries `user_id`; the actor label is redundant on 10⁸ rows (pings are LEDGER rows, no `AuditMixin`) |
| h | `ix_location_pings_checkpoint (visit_id, checkpoint_label)` | shift checkpoints are never indexed; replaced (F-18) |
| i | `shift_metrics.currency DEFAULT 'INR'`, single `total_order_value` | amounts come from the order/payment modules in their own currency; metrics hold `order_value_base` in the organization's base currency (currency module) |
| j | auto-close cap `planned_end_at + grace` when `planned_end_at` is NULL (ad-hoc shifts) | cap = `COALESCE(planned_end_at, started_at + policy.max_shift_hours) + grace` |
| k | `ended_by ∈ (user, system)` | add `manager` (a correction is neither) |
| l | `duration_basis ∈ (wall_clock, system_estimated)` | `device_reported / system_estimated / manager_adjusted` |
| m | `user_live_locations` upsert has no recency guard | an offline replay regresses the live position to yesterday; the upsert writes the corrected time into `recorded_at` and becomes `… DO UPDATE … WHERE excluded.recorded_at > user_live_locations.recorded_at` |
| n | 202 for "partially accepted" | 202 means *not yet processed*. Ingest is synchronous, so answer **200 with a per-item result array, always** (the client handles one shape); keep 202 for a future async lane |
| o | "single active session at the auth layer" | sessions are stateless JWT + Authentik; see F-30 |

---

## 6. Geofencing: the better approach you asked for

The brief's rule (one `ST_DWithin` of the latest ping at button press → `inside/outside`) has three
failure modes that field teams run into in the first week:

1. **Accuracy is ignored.** A fix 90 m from the shop with ±150 m accuracy is *not* evidence of being
   outside, and one 40 m away with ±200 m accuracy is not evidence of being inside. Indoors (a
   chemist's shop with a steel shutter) accuracy of 50–300 m is normal.
2. **One sample.** "The latest ping" may be minutes old (tracking interval), or a cold-start fix taken
   before the GNSS converged.
3. **Binary output.** Everything uncertain gets forced into `outside`, reps learn the check is noise,
   and managers learn to ignore it.

### 6.1 Evidence-based verification

```
evidence   = the checkpoint fix taken AT the press (client requests a fresh high-accuracy fix,
             ≤ 20 s timeout) + every stream fix in [press − 120 s, press + 60 s]
best fix   = min accuracy_m among evidence, excluding is_mock and flagged fixes
target     = geo.geofences for the visit place (polygon > circle)
             → else place.coordinates + policy radius (scaled by place verification, below)
             → else: not_configured (never blocks)
d          = ST_Distance(target, best_fix) on geography (0 when a polygon covers the point)
classify(d, r, accuracy):
     d + accuracy ≤ r        → inside            (confident)
     d − accuracy > r        → outside           (confident)
     otherwise               → uncertain
     no usable fix           → no_fix
     channel ≠ field         → not_applicable
```

`classify` is a **pure function** with table-driven tests: the one piece of `geo_utils.py`'s
ambition worth keeping. Everything spatial is one PostGIS query. The result, the distance, the fix
used, its accuracy, the method (`polygon / circle / place_default`) and the fence id go to
`fieldops.location_checks`, an append-only ledger, so re-running verification after a fence is
redrawn adds a row rather than rewriting history. The visit keeps only the denormalised headline
(`start_check`, `end_check`, `distance_from_target_m`).

### 6.2 Radius from what we know about the place

A place's coordinates are only as good as their provenance (`VerificationMixin`):

| `places.verification_status` | radius used when no fence exists |
|---|---|
| `field_verified` | `policy.default_visit_radius_m` (e.g. 100 m) |
| `geocoded_only` | × `policy.geocoded_radius_factor` (e.g. 2.5 → 250 m): a geocoder's rooftop guess in a Gujarat village is often a street off |
| `unverified` / no coordinates | `not_configured` (never blocks) |
| `disputed` | `not_configured` + an anomaly: a disputed point must not judge anyone |

### 6.3 Enforcement that respects offline

| `geofence_enforcement` | `inside` | `uncertain` / `no_fix` | `outside` |
|---|---|---|---|
| `advisory` (start here) | record | record | record + anomaly |
| `soft_block` | record | record | **justification required** (reason code + note, optional photo); visit starts, `review_status = pending` |
| `hard_block` | record | treated as soft | **422 `outside_geofence`** online; manager override token accepted |

**Offline caveat, stated plainly.** A device with no signal cannot ask the server. The app therefore
downloads today's fences (planned accounts + recent visits) and evaluates locally with the same
`classify` rules. When the server re-evaluates on sync and a `hard_block` visit comes back `outside`,
**the visit is still accepted**, because the server cannot reject something that already happened. It
is flagged `hard_block_bypassed_offline` for review. Rejecting it would lose the order that was taken.

### 6.4 `geofence_entry_at` / `geofence_exit_at` from dwell, not a single fix

After a visit ends (and again when late pings arrive), `detect_dwell` scans the user's fixes from
`started_at − 15 min` to `ended_at + 15 min`. It finds the first run of fixes inside the target that
lasts at least `geo.geofences.dwell_threshold_s` (the column already exists for exactly this), and the
last fix before a run outside of the same length. KPIs use `geofence_entry_at … geofence_exit_at` when
both exist with `confidence ≥ medium`, and fall back to button presses otherwise. `visit_time_basis`
on the visit records which pair was used, so no KPI silently mixes the two.

### 6.5 Closing the loop: outlet geotagging

Most customers have no coordinates at onboarding (the brief says as much), and a fence nobody draws
never helps. Enterprises close this with **learned geotags**: when a place has no coordinates, or is
`geocoded_only`, and at least 3 field visits by at least 2 distinct users produced `best_fix.accuracy
≤ 30 m` fixes clustering within 50 m, the verifier opens a `place_geotag_proposal` anomaly carrying the
cluster centroid. A manager accepts it → `geo` service sets `places.coordinates` and
`mark_verified(method='field_visit')`. Coverage then ratchets up from real visits, which is the
precondition the brief set for moving from `advisory` toward `soft_block`.

### 6.6 Anti-spoofing signals (surface, don't block)

`is_mock` (Android `Location.isMock()` API 31+, `isFromMockProvider()` before; iOS 15+
`CLLocationSourceInformation.isSimulatedBySoftware`), impossible speed between consecutive fixes
(> 250 km/h implied), identical coordinates across many fixes (replay), accuracy suspiciously constant,
Play Integrity / App Attest verdict, developer options on, "automatic date & time" off. Each becomes a
quality flag on the fix and, above a threshold per shift, an anomaly. None blocks by default, because
mock detection false-positives on some OEM builds (the brief's reasoning, kept).

---

## 7. Offline sync and idempotency

### F-27 · Anomalies deserve a table, not a JSONB array on metrics

`shift_metrics.anomaly_flags jsonb` cannot be acted on: a manager reviews, accepts or rejects **each**
anomaly, and the review queue needs to filter by type, severity and state. **`fieldops.anomalies`**:
subject (shift/visit/place/device), type, severity, detected_at, evidence, state (`open / acknowledged
/ resolved / dismissed`), resolver, resolution note. The review queue is
`anomalies WHERE state = 'open'` ∪ `shifts/visits WHERE review_status = 'pending'`.

### F-28 · Client-generated ids are the first idempotency guarantee

The strongest idempotency is structural. The device generates the entity's **UUIDv7** (time-ordered,
native Postgres `uuid`; a ULID is the same 128 bits and converts losslessly if FieldMate keeps `ulidx`)
and sends it as the entity's `uuid`. `uq_*_uuid` makes a replayed *create* hit the same row, even
across the rolling window and even when the key ledger has been purged. `BigIntPKWithUUIDv7Mixin`'s
server default only fires when no uuid is supplied.

### F-29 · A platform-level key ledger for everything else

State transitions (end shift, end visit, submit task) are not creates. They need
**`core.idempotency_keys`** (LEDGER, platform-wide because DLP proof-of-delivery needs the same
thing): `(tenant_id, user_id, key)` unique, `request_fingerprint` (method + route + body sha256), the
**stored response** (status + body), `state (in_flight / completed)`, `expires_at`. A replay with the
same fingerprint returns the stored response byte-for-byte. The same key with a different body is a
`409 idempotency_key_reused`. Window: 30 days (rural devices do stay offline for days), purged by the
existing maintenance lane. It is implemented once as a FastAPI dependency (`Idempotent()`), not
re-coded per route.

### F-30 · "Two devices, one account" → device binding, not auth sessions

Sessions are stateless JWTs issued by Authentik or first-party. "Single active session" at the auth
layer is an Authentik policy change with platform-wide blast radius. Field ops only needs one narrower
guarantee: **a shift belongs to one device**. `fieldops.devices` registers each installation (an
app-generated installation id, never IMEI, which Android 10+ withholds anyway). A shift is bound to the
device that started it. Pings and mutations for that shift from another device are accepted, flagged
`foreign_device`, and raise an anomaly. A second shift start from another device hits the one-active
index → 409 with the active shift's device in `data`, so the app can offer "end it there first".

### F-31 · 409 on offline replay needs a rule, not just an error

A 409 is fine for an online tap: the app shows "you already have an active shift". For an **offline
replay** the client cannot fix anything, and an unresolvable 409 leaves its queue stuck. Rule: when the
incoming start has `occurred_at` **later** than the active shift's last activity + `policy.stale_after`
and comes from the **same device**, the stale shift is auto-closed (`end_reason = superseded`,
`review_status = pending`) and the new one starts. Otherwise 409 with the conflicting entity in `data`.

---

## 8. What enterprises capture that the proposal does not

Compared with Salesforce Maps / Consumer Goods Cloud (visits, planned vs actual, in-store location),
Dynamics 365 Field Service (bookings, geofence events), SAP Sales Cloud (check-in/out with coordinates,
visit routes), Veeva CRM (call reports, attendees, samples, product detailing) and the Indian
field-force platforms (FieldAssist, Bizom: day start/end with selfie, beat plans, outlet geotagging,
odometer-based travel allowance):

| Capability | Captured where (build spec) | Phase |
|---|---|---|
| Device inventory: model, OS, app build, installation id, push token | `fieldops.devices` | 1 |
| Per-session snapshot: app version, **location permission level** (precise/approximate, always/while-in-use), battery-optimisation exemption, power-save, auto-time on, developer options, integrity verdict | `fieldops.device_sessions` | 1 |
| Tracking-health events: GPS off, permission revoked, airplane mode, battery saver on, time changed, app restarted after kill, mock app detected | `fieldops.device_events` | 1 |
| **Tracking coverage %** (shift minutes with a fix within the expected interval) and longest gap | `shift_metrics` | 3 |
| Breaks (lunch), paid vs unpaid time | `fieldops.shift_breaks` | 1 |
| Attendance selfie at shift start (policy) | media collection `shift_selfie` | 1 |
| Vehicle, travel mode, odometer start/end (+photo) for travel allowance | `shifts.vehicle_id → fleet.vehicles`, odometer columns | 2 |
| GPS distance travelled (optionally Valhalla map-matched) | `shift_metrics.gps_distance_km` | 3 |
| Planned vs unplanned visits, sequence, "missed" planned visits | `visits.plan_ref`, `status = missed` | 2 (beat plans later) |
| Visit outcome / no-order reason (closed shop, owner absent, stock sufficient, …) | `visits.outcome`, `no_order_reason` | 2 |
| Joint working (manager accompanies rep) | `fieldops.visit_participants` | 3 |
| Product detailing, **sample distribution** with batch + quantity (pharma: sample records are a UCPMP compliance topic; confirm the current code with THPL compliance) | `visit_tasks` types `product_detailing`, `distribute_sample` | 2 |
| Telephonic evidence | click-to-call through the app records dial/end times. **Reading the call log needs `READ_CALL_LOG`, which Google Play restricts to default dialer apps**, so do not plan on it. A telephony provider (virtual number) integration is the enterprise-grade path | 2 / later |
| DPDP: consent for location tracking before first shift; tracking **only while on shift** (purpose limitation); retention by category | `compliance.consent_records (location_tracking)`, `data_retention_schedules (location_history)` | 1 |
| Android 14 foreground-service type `location`; Play "prominent disclosure" for background location | client requirement, noted in the spec | 1 |

---

## 9. Decisions this review needs from you

| # | Question | Default the spec assumes |
|---|---|---|
| D1 | Visits need an account. Phase 6 (contacts/customers) is on hold. Ship visits against `place` + `prospect` first, or unhold contacts? | ship against places; register `customer` when contacts land |
| D2 | Ping cadence and tracking mode per role (continuous vs checkpoints-only)? | reps: continuous 60 s / 50 m while moving; delivery agents: continuous 30 s |
| D3 | `location_history` retention days (`data_retention_schedules`) | 180 days raw fixes; metrics and checkpoints kept with the shift |
| D4 | Start at `advisory` everywhere? | yes; ratchet per role once geotag coverage reaches ~70 % |
| D5 | Where do orders / payments / returns live (targets of `visit_tasks.reference_*`)? | Zoho-bound modules to come (sales orders, customer payments); `reference_type` uses `core.entity_types` |
| D6 | Is a shift selfie required, and is face-match in scope? | selfie optional per policy; no face-match |
| D7 | Drop `user_location_pings` after the copy, or keep a compatibility view for one release? | **decided in the build: dropped** — no reader outside the change existed; the Debezium include list was updated |
| D8 | Should managers see only their team's tracks? RBAC data scope is **not built** (reads are tenant-wide) | build `fieldops` reads with an explicit team filter derived from `teams` membership (interim), flagged as the first consumer of data scope |
