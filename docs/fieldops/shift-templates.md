# Shift templates, scheduled shifts, route endpoints and the hub of the day

**Status:** ✅ built (2026-10-06) · **Migration:** `c3d9a7e2f415` · **Tests:** `tests/test_fieldops_shift_plan.py`
· **Code:** `model/template.py`, `endpoints.py`, `service/templates.py`, `service/shifts.py`, `cards.py`,
`app/modules/hubs/assignments.py`

## 1. Where a shift's plan comes from

`POST /api/me/shifts` with:

| uuid | Result |
|---|---|
| a **scheduled** shift's uuid (from `GET /me/shifts`) | that shift starts (`scheduled → active`) |
| a new uuid, and a scheduled shift covers now | `409 scheduled_shift_exists` (`data.shift_uuid`) — start that one |
| a new uuid, the user's template has an occurrence now | a shift **materialized** from the template (`source = template`) |
| a new uuid, no template, `allow_unscheduled_shifts` | an ad-hoc shift (today's behaviour) |
| otherwise | `409 no_shift_available` |

Starting before the window opens is allowed on the same business day (anomaly `early_start`); a shift
scheduled for a LATER day cannot be started yet (`409 shift_not_yet_startable`); late is allowed
(`late_start`); after a scheduled shift's planned end: `409 shift_window_closed`.

## 2. Route endpoints

One value type for "where work starts / ends" (shifts, templates; beats and journey plans later):

| `mode` | Meaning | Geofence |
|---|---|---|
| `anywhere` (default) | no expectation | — |
| `hub` + `hub_id` | a specific hub (its place / fence) | optional |
| `assigned_hub` | the user's hub **for that day** | optional |
| `place` + `place_uuid` **or** `latitude`/`longitude` (+ `address`, `name`) | a location (coordinates found-or-created in `geo.places`) | optional |

Each side takes optional `enforcement` (`advisory` / `soft_block` / `hard_block`; omitted = record only) and
`radius_m` (omitted = the place's fence, else the policy radius). Start and end are independent.

* **Start** is enforced: soft block needs a `justification` (`422 justification_required`), hard block refuses
  online (`422 outside_geofence`); a start that happened **offline is never refused** (accepted, review pending).
* **End** is only recorded (`end_check`, `end_distance_m`, anomaly `outside_end_place` when enforcement was set).
* Resolution precedence per side: explicit on the shift > journey plan > beat (future) > template > anywhere.
  The resolved endpoint is frozen on the shift (`assigned_hub` becomes the day's hub; no hub that day →
  `anywhere` + anomaly `no_hub_assigned`).

## 3. Templates

`fieldops.shift_templates`: `code`, `name`, `work_type`, `start_local_time` / `end_local_time`,
`end_day_offset` (overnight), `timezone` (NULL = organization's), `days_of_week`, validity, endpoints. A
template has **no** targeting columns — who gets it is the policy setting `shift.template`
([policy-layers.md](policy-layers.md)): organization-wide, per role, team, hub or user.

Materialization is **lazy**: nothing is generated nightly; the shift is created when the user starts it,
copying the template (`template_snapshot`). Until then `GET /me/shifts` lists the occurrence as a
**virtual** entry (`uuid: null`, `source: template`) for today and — within 12 h — tomorrow.

API: `GET/POST /api/fieldops/shift-templates`, `GET/PATCH/DELETE /…/{ref}` (uuid, id or code),
`GET /…/{ref}/preview?at=`. Perms `fieldops.shift_template:*`.

**THPL seed** (`python scripts/seed.py --only fieldops.defaults`): `WORK_SHIFT` "Work Shift", 09:00–21:00
Asia/Kolkata, every day, `work_type = other`, start/end anywhere, no geofencing; assigned to role `member`.
To add a start hub with geofencing later:

```json
PATCH /api/fieldops/shift-templates/WORK_SHIFT
{"row_version": 1, "start": {"mode": "assigned_hub", "enforcement": "soft_block", "radius_m": 150}}
```

## 4. The hub of the day

`user_hub_assignments` (date ranges, one per user per day; `hub_id` NULL = explicitly none). Resolution:
assignment → current employment record's hub → none. Writing a range **splits** what it overlaps.

`POST /api/hubs/assignments` `{"assignments": [{"user_id": 7, "hub_id": 3, "date": "2026-10-08"}]}` (or
`valid_from` / `valid_to`) · `GET /api/hubs/assignments?user_id=&date=` · `GET /api/hubs/me?date=`.
Perms `hubs.assignment:read/manage`, judged at each TARGET user's organization (all-or-nothing for a batch;
the list shows only users the caller's grant covers). The hub is frozen on each shift (`shifts.hub_id`) and is the `hub`
policy dimension.

## 5. Scheduling (managers)

| Route | |
|---|---|
| `POST /api/fieldops/shifts` | `user_id` + window (`planned_start_at`/`planned_end_at`) **or** `template` (+ `date`); `title`, `work_type` (`delivery` · `collection` · `return` · `exchange` · `other`), `start`, `end`, `notes`, optional `uuid`. `409 shift_overlaps` |
| `POST /api/fieldops/shifts/bulk` | ≤ 200, all-or-nothing |
| `PATCH /api/fieldops/shifts/{ref}/plan` | edit a scheduled shift's plan (`row_version`) |
| `POST /api/fieldops/shifts/{ref}/cancel?reason=` | cancels it and its planned stops |
| `POST /api/fieldops/shifts/{ref}/stops` | planned visits in order (`place_uuid` / coordinates / account; `stop_code`, `external_ref`, window) |

The rep starts a stop with `POST /api/me/visits/{uuid}/start` (the fix is the proof-of-presence capture).

## 6. Auto-close

Every 5 minutes (not at midnight): a shift closes at
`auto_close_at = min(planned_end + overtime_minutes, started_at + max_shift_hours) + auto_close_grace_minutes`,
stored at start (the app's force-end alarm uses the same value; it is in `/me/fieldops/config`
`shift_boundaries`). The recorded end is the last trusted activity, never the cap. Scheduled shifts not
started by planned end + 60 min become `missed` (anomaly `missed_shift`). A continuously tracked active shift
silent for `silence_factor × max_interval_s` raises `tracking_silent` (once per silent stretch).

For "Work Shift" with the seeded values: a 09:00 start closes at ~22:00 IST.

## 7. What the app reads

`GET /api/me/shifts` (filters `status`, `date_from`, `date_to`, `upcoming`): `shift_code`, `title`,
`work_type`, `source`, planned window, `auto_close_at`, `hub`, `template`, `start_location` / `end_location`
(mode, name, address, coordinates, radius, fence uuid, enforcement), start/end checks, stop counts.
`GET /api/me/shifts/{uuid}`: plus `captured_start` / `captured_end`, the stops and the **fence pack**
(circles for Android's GeofencingClient, `requestId = fence_id`, ≤ 100). `POST /me/shifts/{uuid}/handover`
moves an open shift to the calling device.
