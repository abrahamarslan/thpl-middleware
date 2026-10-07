# Policy layers

**Status:** ✅ built (2026-10-06) · **Migration:** `b7e4c1a9d3f2` (replaced `fieldops.work_policies`) ·
**Code:** `app/modules/fieldops/policy/` · **Tests:** `tests/test_fieldops_policy.py`

One engine decides what a field worker **must** do (shift rules, consent, geofencing, the single-session
rule) and how the field app **behaves** (tracking cadence, flush, stop capture). RBAC still decides what
someone **may** do.

## 1. The model

A **layer** is a *sparse* set of settings with a **target**:

| `scope_type` | `scope_id` | Applies to |
|---|---|---|
| `organization` | — | everyone in that organization **and its subtree** (at the root organization: the tenant default) |
| `role` | `roles.id` | users whose **base role** it is (within the layer's organization subtree) |
| `team` | `teams.teams.id` | approved, active members |
| `hub` | `hubs.id` | the shift's hub, or the user's hub of the day ([shift-templates.md](shift-templates.md) §4) |
| `beat` | — | **reserved** — refused (`scope_not_available`) until the beats module exists |
| `user` | `users.id` | one person (an exception) |

Layers are merged **per setting field** over the code defaults. A layer that sets one field inherits
every other value — unlike the old `work_policies`, where the winning row replaced everything.

### Precedence (later wins)

```
scope rank (organization 0 · role 10 · team 20 · hub 30 · beat 40 · user 50)
  → organization depth (deeper wins at the same rank)
  → priority (-100..100) → effective_from (NULLs first) → id
```

Scope before depth: a branch's **general** default never overrides HQ's **role** rule. To override HQ's
delivery-agent rule, a branch writes a delivery-agent rule (same rank, deeper).

### Locks

`locked_keys` holds setting keys (`consent.required`) or single fields (`geofence.rules.geofence_enforcement`).
A lock freezes the value for every layer folded after it. Writes that set a key locked by an
organization layer above are refused (`422 policy_setting_locked`); anything else locked is skipped at
resolution and reported as a conflict.

### Skipped contributions (never fatal)

`/policies/resolve` reports `conflicts`: `locked`, `scope_not_allowed` (e.g. a session rule on a hub
layer), `invalid_combination` (a merge that breaks an invariant such as `min ≤ base ≤ max`), `unknown_setting`.

## 2. The settings registry (`policy/settings.py`)

| Key | Fields (flat names) | Binding | Scopes |
|---|---|---|---|
| `shift.requirements` | `requires_shift`, `allow_visits_without_shift`, `require_start_selfie`, `require_odometer`, `allow_unscheduled_shifts` | frozen | all |
| `shift.window` | `earliest_start_local`, `latest_end_local`, `start_early_minutes`, `late_start_grace_minutes`, `max_shift_hours`, `overtime_minutes`, `auto_close_grace_minutes`, `stale_shift_after_minutes`, `pre_end_reminder_minutes` | frozen | all |
| `shift.template` | `shift_template` (template code) | frozen | all |
| `shift.start_place` | `require_start_at_place_id` (fallback advisory start place) | frozen | not user |
| `pause.rules` | `max_pause_minutes`, `max_pauses_per_shift`, `paid_pause_types`, `track_during_pause`, `pause_extends_cap` | frozen | all |
| `consent.required` | `require_location_consent` | frozen | organization, role, user |
| `tracking.mode` | `tracking_mode` | live | all |
| `tracking.intervals` | `priority`, `min_interval_s`, `ping_interval_s` (base), `max_interval_s`, `stationary_interval_s`, ratios, `ping_min_distance_m`, `battery_bands`, `activity_intervals` | live | all |
| `tracking.accuracy` | `client_max_accuracy_m` (app drops), `max_fix_accuracy_m` (server evidence) | live | all |
| `tracking.silence` | `silence_factor` | live | all |
| `stop_capture` · `sync.batch` · `features` | client tuning | live | all |
| `retention.local` | `local_synced_data_days` | live | organization, role |
| `geofence.rules` | `geofencing_enabled`, `geofence_enforcement`, `default_visit_radius_m`, `geocoded_radius_factor`, `allow_manual_location` | frozen | all |
| `anomaly.thresholds` | visit/gap/skew/coverage thresholds | frozen | not user |
| `security.mock_location_action` | `flag_only` · `reject_and_alert` · `end_shift` | frozen | organization, role, user |
| `security.integrity` | `mock_location_detection`, `play_integrity_check` | live | organization, role |
| `session.field` | `field_max_sessions` (0 = unlimited), `field_on_new_login` (`revoke_previous` / `refuse`), `field_drain_grant_hours` | login | organization, role, user |

**frozen** = copied onto a shift when it starts (`shifts.policy_snapshot`) — a running shift keeps its
rules. **live** = re-resolved on every config refresh. **login** = resolved at sign-in (no shift context).
Adding a setting is one registry entry; no migration.

## 3. Versions and caching

`fieldops.policy_epochs` holds one counter per tenant, bumped in the same transaction as every layer
write: `epoch = GREATEST(epoch + 1, minutes since 2020-01-01)`. It is the app's `config_version` — it never
decreases, even when a layer is deleted or the table is recreated by a downgrade/upgrade. Resolution is
3–4 indexed queries; the hot path (ping ingest, shift actions) reads the shift's snapshot, so there is
no resolution cache.

## 4. API

| Route | Perm |
|---|---|
| `GET /api/fieldops/policy-settings` — the catalogue (JSON schema, default, binding, scopes) | `fieldops.policy:read` |
| `GET /api/fieldops/policy-layers` · `GET /…/{ref}` | `fieldops.policy:read` |
| `POST /api/fieldops/policy-layers` (organization from `X-Organization-Code`) | `fieldops.policy:create` |
| `PATCH /api/fieldops/policy-layers/{ref}` — `settings` sets keys/fields, `unset` removes them, `row_version` | `fieldops.policy:update` |
| `DELETE /api/fieldops/policy-layers/{ref}?reason=` | `fieldops.policy:delete` |
| `GET /api/fieldops/policies/resolve?user_id=&shift=&at=` — explain: values, provenance, conflicts, layers | `fieldops.policy:read` |
| `POST /api/fieldops/policies/preview` — dry run of a draft layer (≤ 200 users evaluated) | `fieldops.policy:read` |
| `GET /api/me/fieldops/config` — the Android config (ETag, 304) | `fieldops.field_work:use` |
| `GET /api/me/fieldops/policy` — every flat value that applies to me | `fieldops.field_work:use` |

Example — THPL members (as seeded):

```json
POST /api/fieldops/policy-layers
{"name": "THPL members", "scope_type": "role", "scope_id": 3,
 "settings": {"shift.template": "WORK_SHIFT",
              "session.field": {"field_max_sessions": 1, "field_on_new_login": "revoke_previous"},
              "tracking.intervals": {"ping_interval_s": 45, "stationary_interval_s": 180}}}
```

## 5. Adding a dimension (beats)

1. The beats module creates its table and `shifts.beat_id` (set when a shift is scheduled).
2. One `Dimension` entry in `policy/dimensions.py` (`table="…beats"`).
3. Nothing else — `scope_type = 'beat'` is already in the CHECK and the precedence order.

Beat context comes from the shift's assignment, never from live GPS (no flip-flopping at boundaries).

## 6. Migration from `work_policies`

Each live row became one layer carrying **all** its values (organization layer when `role_id` was NULL,
role layer otherwise), so resolution results were unchanged on day one. Trim layers to gain inheritance.
Old shift snapshots read back unchanged (same flat names).
