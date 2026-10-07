# Field app ↔ backend contract (Android)

**For:** the Android team · **Status:** live on the dev stack (2026-10-06) · Every response is the envelope
`{code, msg, data, request_id}` — read `data`; branch on `code`, never on `msg`.

## 1. Sign-in and sessions

```http
POST /api/auth/login
{"identifier": "ravi@…", "password": "…", "client_type": "field_app",
 "device_type": "android", "device_id": "<model>", "installation_id": "<your install id>"}
→ {access_token, refresh_token, expires_in, session_uuid, displaced_sessions}
```

* One active field-app session per user (THPL `member`). Signing in on device B ends device A's session:
  A's next call returns **`401 {code: "session_revoked", data: {reason: "signed_in_elsewhere",
  revoked_at, drain_until}}`**. On that code:
  1. stop the tracking service;
  2. make **one** final `POST /api/me/location-pings` with the queued fixes — allowed until `drain_until`
     for fixes recorded **before** `revoked_at` (later ones are rejected per item);
  3. clear tokens and show "You signed in on another device".
* Other `401` codes (`unauthorized`): refresh; if refresh fails, log out.
* Refresh **rotates**: always store the new `refresh_token`. Serialize refreshes; a duplicate of the
  previous token within 30 s is tolerated (parallel requests), but re-using an old one later ends the
  session (`reason: refresh_reuse`).
* `POST /api/auth/logout` ends this session; `GET /api/auth/sessions` lists my devices.
* If B signs in while a shift is open on A: `GET /api/me/fieldops/current` shows it; call
  `POST /api/me/shifts/{uuid}/handover` from B (with B's `X-Device-Session`).

## 2. Headers on every field call

| Header | Value |
|---|---|
| `X-Device-Session` | session uuid from `POST /api/me/devices` (call on every app launch) |
| `X-Device-Sent-At` | wall clock at send, ISO-8601 with offset |
| `X-Device-Elapsed-Ms` | `SystemClock.elapsedRealtime()` at send |
| `X-Device-Boot-Count` | `Settings.Global.BOOT_COUNT` |
| `X-Idempotency-Key` | a uuid per mutation (start/end shift, start/end visit) |

Business time is derived from the fix's `elapsed_realtime_ns` chained to these headers — offline actions keep
their real time and clock tampering is detected. Without the headers times degrade to the raw device clock.

## 3. Configuration

`GET /api/me/fieldops/config` → `LocationConfig` **v5** (the v4 shape, with `battery_thresholds` as ordered
bands: `[{min_pct: 30, interval_seconds: 45}, {min_pct: 15, …: 120}, {min_pct: 0, …: 600}]` — pick the first
band whose `min_pct ≤ battery`). Send `If-None-Match: <ETag>`; `304` = unchanged. Apply a config when
`config_version >= applied` and the ETag changed. `config_version` is a large, time-based number (minutes
since 2020, e.g. 3557979) — it fits a 32-bit Int. Also returned: `shift_boundaries.auto_close_at` — use it for
the force-end alarm (not `startedAt + max_shift_duration_hours`).

## 4. Consent (before the first shift)

`GET /api/me/fieldops/current` → `consent.location_tracking: {given, version, required}`. If required and not
given: `POST /api/me/consents {"consent_type": "location_tracking", "consent_text_version": "1.0",
"consent_language": "en"}`. Withdrawal (`POST /api/me/consents/location_tracking/withdraw`) ends the open shift.

## 5. Shifts

* `GET /api/me/shifts` — open, then scheduled, then history. An item with **`uuid: null`, `source: template`**
  is today's template shift (e.g. "Work Shift 09:00–21:00"): start it with **your own** UUIDv7.
* Each item: `shift_code`, `title`, `work_type` (`delivery` · `collection` · `return` · `exchange` · `other`),
  `planned_start_at` / `planned_end_at`, `auto_close_at`, `hub`, `start_location` / `end_location`
  (`mode` anywhere/hub/place, `name`, `address`, `latitude`, `longitude`, `radius_m`, `geofence_enforcement`),
  `stops_total` / `stops_completed`. Durations/distances are JSON numbers.
* `GET /api/me/shifts/{uuid}` — plus `captured_start`, the `stops`, and the **fence pack** (`fences`: register
  each with `GeofencingClient`, `requestId = fence_id`).
* Start: `POST /api/me/shifts {"uuid", "occurred", "fix"}` (scheduled shift → its uuid). Errors to handle:
  `409 scheduled_shift_exists` (start `data.shift_uuid`), `409 no_shift_available`, `422 location_consent_required`,
  `422 justification_required` (retry with `justification: {code, note}`), `422 outside_geofence`,
  `422 mock_location_rejected`, `409 shift_not_yet_startable` (a shift scheduled for a later day),
  `409 shift_window_closed`.
* The drain grant (§1) judges fixes by their monotonic time — send `boot_count` on fixes and
  `X-Device-Boot-Count`, or backdated wall-clock times are all the server can go on.
* End: `POST /api/me/shifts/{uuid}/end {"fix"}` — never blocked by location.

## 6. Stops (proof of delivery)

"Start Delivery": `POST /api/me/visits/{stop_uuid}/start {"fix": <high-accuracy one-shot>, "occurred"}` ·
"End Delivery": `POST /api/me/visits/{stop_uuid}/end {"fix", "outcome": "delivered"}`. Use the **same uuid**
for that fix and its queued ping copy — the copy becomes a harmless duplicate. Double taps are safe (same
visit uuid + `X-Idempotency-Key`).

## 7. Location pings

`POST /api/me/location-pings {"uuid": <batch uuid>, "pings": [≤ 500]}` → always `200` with per-item results;
drop `accepted` and `duplicate` items, drop `rejected` ones too (they cannot succeed on retry).

Send **`PingDto`** (guide §6) in **snake_case** — not the Room entity. Mapping applied by the server:

| You send | Becomes | Notes |
|---|---|---|
| `ping_id` | `uuid` | UUIDv7 |
| `da_id` | — | must be you (user id or employee code), else `user_mismatch` |
| `shift_id` / `stop_id` | shift / visit uuid | **UUIDs** from the API, not `SHIFT-…` strings |
| `capture_reason` | kind + label | `interval`, `shift_start`, `shift_end`, `start_delivery`, `end_delivery`, `geofence_enter`, `geofence_exit` |
| `geofence_event.geofence_id` | `geofence_uuid` | the `fence_id` from the fence pack |
| `captured_at` | device time | ISO-8601 (or epoch **ms**) |
| `elapsed_realtime_ns` | ms | |
| `accuracy`, `bearing`, `speed`, `is_mock_location` | `accuracy_m`, `heading_deg`, `speed_mps`, `is_mock` | |
| `battery_state`, `app_state`, `network_type`, `activity_*`, `is_significant`, `distance_from_last_m` | stored | client hints are diagnostics only |
| `received_at`, `device_model`, `os_version`, `app_version_code` | dropped | server-set / sent once on `POST /me/devices` |
| `syncStatus`, `syncAttempts`, `createdAtEpochMs`, any camelCase | **rejected** | "unknown fields: …" |

Mock fixes are always stored (flagged); depending on policy the shift may be closed (`policy_violation`).
Note: the example `capturedAtEpochMs: 17860370863000` has one digit too many (year 2536).

## 8. Profile privacy

`GET /api/me/settings/options` lists every value with a label (map by `value`):
`profile_visibility` = `everyone` (Everyone) · `team` (My Team) · `managers` (Managers) · `private` (Private);
`contact_visibility` = `everyone` · `team` · `hidden`; notification channels `email` · `push` · `sms` ·
`slack` · `in_app` with `available`; `two_factor_supported: false` (show the 2FA toggle disabled).
`GET/PATCH /api/me/settings` (send only what changed). Old values (`organization`, `public`, `contacts`,
`show_email`, `show_phone`) are still accepted and converted.
