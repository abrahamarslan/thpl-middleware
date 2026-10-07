# Field app integration plan — telemetry contract, org-scoped client config, scheduled shifts, sessions, privacy settings

**Status:** 📝 plan (2026-10-06) · **Builds on:** [`README.md`](README.md) (fieldops as built, migration `5d8c2e1f7a90`),
[`docs/geo/README.md`](../geo/README.md), [`docs/rbac-module.md`](../rbac-module.md) · **Inputs reviewed:** the Android
"Shift Tracking for Delivery Agents" guide, its `LocationConfig` JSON (v4), the ping payload examples, the Room-entity
request the app sends today, the Privacy screen, and the Android developer's questions about multi-device login,
`/api/me/shifts`, and `profile_visibility`.

---

## 0. Summary

| Question | Answer |
|---|---|
| Is the mobile document a better **server** design than what we have? | **No.** It is a good **Android client** design (FGS, adaptive interval, Room queue, one-shot proof capture), and we should adopt it on the client. On the server, `fieldops` is already stronger: idempotent partitioned stream, monotonic-clock business time, server-computed quality flags, policy resolution through the organization tree, frozen per-shift policy, geofence verification ledger, and auto-close. We adopt **six specific ideas** from it (§2.2). We do **not** adopt its server-side rules where they are weaker, chiefly "anchor business time to `received_at`" (§2.3). |
| Can the mobile config be organization-scoped and configurable? | **Yes, with policy layers (revision 2, §4).** `fieldops.work_policies` (one whole row wins, organization × role only) is **replaced** by `fieldops.policy_layers`. Each layer is a *sparse* set of settings with a target: organization, role, team, hub, user, and **beat once that module exists**. Layers merge **per setting** from general to specific over a code-default floor, and HQ can **lock** settings. The root organization's layer is the tenant fallback, and each organization's layer is its own fallback. One registry declares every setting (type, default, frozen/live, server/client, allowed scopes), and the same engine carries shift obligations, the Android config, and the session rule. `GET /api/me/fieldops/config` renders the app's JSON with a monotonic per-tenant version and an ETag. Adding a dimension later (beat, district, …) is three steps, with no resolver or table change. |
| Models/schemas to change? | Yes: 6 nullable columns + 2 labels on `location_pings`; 10 columns on `shifts`; `work_policies` → `policy_layers` + `policy_epochs` (behaviour-preserving data migration); one new table `auth.user_sessions`; settings enum migration. Details in §3–§7 and the full list in §9. |
| Single session per user? | Today **both devices stay signed in**, and so does a token after logout. I checked this live (§1). Tokens are stateless JWTs (24 h access, 30 d refresh) with no session store, so nothing can revoke them. **Recommendation:** server-side sessions with a `sid` claim. Make the rule a per-organization/per-role setting: **one active session per user for the field app** (Device B's login revokes Device A, and A gets `401 session_revoked`), and multiple sessions for web/manager clients. Logout must revoke. §6 |
| `/api/me/shifts` working? | **Yes.** I tested it live end to end (register device → start → replay → list → end). There are also **two blockers and three bugs**, listed in §1. |
| Shift fields missing (delivery type, title, address, start location, geofence enforcement)? | Yes (§5.1b): `title`, `shift_code`, `work_type`, `source`, template link, **route endpoints** (start/end: `anywhere` (default) / `hub` / `assigned_hub` / `place`, each with optional geofence enforcement; one value type later reused by beats and journey plans, §5.1), the user's hub of the day, and `auto_close_at`. Also a manager API to **create scheduled shifts** (§5.2). When nobody scheduled a shift, **shift templates** apply (§5.6): an organization- or role-wide pattern such as THPL's "Work Shift" 09:00–21:00 IST for `member`, chosen through the policy layers and materialized when the user starts. Seeded for THPL (§5.9). |
| `profile_visibility` values? | Today the API allows `public`, `organization`, `contacts`, `private`. **None of them is enforced anywhere**, and they do not match the UI. New closed set: `everyone`, `team`, `managers`, `private`; contact: `everyone`, `team`, `hidden`; notifications add `slack`. These come with an enforcement resolver and a `GET /me/settings/options` catalogue so Android never hardcodes values. §7 |

---

## 1. What I verified against the running dev stack (2026-10-06)

The test user was `dev@local.test` (id 2), with a token from `POST /api/auth/dev-token`.

| Step | Result |
|---|---|
| `GET /api/me/shifts` (no shifts) | `200`, `data: []` ✅ |
| `POST /api/me/devices` | `200`, device + session registered ✅ |
| `POST /api/me/shifts` | **`422 location_consent_required`** ❌ — see blocker B1 |
| Inserted a `location_tracking` consent row by SQL (dev DB, `consent_records.id = 1`), retried | `201 Shift started` ✅ |
| Same request again (replay) | `200` (idempotent replay) ✅ |
| `GET /api/me/shifts` | the shift, `status: active` ✅ |
| `POST /api/me/shifts/{uuid}/end` with a `client_timestamp` 22 min in the future | `200`. `ended_at` was clamped to receipt time, because business time is never in the future ✅ |
| `GET /api/me/shifts` | `status: completed`, `paid_minutes: "8.86"` ✅ |
| The Android ping payload as sent today, to `POST /api/me/location-pings` | `200`, `rejected: 1`, `reason: "uuid: Field required"`. This is expected (§3), but see bug X1 |
| Minted a second token (Device B's login), then called `GET /api/auth/me` with the **first** token | **`200`** — see §6 |
| `POST /api/auth/logout`, then the **same** token on `GET /api/auth/me` | **`200`** ❌ logout does not revoke |

The dev DB now holds one completed test shift and one consent row for `dev@local.test`.

**Blockers**

* **B1 — no consent API.** `work_policies.require_location_consent` defaults to `true`, and `compliance.consent_records`
  has no API at all. **A field user cannot start a shift** unless a policy turns consent off, or someone inserts a row
  by hand. Fix: §8.
* **B2 — no way to create a shift from the backend.** `ShiftStatus.SCHEDULED` exists, but no code path writes it.
  Only `POST /me/shifts` creates shifts, as already-active rows. Fix: §5.

**Bugs found on the way**

* **X1** — in `ingest.py:266`, a rejected item with no uuid is reported as `"uuid": "None"` (the string), not `null`.
  The cause is `str(raw.get("uuid"))`.
* **X2** — `Decimal` columns serialize as JSON **strings** (`"8.86"`), which is Pydantic v2's default. Android must parse
  them as strings, or the `*Out` schemas should declare `float` for durations/distances. Recommendation: `float` for
  minutes/km/metres in Out DTOs, and keep `Decimal` for money.
* **X3** — the sample request has `capturedAtEpochMs: 17860370863000`, an **extra digit** (year 2536), next to
  `createdAtEpochMs: 1786037086300`. The server clamps it (`PARTITION_KEY_CLAMPED`), but it is a client bug.

---

## 2. Client design vs. our design

### 2.1 Side by side

| Concern | Android guide | `fieldops` as built | Verdict |
|---|---|---|---|
| Identity of a ping | client `ping_id` UUID, server dedupes | client UUIDv7 `uuid` + `UNIQUE(tenant,user,uuid,recorded_at)`, `ON CONFLICT DO NOTHING`, batch-level replay ledger | **ours** (also dedupes whole batches) |
| Who the ping belongs to | `da_id` in the body | the bearer token | **ours**. The body's id is only a consistency check (§3.4) |
| Shift reference | free string `SHIFT-20260814-DA4821` | shift `uuid` (client- or server-generated) | **ours**. Add a human `shift_code` for display (§5) |
| Business time | `received_at` (server) for anything with "teeth" | `occurred_at` from `clock.py`: monotonic chain → skew-corrected wall clock → device wall clock → receipt | **ours**. See §2.3 |
| Significance / distance | client `is_significant`, `distance_from_last_m` | server recomputes impossible hop, duplicate coordinates, accuracy | **ours** (client values kept as diagnostics) |
| Mock location | client flag + server policy `mock_location_action` | client flag → `QualityFlag.MOCK`; never evidence | **merge**: add the policy action (§3.6) |
| Proof of delivery | one-shot high-accuracy fix sent **as a ping** with `capture_reason` | fix attached **to the action** (`POST /me/visits`, `/end`), verified atomically, ledgered in `location_checks` | **ours**. The action carries the proof. The ping copy is a dedupe-safe duplicate |
| "Better fix replaces fallback" | Room `REPLACE` on a deterministic `ping_id` | append-only; verifier picks **best accuracy in the window** | **ours**. Evidence is never overwritten |
| Geofences | client-registered, ids like `GEOFENCE-STOP-00456` | `geo.geofences` + `verify.py` (accuracy-aware, polygon or circle) | **merge**: server ships the fence pack, the client reports enter/exit (§5.5) |
| Zombie shifts | client AlarmManager + "server backstop" | `auto_close_shifts` every 5 min, ghost/supersede rules, `long_gap` anomaly | **ours**, plus a live `tracking_silent` detector (§3.7) |
| Server-driven config | versioned JSON | policy columns, frozen per shift | **merge**: render their JSON from our policy (§4) |
| Device facts per ping | `device_model`, `os_version`, `app_version_code` on every ping | once per launch on `device_sessions` | **ours**. Repeating them per ping is ~60 bytes × 1,000 pings/day for nothing |
| Offline queue / FGS / adaptive interval / WorkManager role | detailed | out of scope for the server | **theirs**. Adopt on Android as written |

### 2.2 What we adopt from the Android guide

1. **`capture_reason` vocabulary**, mapped onto our `kind` + `checkpoint_label` (§3.2). Two new labels:
   `geofence_enter`, `geofence_exit`.
2. **`app_state`** (foreground/background) and **`battery_state`** on each fix. Both are cheap and useful as evidence
   weight and in tracking-health analysis.
3. **Server-driven client config** with `config_version` + `effective_from`, served to the app (§4).
4. **`mock_location_action`** as policy (`flag_only` / `reject_and_alert` / `end_shift`) (§3.6).
5. **Stops as first-class context on pings** (`stop_id`). For us a stop is a **planned visit**, so `stop_id` becomes
   `visit_uuid` (§5.4).
6. **A "no telemetry for N × interval" backstop on open shifts**, as a live detector, not only a post-shift metric
   (§3.7).

### 2.3 What we do not adopt, and why

* **"Anchor attendance to `received_at`."** For a rural, offline-first fleet this is the wrong anchor. A shift start
  captured at 09:02 and synced at 18:40 would be recorded as 18:40. `clock.py` already gets tamper resistance *and*
  correctness. It chains the fix's `elapsed_realtime` to the monotonic clock **at send time** (header
  `X-Device-Elapsed-Ms`), then anchors that to `received_at`. The result is server-anchored and immune to the user
  changing the wall clock. `received_at` is still stored, and the gap is still flagged (`CLOCK_SKEW`,
  `STALE_REPLAY`, `CLOCK_TAMPERED`). **Android must send the three `X-Device-*` headers on every upload.** That is the
  single most important item in this document for the Android team.
* **Deterministic `ping_id` from `(stopId, reason)` with REPLACE.** Evidence must be append-only. Send each capture
  with its own UUIDv7 and let the verifier choose. Double-tap protection already exists: the visit `uuid` plus
  `X-Idempotency-Key` make a second "End Delivery" a replay.
* **Accepting the Room entity on the wire.** The request in the brief is the Room row in camelCase, including
  `syncStatus`, `syncAttempts`, `createdAtEpochMs`. Those are local queue bookkeeping. The guide itself says to send
  `PingDto`, in snake_case. The server rejects unknown keys so this mistake is visible immediately.

---

## 3. Telemetry wire contract (`POST /api/me/location-pings`)

### 3.1 One contract, one mapper

`PingIn` stays the only schema (`extra="forbid"`). An explicit inbound mapper, `fieldops/wire.py::normalize_ping(raw)`,
runs per item **before** validation and accepts the Android §6 field names. This is the "mapper at every inbound
boundary" rule: two spellings reach one model, and no second endpoint is added.

| Android §6 field | Server field | Mapper rule |
|---|---|---|
| `ping_id` | `uuid` | rename |
| `da_id` | — | compare with the token's user (§3.4), then drop |
| `shift_id` | `shift_uuid` | rename; must be a UUID |
| `stop_id` | `visit_uuid` | rename; must be a UUID (a stop is a planned visit, §5.4) |
| `capture_reason` | `kind` + `checkpoint_label` | table §3.2 |
| `captured_at` | `client_timestamp` | rename |
| `elapsed_realtime_ns` | `elapsed_realtime_ms` | `// 1_000_000` |
| `received_at` | — | **dropped** (server-set; a client value is ignored) |
| `latitude`, `longitude` | same | — |
| `accuracy` | `accuracy_m` | rename |
| `bearing` | `heading_deg` | rename; `360.0` → `0.0` |
| `speed` | `speed_mps` | rename |
| `provider` | `provider` | same enum (`gps/network/fused/passive`) |
| `is_mock_location` | `is_mock` | rename |
| `battery_pct` | same | — |
| `battery_state` | `battery_state` (**new column**) + `is_charging` derived | `charging`/`full` → true; `discharging`/`not_charging` → false |
| `network_type` | same | `wifi/5g/4g/3g/2g/offline/unknown` (CHECK added) |
| `activity_type`, `activity_confidence` | same | — |
| `app_state` | `app_state` (**new column**) | `foreground` / `background` |
| `geofence_event` `{geofence_id, type}` | `geofence_uuid` (**new**) + label `geofence_enter/exit` | `type` must agree with `capture_reason` |
| `is_significant` | `client_significant` (**new**, diagnostics) | server never trusts it |
| `distance_from_last_m` | `client_distance_m` (**new**, diagnostics) | server computes its own |
| `device_model`, `os_version`, `app_version_code` | — | dropped per ping. They belong on `POST /me/devices` → `device_sessions` (already there) |

Anything else unknown (camelCase keys, `sync_status`, `sync_attempts`, `created_at_epoch_ms`) → the item is
**rejected** with `reason: "unknown fields: syncStatus, …"`. The rest of the batch is still accepted, because each item
is validated on its own.

### 3.2 `capture_reason` → stream row

| `capture_reason` | `kind` | `checkpoint_label` | Required context |
|---|---|---|---|
| `interval` (default) | `continuous` | — | `shift_uuid` |
| `shift_start` / `shift_end` | `checkpoint` | `shift_start` / `shift_end` | `shift_uuid` |
| `start_delivery` / `end_delivery` | `checkpoint` | `visit_start` / `visit_end` | `visit_uuid` (= `stop_id`) |
| `geofence_enter` / `geofence_exit` | `checkpoint` | **`geofence_enter` / `geofence_exit` (new)** | `geofence_uuid`; `visit_uuid` optional |

**The proof of delivery is the action, not the ping.** "Start Delivery" calls `POST /me/visits/{uuid}/start` (§5.4)
with the high-accuracy fix in `fix`. "End Delivery" calls `POST /me/visits/{uuid}/end`. **Use the same UUID for the
action's `fix.uuid` and the queued ping's `ping_id`**, so the ping copy becomes a no-op duplicate once the action
succeeds, and still delivers the point if the action is retried later.

### 3.3 Required headers (unchanged; Android must send them)

| Header | Value |
|---|---|
| `Authorization: Bearer …` | access token |
| `X-Device-Session` | session uuid from `POST /me/devices` (one per app launch) |
| `X-Device-Sent-At` | wall clock at send, ISO-8601 with offset |
| `X-Device-Elapsed-Ms` | `SystemClock.elapsedRealtime()` at send |
| `X-Device-Boot-Count` | `Settings.Global.BOOT_COUNT` |
| `X-Idempotency-Key` | uuid, on mutations (shift/visit actions) |

The batch body is `{ "uuid": "<batch uuid>", "pings": [ … ≤ 500 ] }`. Android's `max_batch_size` (200) fits.

### 3.4 Owner check (`da_id`): the shared-device trap

The Room queue survives logout. If DA1 logs out and DA2 logs in on the same phone, DA1's unsent pings would be
flushed **under DA2's token** and attributed to DA2. The server rule: when the item carries `da_id`/`user_ref`, it must
equal the token user's `uuid` or `employee_code`. Otherwise the item is rejected with `user_mismatch` and a
`foreign_user_ping` device event is written. The Android rule: **flush the queue before logout**, and partition the
queue by user.

### 3.5 Stream schema changes (`fieldops.location_pings`, partitioned parent)

All columns are nullable with no default. `ALTER TABLE … ADD COLUMN` on the parent propagates to the partitions and only
changes metadata.

```python
geofence_id: Mapped[int | None] = mapped_column(BigInteger, comment="geo.geofences.id (no FK, resolved at ingest)")
geofence_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True), comment="Fence the client reported")
app_state: Mapped[str | None] = mapped_column(String(12), comment="foreground | background")
battery_state: Mapped[str | None] = mapped_column(String(14), comment="charging | discharging | full | not_charging | unknown")
client_significant: Mapped[bool | None] = mapped_column(Boolean, comment="Client hint; diagnostics only")
client_distance_m: Mapped[float | None] = mapped_column(REAL, comment="Client-computed hop; diagnostics only")
```

New enums: `AppState`, `BatteryState`, `NetworkType`, and `CheckpointLabel.GEOFENCE_ENTER/EXIT`. New CHECKs:
`chk_location_pings_geofence_label` (`checkpoint_label NOT IN ('geofence_enter','geofence_exit') OR geofence_uuid IS
NOT NULL`), plus the enum CHECKs. `PingIn` gains the same fields. `TrackPoint` gains `checkpoint_label`
(already there) and `geofence_uuid`.

Geofence ingest resolves `geofence_uuid` → `geofence_id` in one query per batch (the same pattern as
`_contexts`). An enter event **does not** start a visit. It is context for `detect_dwell` and the review screen.

### 3.6 Mock-location policy

New policy setting `security.mock_location_action` (`flag_only` | `reject_and_alert` | `end_shift`, default
`flag_only`; lockable, so HQ can enforce it fleet-wide, §4.3). The
server **always stores** a mock fix, because it is evidence of the fraud attempt. It is flagged `MOCK` and is never
evidence.

| Action | Ambient ping | Fix on an action (shift start, visit start/end) |
|---|---|---|
| `flag_only` | anomaly `mock_location` (one per shift, dedupe key) | accepted; anomaly |
| `reject_and_alert` | anomaly, severity `critical`, manager alert | **422 `mock_location_rejected`** |
| `end_shift` | anomaly + `close_shift(..., end_reason='policy_violation')` (new `ShiftEndReason`), review pending | 422, and the open shift is closed |

The Android flags `enforce_mock_rejection` and `mock_location_action` both come from this one column (§4.3), so they
cannot disagree.

### 3.7 Live silence detector (the guide's "server backstop")

This is a new beat task, `detect_silent_shifts`, every 5 min. An open, unpaused shift whose `last_activity_at` is older
than `tracking.silence.factor × effective max interval` (default `3 × 600 s`) raises anomaly `tracking_silent` (new
`AnomalyType`, severity `warning`). The dedupe key is per shift per silence window. It resolves itself when pings
resume. It **does not** close the shift; `auto_close_shifts` keeps that job.

---

## 4. Policy layers — one configuration engine for obligations, client config and sessions

> **Revision 2 (2026-10-06).** The first draft extended `work_policies` with a `client_config` column. That kept
> the table's shape, which is "one row per (organization, role), the winning row is used whole". The user rejected it,
> correctly: it cannot target a **beat** (or any future dimension) and it has no real organization fallback. This
> section replaces it.

### 4.1 Why `work_policies` cannot simply grow a `beat_id` column

`service/policy.py::resolve_policy` (as built) selects **one row**:

```sql
… WHERE home.hierarchy_path LIKE o.hierarchy_path || '%' AND (p.role_id = :role OR p.role_id IS NULL)
ORDER BY o.depth DESC, (p.role_id IS NOT NULL) DESC LIMIT 1
```

There are three structural problems, and adding columns makes all three worse:

1. **Winner takes all, with no inheritance per setting.** Suppose HQ's organization default sets `ping_interval_s = 45`
   and `geofence_enforcement = hard_block`. A role row added to change *only* the selfie rule carries every other
   column at its **code default**. Every user with that role silently loses HQ's 45 s and hard block. The only way to
   "inherit" is to copy every value into every row, and the copies then drift.
2. **The precedence is hard-coded to two dimensions.** Org depth beats role, so a branch's organization default
   silently overrides HQ's "delivery agents" rule. Adding `beat_id` means a third `ORDER BY` term, a wider unique index,
   and a combinatorial set of rows (organization × role × beat).
3. **No governance.** HQ cannot say "consent is mandatory everywhere, branches may not turn it off".

### 4.2 The model: sparse layers, merged per setting

A **policy layer** is a *sparse* set of settings with a **target**. Resolution collects every layer that applies to
the person and the work context, orders them from general to specific, and merges **per setting**. The most specific
layer that sets a setting wins that setting, and everything it does not set is inherited. This is CSS / Group Policy /
Kustomize semantics, and it is what "organization default with role and beat overrides" means.

```
code defaults (settings registry)                       ← always complete; the floor
  └─ organization layer @ root org (tenant default)      ← "organization fallback"
       └─ organization layer @ branch (Halol)            ← deeper org refines
            └─ role layer (delivery_agent)               ← who you are
                 └─ team layer (Halol night team)
                      └─ hub layer (Halol Hub)            ← where you operate from
                           └─ beat layer (Beat H-03)      ← where this shift works   (future)
                                └─ user layer (Ravi)      ← individual exception
```

**Precedence rule (total order, deterministic):**
`scope rank ASC` (organization 0 · role 10 · team 20 · hub 30 · beat 40 · user 50) →
`organization depth ASC` (a layer defined deeper in the tree beats the same scope defined higher) →
`priority ASC` (explicit tie-breaker) → `effective_from ASC NULLS FIRST` → `id ASC`. Layers are applied in that order
and later ones win.

Why scope before depth: "what this work is" (role, beat) is more specific than "where in the org chart the rule was
written". A branch that wants to override HQ's *delivery-agent* rule writes a *delivery-agent* rule at the branch
(same rank, deeper, so it wins). A branch's general default never accidentally overrides a fleet-wide role rule,
which is problem 2 above.

**Locks (governance).** A layer can list `locked_keys`. A locked setting cannot be set by any layer that applies
*below* it (a narrower scope, or a deeper org), and the write is refused with 422 `policy_setting_locked`, naming the
locking layer. At resolution a lock also stops the merge for that key, which covers layers written before the lock.
HQ locks `consent.required = true` and `security.mock_location_action`, and no branch, beat or user layer can relax
them.

**Settings are atomic units, not individual scalars.** A setting may be a structured value. All interval knobs are
**one** setting, `tracking.intervals`
(`{min_s, base_s, max_s, battery_bands, activity_intervals, …}`), so a layer either replaces the whole group or none
of it. This is what makes cross-field invariants checkable at **write** time (`min ≤ base ≤ max`, bands descending to
0, every interval within `[min, max]`). A per-scalar merge could combine a beat's `max_s = 120` with HQ's
`base_s = 300` into an invalid config nobody wrote.

### 4.3 The settings registry (`fieldops/policy/settings.py`): registries over conditionals

Every setting is declared once in code:

```python
@dataclass(frozen=True)
class SettingSpec:
    key: str                         # "tracking.intervals"
    model: type[BaseModel] | type    # Pydantic model or scalar type — validates writes AND defaults
    default: Any
    binding: Binding                 # FROZEN (snapshotted at shift start) | LIVE (re-resolved on refresh)
    audience: Audience               # SERVER (enforced here) | CLIENT (rendered to the app) | BOTH
    scopes: frozenset[Scope]         # where it may be set (e.g. session.* : organization, role, user — never beat)
    client_path: str | None          # where it appears in the app's JSON, e.g. "location_request"
    lockable: bool = True
    description: str = ""
```

Initial catalogue. Existing `work_policies` columns become settings 1:1, and the Android config fills the client side:

| Setting key | Type (summary) | Binding | Audience | Allowed scopes |
|---|---|---|---|---|
| `shift.requirements` | `{requires_shift, allow_visits_without_shift, require_start_selfie, require_odometer, allow_unscheduled_shifts}` | frozen | server | all |
| `shift.template` | template reference \| `null` (§5.6) | frozen | both | all |
| `shift.window` | `{earliest_start_local, latest_end_local, start_early_minutes, late_start_grace_minutes, max_shift_hours, overtime_minutes, auto_close_grace_minutes, stale_shift_after_minutes, pre_end_reminder_minutes}` | frozen | both | all |
| `pause.rules` | `{max_pause_minutes, max_pauses_per_shift, paid_pause_types, track_during_pause, extends_cap}` | frozen | both | all |

*(The old `require_start_at_place_id` column becomes the start endpoint of a template (§5.1, §5.6) during the
§4.9 migration: one template per policy row that set it, with `mode = place` and `enforcement = advisory`. It is not
a setting any more, because endpoints belong to the plan, not the policy.)*
| `consent.required` | bool | frozen | server | organization, role, user |
| `tracking.mode` | `off \| checkpoints_only \| continuous` | live | both | all |
| `tracking.intervals` | `{priority, min_s, base_s, max_s, min_update_ratio, max_delay_ratio, significant_distance_m, battery_bands[], activity_intervals{}}` | live | client | all |
| `tracking.accuracy` | `{client_max_accuracy_m (200), evidence_max_accuracy_m (100)}` | live | both | all |
| `tracking.silence` | `{factor (3)}` | live | server | all |
| `stop_capture` | `{priority, timeout_s, fallback_to_last_known}` | live | client | all |
| `sync.batch` | `{max_batch_size, max_wait_s, flush_on_significant}` | live | client | all |
| `retention.local` | `{synced_data_days}` | live | client | organization, role |
| `geofence.rules` | `{enabled, enforcement, default_radius_m, geocoded_radius_factor, allow_manual_location}` | frozen | both | all |
| `anomaly.thresholds` | `{min_visit_minutes, late_task_window_hours, gap_flag_minutes, clock_skew_flag_seconds, min_tracking_coverage_pct}` | frozen | server | organization, role, team, hub, beat |
| `security.mock_location_action` | `flag_only \| reject_and_alert \| end_shift` | frozen | both | organization, role, user |
| `security.integrity` | `{mock_detection, play_integrity_check}` | live | client | organization, role |
| `features` | `{activity_recognition, dashboard_push}` | live | client | all |
| `session.field` | `{max_sessions (1), on_new_login: revoke_previous \| refuse, drain_grant_hours (24)}` | — (login time) | server | organization, role, user |

*`session.field` lives here, as decided.* It is resolved at **login**, where there is no shift and therefore no
beat/hub context, and that is why its allowed scopes exclude them. The registry refuses a beat-level session rule at
write time instead of letting it silently never apply.

The registry gives four things for free: write validation, the code-default floor (problem 1 disappears), the admin
catalogue endpoint, and the client renderer. Adding a setting means adding one `SettingSpec`, with no migration.

### 4.4 Scope dimensions: beats can be added without touching the resolver

A **dimension** is a registry entry too (`fieldops/policy/dimensions.py`):

```python
@dataclass(frozen=True)
class Dimension:
    scope: Scope                 # "role", "team", "hub", "beat", …
    rank: int                    # precedence (§4.2)
    entity_type: str             # core.entity_types.code — validates scope_id on write (exists, same tenant)
    from_context: Callable[[PolicyContext], Awaitable[tuple[int, ...]]]   # which ids apply right now
    needs_work_context: bool     # True = only known once a shift exists (hub, beat)
```

| Dimension | Ids that apply | Available |
|---|---|---|
| `organization` | the user's organization **ancestry** (root → home), not a single id | now |
| `role` | the user's **base role** (obligations don't compose by union, which is existing doctrine) | now |
| `team` | approved team memberships (`teams`) | now |
| `hub` | `shift.hub_id`, else the user's home hub when HR records one | now (with §5.1 `shifts.hub_id`) |
| `beat` | `shift.beat_id` | **when the beats module lands** |
| `user` | the user | now |

**Adding beats later is three steps, and the resolver, the table and the API do not change:** (1) the beats module
creates its table and registers the `beat` entity type, (2) `shifts.beat_id` is added (nullable, set when a shift is
scheduled), (3) one `Dimension` entry. `scope_type = 'beat'` is in the CHECK from day one, so the only migration is
the beats module's own. A future "district" (`geo.admin_boundaries`), "vehicle type" or "customer segment" dimension
follows the same three steps.

**Beat comes from the shift's assignment, never from live GPS position.** Re-resolving config as a phone crosses a
polygon would oscillate at boundaries, depend on the very fixes the config controls, and make "which rules applied"
unanswerable in a dispute. The shift is scheduled *for* a beat, and that is the context. Dimensions with
`needs_work_context = True` are ignored when there is no shift, so login and device registration get the
organization/role/user view, and the config is re-resolved at shift start with the shift's context.

### 4.5 Tables

**`fieldops.policy_layers`** (ENTITY: `BigIntPKWithUUIDv7Mixin`, `OrgEntityMixin`, `SoftDeleteFilteredMixin`,
`HasCommentsMixin` for change discussions). It replaces `fieldops.work_policies`.

```python
class PolicyLayer(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "policy_layers"
    # organization_id (from OrgEntityMixin) = the subtree the layer applies within
    name: Mapped[str]                       = mapped_column(String(120), nullable=False)
    description: Mapped[str | None]         = mapped_column(Text)
    scope_type: Mapped[str]                 = mapped_column(String(20), nullable=False)   # CHECK values(Scope)
    scope_id: Mapped[int | None]            = mapped_column(BigInteger)                   # NULL iff organization
    settings: Mapped[dict]                  = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"),
                                                            comment="Sparse {setting_key: value}; validated by the registry")
    locked_keys: Mapped[list[str]]          = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    priority: Mapped[int]                   = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    effective_from: Mapped[dt.datetime | None]  = mapped_column(DateTime(timezone=True))
    effective_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str]                     = mapped_column(String(10), nullable=False, server_default=text("'active'"))
    __table_args__ = (
        CheckConstraint("(scope_type = 'organization') = (scope_id IS NULL)", name="chk_policy_layers_scope_id"),
        CheckConstraint("effective_until IS NULL OR effective_from IS NULL OR effective_until > effective_from",
                        name="chk_policy_layers_window"),
        # one live layer per target per start instant (a scheduled change is a second row with a later effective_from)
        Index("uq_policy_layers_target_live", "tenant_id", "organization_id", "scope_type",
              text("COALESCE(scope_id, 0)"), text("COALESCE(effective_from, '-infinity'::timestamptz)"),
              unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("ix_policy_layers_lookup", "tenant_id", "scope_type", "scope_id",
              postgresql_where=text("deleted_at IS NULL AND status = 'active'")),
        {"schema": "fieldops"},
    )
```

`scope_id` has **no FK**. It is polymorphic, like `visits.account_type/account_id`, and is validated on write
through the dimension's `entity_type` (the same `core.entity_types` registry that visits, comments and tax assignments
use). A deleted team or role makes its layers inert, and the nightly task soft-deletes orphaned layers with an
activity record.

**`fieldops.policy_epochs`** (`tenant_id` PK, `epoch BIGINT`, `changed_at`). It is bumped with
`UPDATE … SET epoch = epoch + 1 RETURNING epoch` **in the same transaction** as any layer write. It is the tenant's
monotonic config version, and it lives in fieldops because tenancy core must not know a feature module (`.importlinter`).

**Scheduled changes** (`effective_from` in the future) need no job to "activate" them; a layer simply starts
matching. Clients notice on their next periodic refresh because the ETag changes while the version stays equal, which
the client rule in §4.7 accepts. The cache fingerprint includes the day boundary, and the resolver also caps the cache
TTL at the next `effective_from`/`effective_until` instant among candidate layers, so a scheduled change is never
served stale.

### 4.6 Resolution (`fieldops/policy/resolver.py`)

```
PolicyContext(user, at, shift=None)                     # shift → hub, beat, frozen snapshot
  → ids per dimension (registry providers)              # ≤ 2 queries: teams, org ancestry (cached per request)
  → ONE query for candidate layers:
      WHERE tenant_id = :t AND deleted_at IS NULL AND status = 'active'
        AND organization_id = ANY(:ancestry)
        AND (effective_from IS NULL OR effective_from <= :at)
        AND (effective_until IS NULL OR effective_until > :at)
        AND (  scope_type = 'organization'
            OR (scope_type = 'role' AND scope_id = ANY(:roles))
            OR (scope_type = 'team' AND scope_id = ANY(:teams))
            OR (scope_type = 'hub'  AND scope_id = ANY(:hubs))
            OR (scope_type = 'beat' AND scope_id = ANY(:beats))
            OR (scope_type = 'user' AND scope_id = :user) )
  → sort (§4.2) → fold per setting key, honouring locks → registry defaults fill the gaps
  → ResolvedPolicy {values, provenance{key: layer_uuid, scope, org_code}, conflicts[], epoch, etag}
```

* **Pure core.** `fold(layers, registry) -> ResolvedPolicy` has no I/O and is exhaustively unit-tested
  (precedence, locks, multi-team ties, windows, defaults).
* **Ties are visible.** Two layers of the same rank, the same depth and the same priority that both set a key are
  resolved deterministically by `id`, but they are reported in `conflicts`. The admin explain endpoint shows them,
  and the write API warns (`data.warnings: ["ambiguous_with:<layer_uuid>"]`) when a write creates one (the multi-team
  case).
* **Cache.** Redis DB 0, key `fieldops:policy:{tenant}:{epoch}:{context_fingerprint}` (fingerprint = sorted ids per
  dimension + the day boundary of `at`), TTL 10 min. A layer write bumps the epoch, which invalidates every key in
  the tenant without a scan, the same pattern as the RBAC per-tenant epoch. A role/team/hub change changes the
  fingerprint, so it misses the cache naturally.
* **Hot path.** `ingest_batch` uses the **open shift's snapshot** (no resolution). Only pings without a shift fall back
  to a cached resolve.
* **Snapshot.** At shift start: `shift.policy_snapshot = {values (FROZEN settings), provenance, epoch, layer_uuids}`.
  `EffectivePolicy` keeps its `__getattr__` façade over the new values (`policy.ping_interval_s` maps to
  `tracking.intervals.base_s` through an alias table for one release). The 17 call sites therefore do not change in
  the first PR.

### 4.7 What the app gets: `GET /api/me/fieldops/config`

* Context = the user + their **open shift** if any (so hub/beat layers apply during the shift). FROZEN settings come
  from the shift snapshot; LIVE settings are resolved now. Without a shift: org/role/team/user layers only.
* Body = the Android JSON, rendered from `audience ∈ {client, both}` settings through each spec's `client_path`.
  `battery_thresholds` is emitted in the **v5 band format only** (Android accepted it):
  `[{"min_pct": 30, "interval_seconds": 45}, {"min_pct": 15, "interval_seconds": 120}, {"min_pct": 0, "interval_seconds": 600}]`.
* `config_version` = tenant epoch (monotonic, never decreases, including when a narrower layer is deleted or the
  winning layer changes). `effective_from` = the newest `effective_from`/`updated_at` among contributing layers.
  **Client rule:** apply when `config_version >= applied_version` and the ETag differs. An equal version with new
  content happens when the user's *context* changed (new role, new shift beat) and is valid.
* `ETag` = sha256 of the rendered body. `If-None-Match` → `304`. It is also returned inline from `POST /me/devices`
  and `POST /me/shifts` (start), so start never waits on a fetch.
* `meta.provenance` (optional, `?explain=true`): which layer set each block. Support staff can read it off a phone
  screenshot.

### 4.8 Administration API (`/api/fieldops/policy-layers`; replaces `/api/fieldops/policies`)

| Route | Perm | Notes |
|---|---|---|
| `GET /policy-settings` | `fieldops.policy:read` | the registry catalogue: key, JSON schema, default, binding, audience, allowed scopes, lockable. The admin UI renders forms from it |
| `GET /policy-layers?scope_type=&scope_id=&organization=` | `fieldops.policy:read` | slim list |
| `POST /policy-layers` | `fieldops.policy:create` at the layer's organization | validates scope existence, allowed scopes per key, values, locks above; bumps epoch |
| `PATCH /policy-layers/{ref}` | `…:update` | `row_version`; `settings` patch = **set/replace keys**, `unset: [keys]` = fall back to inheritance (distinct from setting a value) |
| `DELETE /policy-layers/{ref}?reason=` | `…:delete` | soft delete; bumps epoch |
| `GET /policies/resolve?user_id=&shift_uuid=&at=` | `fieldops.policy:read` + `scope.visible` | **explain**: resolved values + provenance + conflicts + locks |
| `POST /policies/preview` | `fieldops.policy:read` | a draft layer → how many users' resolved values change, per key (dry run, nothing written) |

Who can write what: a team manager with `fieldops.policy:create` **at the team's organization** can write team layers;
an organization layer needs the permission at that organization (row targets via `org_of`). Locks apply to everyone,
so HQ governance survives delegated administration.

### 4.9 Migration from `work_policies` (built 2026-09-29, so few rows)

One data migration, behaviour-preserving:

* Each live `work_policies` row becomes one layer: `role_id IS NULL` → `scope_type='organization'`, otherwise
  `scope_type='role'`. **All** of its values are copied (not only non-defaults). This reproduces today's
  winner-takes-all result exactly, and admins can trim layers afterwards to gain inheritance.
* Shifts keep their existing `policy_snapshot`. `EffectivePolicy.from_snapshot` reads both the old flat shape and the
  new one (`snapshot_version` key).
* Drop `work_policies` in the **next** release, after a parity check: resolve every active field user with old and new
  code and assert identical values (a management command run during the deploy).
* `/api/fieldops/policies` answers `410 Gone` with a link to the new routes for one release.

## 5. Scheduled shifts (created from the backend), start location, and stops

### 5.1 Route endpoints: one shared value type for "where work starts and ends"

> **Revision 3 (2026-10-06).** A DA does not always start at a hub. Shifts today, and beats and journey plans later,
> each need "start at a hub / a particular location / anywhere" and "end at a hub / a particular location / anywhere",
> with optional geofencing. Rather than three different shapes, this is **one value type**, used by every
> object that plans work.

**`EndpointSpec`** (Pydantic, `fieldops/endpoints.py`) and **`RouteEndpointsMixin`** (the column set + CHECKs, applied
to `shift_templates`, `shifts`, and later `beats`/`journey_plans`):

| Mode | Meaning | Columns used | Geofence allowed |
|---|---|---|---|
| `anywhere` (**default**) | no expectation | — | no (enforcement must be NULL) |
| `hub` | a specific hub | `*_hub_id` (the hub's `place_id`/`geofence_id` is the target) | yes |
| `place` | a particular location | `*_place_id` → `geo.places` (raw lat/lng + address in the API → geo find-or-create) | yes |
| `assigned_hub` | **the user's hub for that day** (§5.7). It resolves at materialization; NULL that day → treated as `anywhere`, anomaly `no_hub_assigned` (info) | — until resolved | yes |

Per side (`start_*`, `end_*`): `mode`, `hub_id`, `place_id`, `enforcement` (`advisory` / `soft_block` /
`hard_block` / NULL = no check), `radius_m` (NULL = the target's active fence, else the policy default radius).
CHECKs: `mode='hub' ⇔ hub_id NOT NULL`, `mode='place' ⇔ place_id NOT NULL`,
`mode IN ('anywhere','assigned_hub') ⇒ hub_id IS NULL AND place_id IS NULL`, `mode='anywhere' ⇒ enforcement IS NULL`.

Start and end are **independent**, and both default to `anywhere`. (The brief says "start and end both cannot be
anywhere … it depends. By default anywhere". I read this as "they need not both be anywhere": each side is
configured on its own. If it was meant as a *rule* that at least one side must be concrete, that contradicts the
default. It is a one-line validator, `require_one_concrete_endpoint`, that can be switched on per object type
later. **Q13.**)

**Resolution order** when a shift is materialized. The first non-NULL spec per side wins, so a journey plan can pin
the start while the end falls back to the beat:

```
explicit on the shift  >  journey plan (future)  >  beat (future)  >  shift template  >  anywhere
```

The **resolved** endpoint is frozen onto the shift. `assigned_hub` becomes a concrete `hub` (or `anywhere`), and the
`place_id` actually used is stored. Moving a hub or editing a template never rewrites history.

### 5.1b New columns on `fieldops.shifts`

| Column | Type | Purpose |
|---|---|---|
| `shift_code` | `String(32)`, per-tenant partial unique (`deleted_at IS NULL`) | human reference, `SH-20261006-0042` (organization-timezone date + daily sequence). The API id stays `uuid` |
| `title` | `String(200)` | from the scheduler, else the template (`"Work Shift"`) |
| `work_type` | `String(20)` + CHECK, enum `ShiftWorkType` | **"Delivery Type"** (decided): `delivery`, `collection`, `return`, `exchange`, `other`. Closed vocabulary: a new type = enum member + CHECK migration; Android maps unknown values to `other`. A mixed-job shift is `delivery`, and each stop carries its own job type |
| `source` | `String(12)` + CHECK | `scheduled` (manager created it) · `template` (materialized from a template at start) · `ad_hoc` (no schedule, no template) |
| `template_id` | `BigInteger` NULL, composite FK → `fieldops.shift_templates` | which template, if any |
| `template_snapshot` | `JSONB` NULL | the template's values when used (an edit to the template never changes this shift) |
| `start_mode`, `start_hub_id`, `start_place_id`, `start_enforcement`, `start_radius_m` | `RouteEndpointsMixin` | **resolved** start (§5.1) |
| `end_mode`, `end_hub_id`, `end_place_id`, `end_enforcement`, `end_radius_m` | same | **resolved** end. Checked at end; an end is never blocked (enforcement above `advisory` downgrades to "flag") |
| `start_distance_m`, `end_distance_m` | `Numeric(10,1)` NULL | headline of each check (like `visits.distance_from_target_m`) |
| `end_check` | `String(20)` + CHECK (`CheckResult`), default `not_configured` | mirrors the existing `start_check` |
| `hub_id` | `Integer` NULL, FK → `hubs.id` | the user's **assigned hub for `shift_date`**, frozen at materialization (§5.7). It feeds the `hub` policy dimension |
| `assigned_by` | `BigInteger` NULL | manager who scheduled it |
| `auto_close_at` | `DateTime(tz)` NULL | the computed cap (§5.8), stored so the app's zombie alarm and the server agree |

The existing `planned_start_at` / `planned_end_at` are reused. Migration: all nullable or defaulted, no backfill
(existing rows: `source='ad_hoc'`, endpoints `anywhere`). `ShiftStatus` gains **`missed`** (a scheduled shift never
started, §5.8).

**Why place references, not lat/lng columns.** The API accepts a place uuid, a hub, or raw
`{latitude, longitude, address}` (geo find-or-create with the geohash8 near-duplicate probe). Coordinates are
returned in every response but stored once, in `geo.places`. Otherwise a hub's coordinates get copied onto 300
shifts a month and diverge the day the hub moves.

### 5.2 Manager API (new, `/api/fieldops/…`)

| Route | Perm | Notes |
|---|---|---|
| `POST /shifts` | `fieldops.shift:create` (**new code** in `rbac/catalogue.py`) | create one scheduled shift for `user_id`. Body: `user_id`, `planned_start_at`, `planned_end_at`, `title`, `work_type`, `template` (optional code/uuid; fills whatever the body omits), `start` / `end` as `EndpointSpec` (§5.1): `{mode: anywhere}` \| `{mode: hub, hub_id}` \| `{mode: assigned_hub}` \| `{mode: place, place_uuid}` \| `{mode: place, latitude, longitude, address?}`, each with optional `enforcement`, `radius_m`; `notes`; `uuid` optional (idempotent create). The user's hub for the date is frozen into `hub_id` |
| `POST /shifts/bulk` | same | ≤ 200 items, all-or-nothing by default (the RBAC bulk rule), per-item authorization at the target user's organization |
| `PATCH /shifts/{ref}` | `fieldops.shift:update` | extend `ShiftCorrectIn`. While `scheduled`, the plan fields are editable (no `reason` needed). Once started, the existing correction rules apply |
| `POST /shifts/{ref}/cancel` | `fieldops.shift:update` | `scheduled` → `cancelled` (transition recorded) |

Rules: a target user may have several scheduled shifts, but **not two overlapping planned windows** (service check, 409
`shift_overlaps`). `planned_end_at > planned_start_at`. The `policy_snapshot` is **not** taken at scheduling; it is taken
at **start** (the rules in force when work begins). `scope.visible` applies: a team manager can schedule only for
users they can see.

### 5.3 Starting a scheduled shift, and the start location

`POST /me/shifts` with `uuid = <scheduled shift's uuid>`:

1. `existing.status == 'scheduled'` and `existing.user_id == me` → **adopt it**: run all start rules (consent, location,
   selfie, odometer), then transition `scheduled → active`. Today a uuid hit is treated as a replay; the replay rule
   remains for `status != 'scheduled'`.
2. Start window: work is never blocked by the clock. Earlier than `planned_start_at − start_early_minutes`
   (setting `shift.window`, default 60) → accepted with anomaly `early_start`. Later than
   `planned_start_at + late_start_grace_minutes` → accepted with anomaly `late_start` (new `AnomalyType`). After
   `planned_end_at` → 409 `shift_window_closed` (the plan is over; the shift becomes `missed`, §5.8).
3. **Location capture.** The `fix` (or `manual_location`) is required, as today. It is written as the `shift_start`
   checkpoint in the stream.
4. **Start-place verification** against the shift's **resolved** start endpoint (§5.1: explicit > journey plan >
   beat > template > anywhere). `anywhere` → `start_check = not_configured`, no check. Otherwise the target is the
   hub's fence/place or the place, and enforcement is `start_enforcement` (NULL = record only, `advisory`). Call
   `verify.evaluate(..., enforce=True)` (today it is `enforce=False`). The same rules as visits apply:
   * `advisory` → recorded.
   * `soft_block` → needs `justification`. `ShiftStartIn` gains `justification: JustificationIn | None` (reused).
   * `hard_block` → 422 `outside_geofence` **online**. A start that happened offline is **never refused**: it is
     accepted with anomaly `hard_block_bypassed_offline` and review pending (the existing doctrine; `clock.py`'s
     `time_basis` and the receipt gap tell the two apart).
   * `uncertain` / `no_fix` follow the existing enforcement matrix (`verification.py`).
   * `shift.start_check`, `start_distance_m` ← the verdict. The full record is a `location_checks` row
     (`subject_type='shift'`, `phase='start'`).
5. Starting with a **new** uuid follows the order in §5.6: a scheduled shift whose window contains now → 409
   `scheduled_shift_exists` with its uuid. Otherwise the resolved template is materialized. Otherwise
   `shift.requirements.allow_unscheduled_shifts` → ad hoc. Otherwise 409 `no_shift_available`.

The end mirrors this against the resolved end endpoint (`end_check`, `end_distance_m`), and is **never blocked**:
any enforcement at end only records and flags.

### 5.4 Stops = planned visits

A DLP stop is a `fieldops.visits` row with `status='planned'`, `purpose='delivery'`, `shift_id` = the scheduled shift,
`place_id`, `sequence_in_plan`, `planned_start_at`/`planned_end_at` (the delivery window), and `account_type/account_id`
= the customer. All of these columns already exist. Needed additions:

* `POST /api/fieldops/shifts/{ref}/stops` (bulk, ordered), `PATCH/DELETE /api/fieldops/visits/{ref}` while
  `planned`. Perm `fieldops.visit:create` (new).
* `POST /api/me/visits/{uuid}/start` — **adopt a planned visit**. This is today's start logic without creating a row:
  verification and enforcement against the stop's place, and the `fix` is the proof-of-delivery capture.
* `visits.stop_code` (`String(40)`, optional human ref, e.g. the Zoho invoice/package number) and
  `visits.external_ref` (`String(100)`, the order/shipment id from the delivery module when it lands).
* `mark_missed_visits` already handles stops whose window passed.

> Scope note: the delivery *documents* (invoice, package, PoD signature, PoP) belong to the future deliveries module.
> Visits stay the **where/when/proof** container, and tasks (`deliver`, `collect_payment`) point **out** to those
> documents through `reference_*`, as `task_types.py` already intends. Do not put delivery business columns on visits.

### 5.5 What the app reads

**`GET /api/me/shifts`.** Add filters `status`, `date_from`, `date_to`, `upcoming=true` (scheduled with
`planned_start_at >= today_start`). Order: open → scheduled by `planned_start_at` → closed by `shift_date desc`.
`ShiftSlim` gains:

```json
{
  "uuid": "…", "shift_code": "SH-20261006-0042", "title": "Morning delivery — Halol route 3",
  "work_type": "delivery", "status": "scheduled", "source": "scheduled", "shift_date": "2026-10-06",
  "template": null, "hub": {"id": 3, "code": "HUB-HAL-01", "name": "Halol Hub"},
  "planned_start_at": "…", "planned_end_at": "…", "auto_close_at": "…", "started_at": null, "ended_at": null,
  "start_location": {
    "mode": "hub", "place_uuid": "…", "name": "Halol Hub", "address": "GIDC, Halol, Panchmahal 389350",
    "latitude": 22.5021, "longitude": 73.4712,
    "radius_m": 100, "geofence_enforcement": "soft_block", "geofence_uuid": "…"
  },
  "end_location": {"mode": "anywhere"},
  "stops_total": 18, "stops_completed": 0,
  "start_check": "not_configured", "start_distance_m": null,
  "paused_since": null, "pause_count": 0, "wall_clock_minutes": null, "paid_minutes": null
}
```

* `start_location` is resolved with **one** query for the page: `place_id IN (…)` joined to the active fences, via
  `selectinload`-style batching in `crud`. `stops_*` comes from one `GROUP BY shift_id` query. This keeps the existing
  "query count does not grow with rows" rule; add it to the N+1 test.
* `captured_start` (`{latitude, longitude, accuracy_m, recorded_at}` of the `shift_start` checkpoint) is on
  **`ShiftOut` only** (detail). It is read from the stream by `shift_id` + label (index `ix_location_pings_shift`).

**`GET /api/me/shifts/{uuid}` (new, detail).** Returns `ShiftOut` + `captured_start`/`captured_end`, the stops
(`VisitSlim` + place summary, ordered by `sequence_in_plan`), and the **fence pack**:
`[{geofence_uuid, place_uuid, latitude, longitude, radius_m, kind: "stop"|"start"|"end"}]`. Circles only, because
Android's `GeofencingClient` only does circles. For a polygon fence the server sends its minimum enclosing circle and
still verifies on the polygon. Android registers these with `requestId = geofence_uuid` (≤ 100 per app, the Android
limit, so only the next N stops are sent when there are more). This is the "fence pack" listed as not built in the
fieldops README §9.

---

### 5.6 Shift templates: the default when nobody scheduled a shift

**The requirement.** When a manager has not created a shift for a user, the organization still wants one: for THPL,
"Work Shift", 09:00–21:00 IST, for the `member` role (or organization-wide). Its start and end can later be pinned to
a hub or place, with or without geofencing.

**Architecture: a template is data; who gets it is a policy setting.** There are three parts, and each does one job:

1. **`fieldops.shift_templates`** holds *what a shift looks like*: the window, the work type, the endpoints. It has
   no targeting columns (no `role_id`, no `beat_id`).
2. **Policy setting `shift.template`** (a template reference, in the §4 registry, binding `frozen`, allowed scopes
   organization / role / team / hub / beat / user) decides *who gets which template*. "Organization-wide" is an
   organization layer. "For `member`" is a role layer. A user exception is a user layer. Per beat comes for free when
   beats land. A `null` value at a narrower layer switches templates **off** for that audience (e.g. managers).
   **No second targeting mechanism exists.** Templates reuse the precedence, locks, explain endpoint and caching
   of §4.
3. **Materialization** (below) turns the resolved template into a real shift **at the moment it is needed**.

**`fieldops.shift_templates`** (ENTITY: `BigIntPKWithUUIDv7Mixin`, `OrgEntityMixin`, `SoftDeleteFilteredMixin`,
`RouteEndpointsMixin`). Defined at an organization, usable by its subtree:

| Column | Notes |
|---|---|
| `code` | `String(40)`, partial unique per tenant (`WORK_SHIFT`). The seeder and the API reference it by code |
| `name` | "Work Shift" (becomes the shift `title` unless a pattern is set) |
| `title_pattern` | optional, e.g. `"{name} — {date:%d %b}"` |
| `work_type` | `ShiftWorkType` |
| `start_local_time`, `end_local_time` | `Time`, e.g. 09:00 and 21:00 |
| `end_day_offset` | `SmallInteger` 0/1, for overnight templates (22:00 → 06:00 next day) |
| `timezone` | IANA, NULL = the organization's timezone. **Explicit `Asia/Kolkata` for THPL**, so a timezone change on a branch never silently moves the window |
| `days_of_week` | `SmallInteger[]` ISO 1–7, default all days (weekly off-days via a narrower template or leave, later) |
| `start_*`, `end_*` | `RouteEndpointsMixin`, default `anywhere`, no enforcement |
| `valid_from`, `valid_until` | dates; status `active`/`inactive` |

CHECKs: `start_local_time <> end_local_time OR end_day_offset = 1`, window ≤ 24 h, days non-empty and within 1–7.
The planned duration (12 h for 09–21) must be ≤ the resolved `shift.window.max_shift_hours`. This is checked at
materialization rather than write time, since a role layer may lower it; violation → the cap wins and an anomaly
`template_exceeds_max_hours` is raised once per template.

**Materialization: lazy, plus a virtual preview.** There are two possible strategies:

| | Eager: nightly job writes a `scheduled` row per user per day | **Lazy (chosen): the template becomes a shift when the user starts** |
|---|---|---|
| Rows | one per user per day, including people on leave/off | only for days actually worked |
| Leave/holidays | must cancel rows; there is no leave module yet | nothing to cancel |
| Absence detection | `missed` rows show no-shows | not available until a roster exists |
| Change a template at 08:00 | rows already written must be rewritten | the next start simply uses the new template |

Eager generation only pays off when there is a leave/attendance module to reconcile with. Until then it would mostly
generate wrong rows. **Lazy is the default.** An eager "publish roster" job (`generate_rostered_shifts(from, to)`)
is listed as a later option, reusing the same `materialize()` function. It is not built now.

How lazy materialization works:

* **`GET /api/me/shifts?upcoming=true`** returns real scheduled shifts plus, for today (and tomorrow, if the
  template's window starts within 12 h), **one virtual entry** for any day with no real shift:
  `{"uuid": null, "source": "template", "template_uuid": "…", "title": "Work Shift", "planned_start_at": "…T03:30:00Z", "planned_end_at": "…T15:30:00Z", "start_location": null, …}`.
  The app renders it like any shift. The `null` uuid tells it to supply its own when starting.
* **`POST /me/shifts`** with a **new** uuid → `start_shift` resolves, in order:
  1. a real **scheduled** shift for this user whose window contains now (± `start_early_minutes`) → **409
     `scheduled_shift_exists`** with its uuid (start that one; the explicit plan wins over the template);
  2. else the resolved `shift.template` → **materialize**: compute today's occurrence in the template's timezone,
     resolve endpoints (§5.1), freeze `hub_id` (§5.7), set `planned_start_at/end_at`, `title`, `work_type`,
     `source='template'`, `template_id`, `template_snapshot`, then run the normal start rules (consent, fix,
     start-place check with the resolved enforcement);
  3. else `shift.requirements.allow_unscheduled_shifts` → `source='ad_hoc'` (today's behaviour);
  4. else 409 `no_shift_available`.
* **Which occurrence.** The occurrence on the organization-local date of the start, if
  `now < occurrence.end`. If the user starts after that occurrence's end (e.g. 21:30 for a 09–21 template), it is
  not a template shift: rule 3 or 4 applies. If the start is earlier than `planned_start − start_early_minutes`
  (e.g. 07:30 with the default 60), the shift is still created (never block work), with planned times from the
  template and anomaly `early_start`. A DA who starts at 11:00 gets a late start: `planned_end_at` stays 21:00 and
  anomaly `late_start` is raised.
* `ShiftOut` exposes `source`, `template` (`{uuid, code, name}`), and `auto_close_at`.

### 5.7 The user's hub for a day

The `hr.employment_records.hub_id` hub is static. The user says the hub **is assigned, can change daily, and can be
null**. Add a date-effective assignment table in the **hubs** module (hubs owns the concept; fieldops only reads it,
which keeps fieldops a leaf):

**`hubs.user_hub_assignments`** (ENTITY: `BigIntPKWithUUIDv7Mixin`, `OrgEntityMixin`, `SoftDeleteFilteredMixin`):
`user_id`, `hub_id`, `valid_from DATE`, `valid_to DATE NULL` (NULL = open-ended), `source`
(`manager` | `roster` | `hr_default`), `note`. An `EXCLUDE USING gist (tenant_id WITH =, user_id WITH =,
daterange(valid_from, valid_to, '[]') WITH &&) WHERE deleted_at IS NULL` constraint prevents two assignments covering
one day. This is the same temporal-exclusion technique as `geo.place_links` single-valued links. A one-day move is a
row with `valid_from = valid_to = that day`. Writing it **splits** an open-ended assignment: the service closes the
existing row at D−1 and re-opens it from D+1, in one transaction.

**Resolution `hub_for(user, date)`:** an assignment covering the date, else `employment_records.hub_id`, else
**NULL**. A NULL hub is valid: a hub-mode `assigned_hub` endpoint then degrades to `anywhere` (§5.1), and no hub policy
layer applies.

**Where it is used:** frozen onto `shifts.hub_id` at materialization (scheduled shifts get it when scheduled, then
re-read at start if the shift's own hub is still NULL), the `hub` policy dimension (answers former Q11), the
`assigned_hub` endpoint mode, and manager filters on the dispatch board.

**API:** `GET/POST /api/hubs/assignments` (bulk by day: `[{user_id, hub_id|null, date}]`, where null is an explicit
"no hub that day"), `GET /api/me/hub?date=`. Perm `hubs.assignment:manage` (new).

### 5.8 Auto-close: what it does today, and what changes

**There is no midnight job.** `auto_close_shifts` runs **every 5 minutes** and closes an open shift once now is past
its cap:

```
cap = (planned_end_at  OR  started_at + max_shift_hours) + auto_close_grace_minutes      # today
effective_end = min(max(last trusted activity, started_at), cap)
```

Today an ad-hoc shift started at 09:00 closes at about **22:00** (12 h + 60 min grace), and its recorded end is the
last trusted ping, not 22:00. Shift dates are frozen at start, so a shift that crosses midnight is not split. With
templates, these changes are needed:

1. **Bound the cap by both limits.** Today a `planned_end_at` replaces the max-hours cap entirely, so a bad schedule
   (or a template ending at 21:00 started at 06:00) can exceed `max_shift_hours`. New rule:
   `cap = min(planned_end_at + overtime_allowance, started_at + max_shift_hours) + grace`, with
   `shift.window.overtime_minutes` (default **0**, so a template shift auto-closes at planned end + grace; set 60 to
   allow an hour's overtime before the grace starts).
2. **Store `auto_close_at`** when the shift starts, and recompute it when a manager corrects `planned_end_at` or the
   shift is paused (pause time does not extend the cap unless `pause.rules.extends_cap`; default false). Android's
   `ACTION_FORCE_END_SHIFT` alarm uses **this value**, not its own `startedAt + max_shift_duration_hours`. The
   pre-end reminder fires at `planned_end_at − pre_end_reminder_minutes`. The client and server zombie guards then
   agree.
3. **Scheduled shifts that never start:** the same task moves `scheduled` → **`missed`** once now >
   `planned_end_at + grace` (transition recorded, anomaly `missed_shift`). Without this, unstarted scheduled shifts
   would accumulate forever. Template days produce no row, so nothing goes missed for them (no-show detection needs a
   roster, §5.6).
4. The `auto_close_shifts` query gets `auto_close_at <= now()` as its predicate (index
   `ix_shifts_open (auto_close_at) WHERE status IN ('active','paused')`) instead of computing caps per row in SQL.

### 5.9 THPL seed

A new idempotent seeder step, `[5/5] fieldops.defaults` in `scripts/seed.py` (module `app/modules/fieldops/seed.py`).
It follows the documents-seed rule: **create if missing, never overwrite an edited row** (matched by `code`):

| Object | Values |
|---|---|
| Shift template `WORK_SHIFT` @ root organization `THPL` | name **"Work Shift"**, `work_type = other`, 09:00 → 21:00, `end_day_offset = 0`, timezone `Asia/Kolkata` (from `COMPANY_TIMEZONE`), all days, start `anywhere`, end `anywhere`, no enforcement |
| Policy layer "THPL members" (`scope_type = role`, role `member`, organization THPL) | `shift.template = WORK_SHIFT`; `shift.window = {max_shift_hours: 12, overtime_minutes: 0, auto_close_grace_minutes: 60, start_early_minutes: 60, …}`; `session.field = {max_sessions: 1, on_new_login: revoke_previous, drain_grant_hours: 24}` |
| Policy layer "THPL default" (`scope_type = organization`, THPL root) | the code defaults made explicit (so admins see and edit them in the UI), plus `consent.required = true` **locked** |

Later, to make the template start at a hub with geofencing:
`PATCH /api/fieldops/shift-templates/WORK_SHIFT {"start": {"mode": "hub", "hub_id": 3, "enforcement": "soft_block"}}`.
Or use `{"mode": "assigned_hub", …}` so each DA is checked against their hub of the day.

The seed runs for the company tenant (`COMPANY_TENANT_CODE`); the template code and times are constants in the seed
module. Per `seeding-vs-test-database`, the pytest DB is never seeded. Tests build their own templates/layers.

**Template API** (`/api/fieldops/shift-templates`, perms `fieldops.shift_template:read|create|update|delete`, new):
CRUD + `GET /{ref}/preview?user_id=&date=` (the shift that would materialize, with resolved endpoints and
auto-close time). Endpoint specs in the body use `EndpointSpec` (§5.1).

## 6. Sessions and multi-device login

### 6.1 Current behaviour (verified)

* `/api/auth/login` issues an HS256 access token (24 h) and refresh token (30 d). There is **no session record, no
  `jti`/`sid`, and no revocation list**.
* So: logging in on Device B does nothing to Device A. Both get `200` until their tokens expire.
  `POST /api/auth/logout` only writes an audit entry; the token keeps working (`service.logout` docstring: "see the
  audit plan doc for server-side token revocation"). Refresh tokens are not rotated, so a stolen refresh token works
  for 30 days.
* This is **expected behaviour of the current code**, not a regression. It is still a gap for a compliance-sensitive
  field app.

### 6.2 Recommendation

**One active field-app session per user; multiple sessions everywhere else; configurable per organization/role.**
Reasons:

* The fieldops model already assumes one device. A shift is **bound to the device that started it**, and fixes from
  another device are flagged `FOREIGN_DEVICE` and excluded from evidence. Two signed-in phones means two tracking
  streams for one person, and half the proof gets discarded.
* "Clock in on my friend's phone" is the buddy-punching fraud the selfie and device binding exist to stop.
* Managers legitimately use web + phone at the same time. A global single-session rule would log them out constantly.

### 6.3 Design

**New table `auth.user_sessions`** (LEDGER-shaped, tenant-scoped, `BigIntPKWithUUIDv7Mixin` +
`MultiTenantMixin` + `AppMetaMixin` + `TimestampMixin`):

| Column | |
|---|---|
| `uuid` | the `sid` claim |
| `user_id` | FK users (composite tenant) |
| `client_type` | `field_app` \| `web` \| `service` (CHECK). From the login body `client` field, or inferred from `app_id` |
| `device_installation_id` | links to `fieldops.devices.installation_id` when known |
| `ip`, `user_agent` | from `ClientInfo` |
| `created_at`, `last_seen_at` | `last_seen_at` is updated at most once a minute (Redis-gated, so not a write per request) |
| `refresh_jti_hash` | sha256 of the **current** refresh token id (rotation) |
| `expires_at` | absolute session cap (`SESSION_MAX_DAYS`, default 30) |
| `revoked_at`, `revoked_reason` | `logout` \| `signed_in_elsewhere` \| `refresh_reuse` \| `admin` \| `password_changed` \| `user_deactivated` |
| `revoked_by_session` | the session that displaced it |

Index: `(tenant_id, user_id, client_type) WHERE revoked_at IS NULL`.

**Policy (decided: field work policies):** the setting `session.field` in the policy layers (§4.3) —
`{max_sessions: 1, on_new_login: revoke_previous | refuse, drain_grant_hours: 24}`. It is settable at organization,
role and user scope only, because login has no shift and therefore no hub/beat context. It is resolved at login with
the same resolver, through the cached path. Web/service sessions are unlimited (env `MAX_WEB_SESSIONS`, default 0 =
unlimited).

**Layering note.** `users` must not import `fieldops` (`.importlinter`: fieldops is a leaf). The login service
therefore asks through a small hook: `users/sessions.py` declares `SessionRuleProvider` (a Protocol, defaulting to
"unlimited"), and `fieldops` registers its provider at startup. With fieldops absent, logins behave as today.

**Flows**

* **Login** (`password`, `otp`, `refresh`-less): create a session. If `client_type = field_app` and live field
  sessions ≥ `max_field_sessions`:
  `revoke_previous` → revoke the older ones (`signed_in_elsewhere`, `revoked_by_session = new`), audit
  `auth.session_revoked`, push a best-effort Soketi event `session.revoked` to the old device.
  `refuse` → 409 `active_session_exists` with `data.device` (model, last_seen_at). The user can then call
  `POST /api/auth/sessions/takeover` with OTP/password re-confirmation.
* **Access token:** add `sid` and `jti` claims. Lifetime **15 min** (`JWT_EXPIRATION_HOURS` → new
  `JWT_ACCESS_MINUTES`; keep the old var as a fallback for one release).
* **Per-request check** in `users/deps._authenticate`: after `decode_token`, check `sid`. The fast path is the Redis DB 0
  key `auth:session:{sid}` (`"1"` live / `"r:<reason>"` revoked, TTL = access lifetime). Cache miss → DB lookup →
  cache. Revocation **writes the Redis key first, then commits**. Note this request path already does
  `crud.get_by_id(user)` every time; the session check adds one Redis GET.
  Revoked → **`401` with `code: "session_revoked"`, `data: {"reason": "signed_in_elsewhere", "at": "…"}`**. That is
  distinct from `401 token_expired` and `401 invalid_token`, so the app can show "You signed in on another device"
  instead of a generic error.
* **Refresh:** rotate on every use (new refresh `jti`; store its hash). If the *previous* refresh token is presented
  again (**reuse detected**), revoke the whole session (`refresh_reuse`). That is the standard theft signal.
* **Logout:** revoke the current session (fixes the bug in §1). `POST /api/auth/logout-all` revokes every session of
  the user.
* **Password change / admin deactivate:** revoke all sessions.
* **Authentik (RS256) tokens:** out of scope. Authentik owns those sessions. The web SSO path is unaffected.
* **Legacy tokens without `sid`:** accepted until they expire (≤ 24 h after deploy), then refused. This makes the
  rollout zero-downtime.
* **API:** `GET /api/auth/sessions` (mine: device, client, last seen, current flag), `DELETE /api/auth/sessions/{uuid}`.
  Admin: `GET/DELETE /api/users/{id}/sessions` (perm `users.session:revoke`, new).

### 6.4 The two field-specific edge cases

1. **Device A has an open shift when B logs in.** The login response includes `data.open_shift` (`uuid`, `device`,
   `started_at`). The app on B calls **`POST /api/me/shifts/{uuid}/handover`** (new). That rebinds
   `shifts.device_id` to B, records a transition, and raises an `info` anomaly `device_handover`. From then on B's
   pings are not `FOREIGN_DEVICE`. Without a handover, B's pings are accepted but flagged, which is today's behaviour.
2. **Device A's unsent queue after revocation.** These are the same user's pings and are legitimate evidence. A session
   revoked with reason `signed_in_elsewhere` keeps a **telemetry-drain grant** for 24 h. It is accepted **only** on
   `POST /me/location-pings` and `POST /me/device-events`, and only for fixes with `recorded_at` ≤ `revoked_at`. All
   other routes return the 401. The Android rule: on `401 session_revoked`, stop the FGS, attempt one final drain
   upload, then clear credentials and show the message. If you don't want this complexity, the alternative is that A's
   last pings are lost. State this to ops before choosing (Q6).

### 6.5 What to tell the Android developer now

> Today the backend allows several active sessions, and logout does not invalidate the token. Device A keeps
> getting 200 after B logs in; that is current behaviour, not a bug in your app. We are adding one active field-app
> session per user. Once it ships, A's next call returns **401 with `code = "session_revoked"` and
> `data.reason = "signed_in_elsewhere"`**: stop tracking, try one final ping upload, clear tokens, and show "You signed
> in on another device". Treat `401` with any other code as "refresh, and if refresh fails, log out".

---

## 7. Privacy and notification settings (`GET/PATCH /api/me/settings`)

### 7.1 Today

Settings are stored in `users.application_settings` JSONB, and the Pydantic shape is in `users/schema.py`:

```
privacy.profile_visibility: "public" | "organization" | "contacts" | "private"   (default "organization")
privacy.show_email: bool (false) · privacy.show_phone: bool (false)
appearance.theme: "light" | "dark" | "system"
notifications.email (true) · push (true) · sms (false) · in_app (true)
```

**None of the privacy values is enforced**: no read path consults them. `GET /api/users/{id}` returns `UserOut` to the
user and to admins with `users.user:read`, and `UserPublicOut` (id, name, avatar) to everyone else, whatever the
setting. The values also don't match the screen (Everyone / My Team / Managers / Private, and a three-way contact
choice), and Slack is missing.

### 7.2 New vocabulary

| Setting | Values (wire) | UI label | Who can see |
|---|---|---|---|
| `privacy.profile_visibility` | `everyone` | Everyone | any signed-in user of my **tenant** (never cross-tenant, never anonymous) |
| | `team` | My Team | members of any team I belong to (`teams` memberships, approved) + `managers` |
| | `managers` | Managers | my reporting line (`manager` chain upward) + leads of my teams |
| | `private` | Private | only me |
| `privacy.contact_visibility` | `everyone` / `team` / `hidden` | Everyone / Team / Hidden | same audiences; `hidden` = only me |
| `notifications.{email,push,sms,slack,in_app}` | bool | Email / Push / SMS / Slack | — |

**Always visible regardless of setting:** the user, and holders of `users.user:read` at the user's organization
(HR/admin). Privacy settings cannot hide an employee from their employer's administrators, and the API says so
(`settings/options` → `admin_override: true`).

`private` hides the **profile details** (title, department, bio, avatar unless `show_avatar`), not the person's
existence. Assigning a shift or @-mentioning in comments still needs `id` + `name`. A colleague without access gets
`UserPublicOut` with `restricted: true`.

**Migration of stored values** (one data migration over `users.application_settings`):
`public → everyone`, `organization → everyone`, `contacts → team`, `private → private`.
`show_email OR show_phone` → `contact_visibility = everyone` if both were true; otherwise `hidden` (the old default
exposed nothing, so this keeps behaviour). For **one release**, `PATCH` still accepts the old values and normalizes
them (logged as `settings_legacy_value`). `show_email`/`show_phone` are kept as **read-only, derived** fields for
older clients, then removed.

### 7.3 Enforcement (`users/visibility.py`, new)

* `audience_of(viewer, subject) -> set[{"self","admin","manager","team","tenant"}]`, batched for a page with one
  query for team co-membership and one for the manager chain. It reuses the team/report logic already in
  `fieldops/scope.py` and `teams/scope.py`; extract the shared part into `teams/scope.py` rather than writing a third
  copy.
* `project(user, audience) -> UserPublicOut | UserOut`: applies `profile_visibility` (details) and
  `contact_visibility` (email, phone, WhatsApp) to the **directory** shape. Admins and the user themselves keep
  `UserOut`.
* Applied in `list_users`, `get_user`, the comments author block, and anywhere else `UserPublicOut` is built
  (`service.user_public_outs` is the single choke point, so it is one change).
* Tests: the audience matrix (4 profile × 3 contact × 5 viewer relations) as a table-driven pure test, plus an
  N+1 test on `GET /users`.

### 7.4 Notifications

* Add `slack: bool = False`. **No Slack dispatch exists** in this codebase (Resend email only; push token stored on
  `fieldops.devices`). The preference is stored and honoured once a Slack channel lands. `settings/options` reports
  each channel's **availability** (`available: false, reason: "not_configured_for_organization"`), so the app can grey
  it out instead of offering a toggle that does nothing.
* Mandatory notifications (security alerts, `session_revoked`, shift auto-closed) ignore opt-outs for **in_app/push**.
  The options catalogue marks them `locked: true`.

### 7.5 `GET /api/me/settings/options` (new) — the answer to "give me all possible values"

```json
{
  "privacy": {
    "profile_visibility": {"values": ["everyone","team","managers","private"], "default": "everyone",
                           "labels": {"everyone": "Everyone", "team": "My Team", "managers": "Managers", "private": "Private"}},
    "contact_visibility": {"values": ["everyone","team","hidden"], "default": "hidden", "labels": {"…": "…"}},
    "admin_override": true
  },
  "notifications": {
    "channels": [
      {"key": "email", "available": true,  "locked": false},
      {"key": "push",  "available": true,  "locked": false},
      {"key": "sms",   "available": false, "reason": "not_configured_for_organization"},
      {"key": "slack", "available": false, "reason": "not_configured_for_organization"},
      {"key": "in_app","available": true,  "locked": true}
    ]
  },
  "security": {"two_factor": {"supported": false}}
}
```

Labels are localized through the existing `users/lang` catalogue (`Accept-Language`). Android maps by **key**, never
by label.

**Security / 2FA.** The `users` table has `two_factor_secret`, `two_factor_recovery_codes`, `two_factor_confirmed_at`,
but **there is no enrolment or verification endpoint**. The settings response exposes
`security.two_factor_enabled` (= `two_factor_confirmed_at IS NOT NULL`) **read-only**. Enabling it is a separate flow
(TOTP enrol → confirm → recovery codes) that must not be a boolean `PATCH`. Until that flow exists, the app should show
the toggle as disabled ("coming soon"). This is a separate work item (Q7).

---

## 8. Consent API (blocker B1)

`app/modules/compliance` has models only. Add the minimum:

* `GET /api/me/consents` — my consent records (type, given, version, consented_at, withdrawn_at).
* `POST /api/me/consents` — `{consent_type: "location_tracking", consent_given: true, consent_text_version,
  consent_language, purpose_text?}`. The server stamps `consented_at`, IP, and device info (from `X-Device-Session`).
  Idempotent per (user, type, version).
* `POST /api/me/consents/{type}/withdraw` — sets `withdrawal_requested_at`/`withdrawn_at`. **Withdrawing
  `location_tracking` during an open shift** ends the shift (`end_reason = 'consent_withdrawn'`, new
  `ShiftEndReason`) and stops tracking. Under DPDP, a withdrawal must not be ignored.
* `GET /api/me/fieldops/current` adds `consent: {location_tracking: {given, version, required_version}}`, so the app
  can prompt before the shift start fails.
* The 422 `location_consent_required` gains `data.required_version` and `data.consent_endpoint`.

---

## 9. Changes by layer

### Models / migrations (one migration, chained onto the current head; all reversible)

| Table | Change |
|---|---|
| `fieldops.location_pings` | +`geofence_id`, `geofence_uuid`, `app_state`, `battery_state`, `client_significant`, `client_distance_m`; CHECKs for the new enums + geofence label; `chk_location_pings_label` regenerated |
| `fieldops.shifts` | +`shift_code`, `title`, `work_type`, `source`, `template_id`, `template_snapshot`, `RouteEndpointsMixin` (10 columns), `start_distance_m`, `end_distance_m`, `end_check`, `hub_id`, `assigned_by`, `auto_close_at`; composite FKs to `geo.places`, `fieldops.shift_templates`; FK to `hubs`; `ShiftStatus` +`missed`; partial unique `uq_shifts_code_live`; `ix_shifts_scheduled (tenant_id, user_id, planned_start_at) WHERE status='scheduled'`; `ix_shifts_open` re-keyed on `auto_close_at` |
| `fieldops.shift_templates` | **new** (§5.6), `RouteEndpointsMixin` |
| `hubs.user_hub_assignments` | **new** (§5.7), temporal EXCLUDE per user |
| `fieldops.visits` | +`stop_code`, `external_ref` |
| `fieldops.policy_layers` | **new**, replaces `work_policies` (§4.5); data migration copies every row as a full layer (§4.9); `work_policies` dropped one release later after the parity check |
| `fieldops.policy_epochs` | **new** (`tenant_id` PK, `epoch`), seeded with 1 per tenant |
| `fieldops.shifts` (future, beats module) | +`beat_id`. Listed so the dependency is visible; not part of this migration |
| `auth.user_sessions` | **new** (schema `auth`; add to `tests/test_tenancy.py` classification as LEDGER) |
| `public.users` | data-only: normalize `application_settings.privacy` |
| enums | `CheckpointLabel` +2, `AnomalyType` +`tracking_silent`, `late_start`, `device_handover`, `foreign_user_ping`; `ShiftEndReason` +`policy_violation`, `consent_withdrawn`; new `ShiftWorkType`, `AppState`, `BatteryState`, `NetworkType`, `MockLocationAction`, `SessionClientType`, `SessionRevokeReason` |

Every new column on existing tables is nullable or has a server default, so there are no backfills except the settings
normalization. The partitioned `location_pings` parent takes `ADD COLUMN` without rewriting partitions. Check that
autogenerate emits the CHECK constraints on the **parent** only.

### Code

| Area | Files |
|---|---|
| wire mapper | `fieldops/wire.py` (new): `normalize_ping`, capture-reason table, owner check. Pure, unit-tested |
| ingest | `service/ingest.py`: call the mapper, resolve geofence uuids (one query), new columns in `build_row`, X1 fix |
| policy layers | `fieldops/policy/` (new package): `settings.py` (registry + Pydantic setting models), `dimensions.py` (scope registry), `resolver.py` (pure `fold` + one-query loader + Redis cache), `render.py` (Android JSON); `model/policy.py` (`PolicyLayer`, `PolicyEpoch`); `service/policy.py` becomes a thin façade (`resolve_policy`, `EffectivePolicy` alias table, layer CRUD, epoch bump, explain, preview); `api.py` (`/policy-layers`, `/policy-settings`, `/policies/resolve`, `/policies/preview`); `api_me.py` `GET /me/fieldops/config` (ETag); `users/sessions.py` `SessionRuleProvider` hook |
| scheduled shifts | `schema.py` (`ShiftScheduleIn`, `ShiftScheduleBulkIn`, `ShiftSlim`/`ShiftOut` additions, `LocationSummary`), `service/shifts.py` (`schedule_shift`, adopt-on-start, `enforce=True` start check, handover), `crud.py` (batched place/fence + stop counts), `api.py` (manager routes), `api_me.py` (`GET /me/shifts/{uuid}`, filters, handover) |
| stops | `service/visits.py` (`plan_stops`, `start_planned_visit`), `api.py`/`api_me.py` routes |
| templates & endpoints | `fieldops/endpoints.py` (`EndpointSpec`, `RouteEndpointsMixin`, `resolve_endpoints()` with the precedence chain), `model/template.py`, `service/templates.py` (CRUD, `materialize(user, date)` shared by lazy start and a future roster job, preview), virtual entries in `GET /me/shifts`, `fieldops/seed.py` + `scripts/seed.py` step `[5/5] fieldops.defaults` |
| hub of the day | `hubs/model.py` (`UserHubAssignment`), `hubs/service.py` (`hub_for(user, date)`, split-on-write), `hubs/api.py` (`/hubs/assignments`, `/me/hub`) |
| auto-close | `service/shifts.py` (`cap_of` = min(planned end + overtime, start + max hours) + grace, stored `auto_close_at`, recompute on correction), `app/tasks/fieldops.py` (`scheduled → missed`) |
| detectors | `app/tasks/fieldops.py` `detect_silent_shifts` + beat entry (restart celery-beat after deploy) |
| sessions | `users/sessions.py` (new: create/revoke/check, Redis cache), `common/security/jwt.py` (`sid`/`jti`, minutes TTL), `users/deps.py` (check), `users/service.py` (login/refresh rotation/logout), `users/api.py` (sessions routes), `conf.py` + `deployment/docker-compose.yml` env (`JWT_ACCESS_MINUTES`, `SESSION_MAX_DAYS`, `MAX_WEB_SESSIONS`) |
| privacy | `users/schema.py` (new literals, options DTO, legacy normalizer), `users/visibility.py` (new), `users/service.py` (`user_public_outs` applies projection), `teams/scope.py` (shared audience helpers), `users/lang` (labels) |
| consent | `compliance/schema.py`, `service.py`, `api.py` (new), router include |
| RBAC | `rbac/catalogue.py`: `fieldops.shift:create`, `fieldops.visit:create`, `fieldops.shift_template:read|create|update|delete`, `hubs.assignment:manage`, `users.session:revoke`; grant to `manager` template |

**Infra impact:** no new service, port, Redis DB, or image. Redis DB 0 gains the key prefix `auth:session:`.
Celery-beat gains one entry. Three new env vars must be listed in compose (the rule from RBAC memory).

### Tests (per testing doctrine)

* **Pure:** `normalize_ping` (every row of §3.1/§3.2, camelCase rejection, ns→ms, owner check). Policy `fold`:
  precedence table (scope rank × org depth × priority), per-setting inheritance (a role layer setting one key keeps
  HQ's others; this is the regression test for flaw 1 in §4.1), locks (write refusal and fold-time stop), team ties
  reported in `conflicts`, effective windows, defaults floor. Setting-model validation (bands descending to 0,
  `min ≤ base ≤ max`, ratios). Allowed-scope refusal (`session.field` on a hub layer → 422). Render to the Android
  JSON (golden file). A fake `beat` dimension registered in the test proves a new dimension needs no resolver change.
  Privacy audience matrix; legacy settings normalization; session revocation decision table.
* **Templates/endpoints (pure + integration):** occurrence selection (early, on time, late, after window end → ad hoc or 409, overnight `end_day_offset`, timezone Asia/Kolkata at a UTC day boundary); endpoint precedence (explicit > template > anywhere; `assigned_hub` with and without an assignment); scheduled-beats-template (`409 scheduled_shift_exists`); virtual entry in `/me/shifts?upcoming` disappears once materialized; `cap_of` matrix (planned end vs max hours vs overtime vs grace); `scheduled → missed`; hub assignment split-on-write and the EXCLUDE overlap refusal; seed idempotency (running twice changes nothing, an edited template is not overwritten).
* **Migration parity:** for seeded `work_policies` rows, the old `resolve_policy` and the layered resolver return
  identical values for every (organization, role) pair.
* **Integration** (scratch PG/Redis): schedule → list (`upcoming`) → start by uuid (adopt) → soft-block needs
  justification → offline hard-block accepted and flagged → end at `end_place`. Handover. Mock action matrix.
  Geofence enter ping with `geofence_uuid`. `GET /me/fieldops/config` 200 → 304 with ETag → policy PATCH → 200 with a
  higher version. Sessions: login A → login B → A gets `401 session_revoked` → A's drain upload accepted for old fixes
  only → logout revokes → refresh reuse kills the session. Consent give/withdraw (withdraw ends the shift).
* **N+1:** `GET /me/shifts` and `GET /fieldops/shifts` constant query count with `start_location` + stop counts;
  `GET /users` with visibility projection.
* **Route smoke:** new paths in `tests/test_health.py`; `tests/test_rbac_routes.py` passes (every new mutating route
  has `Perm`).
* `_TEST_TABLES` += `auth.user_sessions`, `consent_records` (if not already listed).

### Docs to update

`docs/fieldops/README.md` (§3 API, §6 policies, §9 "not built" → fence pack built), `docs/MODULES.md`,
`docs/PROJECT_STRUCTURE.md`, `docs/rbac-module.md` (new permission codes), a new `docs/fieldops/android-contract.md`
for the Android team (headers, ping mapping, config JSON v5, error codes, session 401 handling), and
`docs/geo/README.md` (shift start/end places as `place_links` owners? No: shifts reference places directly, like
visits do. Note that).

---

## 10. Rollout order

1. **Unblock (small, ship first):** consent API (§8); X1/X2 fixes; tell Android to send `PingDto` (snake_case), the
   `X-Device-*` headers, and UUIDs for `shift_id`. This is days of work, and it makes today's endpoints usable.
2. **Sessions** (§6): independent of fieldops, closes a security gap, and the Android 401 handling should land early.
3. **Scheduled shifts + route endpoints + hub-of-the-day + auto-close changes + `/me/shifts` fields** (§5.1–5.3,
   5.5 list, 5.7, 5.8).
4. **Policy layers** (§4): tables + registry + resolver + migration from `work_policies` with the parity check, then
   `GET /me/fieldops/config`, the mock action (§3.6), and the wire mapper/new ping columns (§3). Sessions (step 2)
   ship first with the "unlimited unless configured" hook default, and `session.field` starts applying when this
   step lands. Until then, single-session is enforced via env `FIELD_MAX_SESSIONS=1` as a stopgap.
   Then **shift templates + the THPL seed** (§5.6, §5.9). They depend on the layers, because `shift.template` is a
   layer setting.
5. **Stops/planned visits + fence pack + geofence events + silence detector** (§5.4, 5.5 detail, §3.7).
6. **Privacy settings vocabulary + enforcement + options** (§7). This can run in parallel with 3–5, since it is
   independent.

---

## 11. Open questions (answers change what gets built)

**Decided (2026-10-06):**

| # | Decision |
|---|---|
| D1 | Configuration = **policy layers** (§4), replacing `work_policies`; beats are a future dimension |
| D2 | `work_type` = `delivery`, `collection`, `return`, `exchange`, `other` |
| D3 | Android accepts **battery bands v5**; only v5 is rendered |
| D4 | The session rule lives in the field work policies (`session.field` setting) |
| D5 | Sessions (§6), scheduled shifts (§5) and privacy settings (§7) go ahead as recommended, including the 24 h telemetry-drain grant (§6.4) |
| D6 | A DA does not always start at a hub. Start and end are each `anywhere` (default) / `hub` / `assigned_hub` / `place`, one shared `EndpointSpec` reused by beats and journey plans (§5.1) |
| D7 | The hub is assigned per day and can be NULL: `hubs.user_hub_assignments` (§5.7) |
| D8 | Shift **templates** (organization- or role-wide) cover days with no scheduled shift; THPL seed "Work Shift" 09:00–21:00 IST for `member`, no endpoints, no geofencing (§5.6, §5.9) |
| D9 | Single session per user stays configurable by role (`session.field` scopes: organization, role, user); seeded `max_sessions = 1` for THPL `member` |
| D10 | 2FA is not implemented now: settings expose a read-only `two_factor_enabled`, and the app shows the toggle disabled |
| D11 | `profile_visibility = everyone` is **tenant-wide** |

**Still open:**

| # | Question | Default if unanswered |
|---|---|---|
| Q4 | Should client tuning changes apply mid-shift (live), or only from the next shift (frozen)? | per-setting `binding` in the registry (§4.3): obligations frozen, tuning live |
| Q10 | Precedence: scope rank before org depth (§4.2), so a branch's *general* default never overrides HQ's *role* rule. Is that the intended governance? | scope rank first |
| Q12 | Are additional `work_type` values expected soon? The "etc." in the answer suggests so | closed enum, extended by migration |
| Q13 | "Start and end both cannot be anywhere": is that a **rule** (at least one side concrete), or does it mean they are configured independently? The plan assumes independent, both defaulting to `anywhere` (§5.1) | independent |
| Q14 | Should a template shift auto-close exactly at planned end + grace (`overtime_minutes = 0`), or allow overtime first? | 0 overtime, 60 min grace (closes ~22:00 IST) |
| Q15 | THPL "Work Shift" `work_type`: `other` (generic), or `delivery`? | `other` |
| Q9 | Retention: the guide says local SYNCED purge 3–7 d; server `location_history` is 180 d with auto-purge **off** (DPDP decision). Confirm 180 d for DAs too? | 180 d, auto-purge off |

---

## 12. Definition of done

- [ ] Every new column is nullable or has a server default. The partitioned parent ALTER is verified on scratch with
      existing partitions (upgrade → downgrade → upgrade).
- [ ] Uniqueness on soft-deletable tables is partial (`uq_shifts_code_live`, policy target index).
- [ ] No coordinates stored outside `geo.places` / the stream (shift start/end are place references).
- [ ] Every new relationship has a stated loader strategy (`start_place`/`end_place`: batched in crud, no ORM
      relationship; sessions: none). Every list endpoint has a `load_only` slim path and an N+1 test.
- [ ] One config system (`policy_layers` + the settings registry), one ping schema (`PingIn` + mapper), one auth dependency (`_authenticate`)
      — no parallel paths.
- [ ] Logging via `structlog.get_logger("app.fieldops.<area>")` / `"app.users.sessions"` with structured kwargs.
- [ ] New permissions in `rbac/catalogue.py`; `test_rbac_routes.py` green.
- [ ] New env vars in `.env.example`, `conf.py`, and `deployment/docker-compose.yml`; celery-beat restarted after deploy.
- [ ] Docs in §9 updated, and `android-contract.md` handed to the Android team.
