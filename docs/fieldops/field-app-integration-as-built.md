# Field app integration — as built (2026-10-06)

Plan: [field-app-integration-plan.md](field-app-integration-plan.md). This page is what exists in code.

## Migrations (chain after `5d8c2e1f7a90`)

| Revision | What |
|---|---|
| `b7e4c1a9d3f2` | `fieldops.policy_layers` + `fieldops.policy_epochs`; every live `work_policies` row copied as a full layer (row-count guarded); `work_policies` dropped. Downgrade restores it. |
| `c3d9a7e2f415` | `fieldops.shift_templates`, `user_hub_assignments`, shift plan columns (code, title, work_type, source, template, route endpoints, hub, end check, `auto_close_at` — backfilled for open shifts), status `missed`, ping columns (geofence, app/battery state, client hints), `visits.stop_code/external_ref`, regenerated CHECKs, planning permissions on `team_manager`/`department_head`. |
| `d81f4b6e2c90` | schema `auth`, `auth.user_sessions`; privacy settings normalized to the new vocabulary. |

All three were tested upgrade → downgrade → upgrade on a seeded scratch DB.

## Policy layers (`app/modules/fieldops/policy/`)

* `settings.py` — the registry (19 settings; flat field names = the old `work_policies` columns + new ones).
* `dimensions.py` — organization / role / team / hub / beat (reserved, refused on write) / user.
* `resolver.py` — pure `fold` (scope rank → org depth → priority → effective_from → id; per-field merge; locks; invalid combinations skipped and reported), one-query loader, per-tenant epoch.
* `render.py` — Android `LocationConfig` v5 (`GET /api/me/fieldops/config`, ETag / 304, `config_version` = epoch).
* Admin: `GET /api/fieldops/policy-settings`, CRUD `/api/fieldops/policy-layers`, `GET /api/fieldops/policies/resolve?user_id=` (explain), `POST /api/fieldops/policies/preview`. The old `/api/fieldops/policies` routes are gone.

## Shifts

* Templates: CRUD `/api/fieldops/shift-templates` (+ `/{ref}/preview`); assigned by setting `shift.template`. Start with a new uuid → scheduled shift covering now (409 `scheduled_shift_exists`) → template occurrence → ad hoc (`shift.requirements.allow_unscheduled_shifts`) → 409 `no_shift_available`.
* Scheduling: `POST /api/fieldops/shifts`, `/shifts/bulk`, `PATCH /shifts/{ref}/plan`, `POST /shifts/{ref}/cancel`, `POST /shifts/{ref}/stops`.
* Route endpoints (`fieldops/endpoints.py`): `anywhere` (default) / `hub` / `assigned_hub` / `place` (uuid or lat/lng → geo find-or-create), optional `enforcement` + `radius_m`. Start enforced (soft/hard block; offline never refused), end recorded only.
* App: `GET /api/me/shifts` (cards incl. start/end location, hub, template, stop counts; virtual template entries with `uuid: null`), `GET /api/me/shifts/{uuid}` (captured start/end, stops, fence pack ≤ 100), `POST /api/me/shifts/{uuid}/handover`, `POST /api/me/visits/{uuid}/start` (planned stop).
* Auto-close: no midnight job; every 5 min, `auto_close_at = min(planned end + overtime, start + max hours) + grace`; scheduled shifts never started → `missed`. New beat task `fieldops-detect-silent` (`tracking_silent`).
* Hub of the day: `POST/GET /api/hubs/assignments` (split-on-write), `GET /api/hubs/me`.
* Seed: `python scripts/seed.py --only fieldops.defaults` → `WORK_SHIFT` (09:00–21:00 Asia/Kolkata, anywhere), "THPL default" layer (consent locked), "THPL members" layer (template, one field session, 45 s cadence). Never overwrites edited rows.

## Telemetry

`fieldops/wire.py` maps the Android §6 `PingDto` (snake_case) onto `PingIn`; camelCase Room entities are rejected per item with their field names; `da_id` must be the token's user; `capture_reason` → kind/label; geofence events need the fence-pack uuid. Mock policy `security.mock_location_action` (flag_only / reject_and_alert / end_shift). Android must still send `X-Device-Sent-At`, `X-Device-Elapsed-Ms`, `X-Device-Boot-Count`, `X-Device-Session`.

## Sessions (`app/modules/users/sessions.py`)

Every login creates `auth.user_sessions`; tokens carry `sid`; every request checks it. Field-app rule from setting `session.field` (org/role/user), fallback env `FIELD_MAX_SESSIONS`. Device A gets `401 {code: session_revoked, data.reason: signed_in_elsewhere, drain_until}`; during the drain grant it may only upload fixes recorded before revocation. Logout/logout-all revoke; refresh rotates (reuse → session revoked); password change/reset revoke. `GET/DELETE /api/auth/sessions[/{uuid}]`, admin `/api/users/{id}/sessions`. New env: `SESSION_MAX_DAYS`, `FIELD_MAX_SESSIONS`, `MAX_WEB_SESSIONS`, `AUTH_REQUIRE_SESSION` (off until legacy tokens expire), `SESSION_CACHE_TTL_SECONDS`.

## Consent & privacy

* `GET/POST /api/me/consents`, `POST /api/me/consents/{type}/withdraw` (location withdrawal ends the open shift). `/api/me/fieldops/current` reports `consent.location_tracking`.
* Privacy: `profile_visibility` everyone · team · managers · private; `contact_visibility` everyone · team · hidden; notifications + `slack`; `security.two_factor_enabled` read-only. `GET /api/me/settings/options`. Enforced in the user directory (`users/visibility.py`); admins always see.

## Also fixed

X1 (`"None"` uuid in ping results), X2 (minutes as floats on shift cards), registering a user's second device (was a 409 from `uq_devices_one_primary`).

## Verification

* Tests: 69 new (`test_fieldops_policy.py`, `test_fieldops_wire.py`, `test_fieldops_shift_plan.py`,
  `test_sessions_consent_privacy.py`); full suite green.
* Dev stack (2026-10-06): migrations applied, `fieldops.defaults` seeded, Celery restarted, and an end-to-end
  script against the live API (real password login, consent, config + 304, the Work Shift virtual entry and
  start, Android pings, hub of the day, a scheduled assigned-hub shift with stops and fence pack, device-B
  sign-in with drain + handover, shift end, privacy settings, explain, logout) passed 33/33.

## Migration verification (2026-10-07)

| Check | Result |
|---|---|
| Whole chain from an EMPTY database (47 revisions) | ✅ to `d81f4b6e2c90` |
| The three revisions down → up on that database | ✅ |
| Autogenerate drift on the owned tables | ✅ none (fixed: two `shifts` column comments were missing). The `location_pings` table comment drift predates this work |
| Every CHECK / EXCLUDE of the owned tables vs the models (104, semantic compare) | ✅ all match; the new CHECK reaches every `location_pings` partition |
| Down → up on a COPY of the dev database (real data) | ✅ row counts and shift states unchanged; layers (settings, locks), privacy values and `config_version` preserved |
| Dev schema vs a fresh-from-zero schema (owned tables, `pg_dump --schema-only`) | ✅ identical |
| Celery in the real worker: auto-close, missed, tracking_silent | ✅ each acted on a real condition |
| Live API end-to-end (33 steps) after all fixes | ✅ 33/33 |

**What a DOWNGRADE loses** (the old schema has no place for it): team/hub/user policy layers, shift
templates, hub assignments, sign-in sessions, shift plan columns, and anomalies of the new types. What it
KEEPS for a later re-upgrade: organization/role layers exactly (stashed in `work_policies.app_metadata`),
privacy choices (stashed keys), and a never-decreasing `config_version` (time floor). After a re-upgrade,
run `python scripts/seed.py --only fieldops.defaults` to recreate the Work Shift template.

**Fixed during verification:** hub assignments are authorized per target user's organization (a branch
manager could move another branch's people); a scheduled shift for a later business day cannot be started
early (`409 shift_not_yet_startable`); the drain cut-off uses monotonic business time, not the device clock;
two refreshes racing within 30 s no longer revoke the session; declining consent the first time is recorded.

## Deploying

`alembic upgrade head` → `python scripts/seed.py --only fieldops.defaults` → restart `celery-worker` and
`celery-beat`. Give the Android team [android-contract.md](android-contract.md). Turn on
`AUTH_REQUIRE_SESSION` once pre-deploy tokens have expired.

## Docs

[policy-layers.md](policy-layers.md) · [shift-templates.md](shift-templates.md) ·
[android-contract.md](android-contract.md) · [../auth/sessions.md](../auth/sessions.md) ·
[../compliance/consents.md](../compliance/consents.md) · [../users/privacy-settings.md](../users/privacy-settings.md)
