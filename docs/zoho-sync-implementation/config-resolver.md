# Config resolver — runtime per-module sync settings

**Status:** ✅ live · **Code:** `app/modules/zoho/control/config.py`,
operator endpoints in `app/modules/zoho/admin/` ·
**Tests:** `tests/zoho_core/test_config_resolver.py`, `test_operator_api.py`,
`test_slices.py`

---

## 1. Layers

| Layer | Source | Changed by |
|---|---|---|
| L0 code default | `GlobalSyncDefaults` field defaults (`sync/config.py`) | a release |
| L1 environment | `ZOHO_SYNC_*` in `conf.py` / `.env` | a redeploy |
| L2 module | the module's `resolve_module_config(...)` declaration | a release |
| **L3 override** | system setting `zoho.module.<module>.<knob>` | an operator, at runtime, audited |

The most specific layer wins. The engine (`ZohoSyncEngine.resolve`), the planner
(`registered_modules(db)`) and the detail worker all use the effective config.
Identity (endpoint, id attribute, field map, nested rules) **cannot** be
overridden at runtime.

---

## 2. Knobs

| Knob | Type | Bounds | What it changes |
|---|---|---|---|
| `enabled` | bool | — | pull this module at all |
| `strategy` | enum | `full` · `incremental` · `index` | scheduled-lane strategy |
| `sync_interval_minutes` | int | 1 – 10 080 | scheduled-lane cadence |
| `weekly_full_enabled` | bool | — | include in the weekly full reconcile |
| `batch_size` | int | 1 – 200 | records per list page |
| `detail_dispatch` | enum | `inline` · `queued` | N+1 detail fetch mode |
| `wait_between_calls` | float | 0 – 10 s | pause between inline detail calls |
| `max_run_seconds` | int | 10 – 480 | slice wall-clock budget ([apply-gate.md](apply-gate.md) §4) |
| `max_pages_per_run` | int | 0 – 100 000 | slice page budget (0 = none) |
| `max_records_per_run` | int | 0 – 10 000 000 | slice record budget (0 = none) |
| `soft_delete_missing` | bool | — | full scans tombstone vanished rows (**also** needs `ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING`) |
| `hash_volatile_keys` | list[str] | ≤ 500 chars as JSON | payload keys ignored by the no-op hash |

A write is validated three ways:
1. the knob's type and bounds;
2. the whole candidate config (`ModuleSyncConfig.model_validate`);
3. the settings table's 500-character value limit.

Only after all three pass is it persisted.

---

## 3. Mechanics

| Step | How |
|---|---|
| Write | `PUT /api/zoho/admin/config/{module}/{knob}` → validate → `system_settings_service.set_setting` (row in `setting_audit_logs` with actor and IP) → **commit** → `INCR zoho:cfg:version` → `activity_logs` entry with before/after and reason |
| Clear | `DELETE …/config/{module}/{knob}?reason=…` → delete the value row + manual audit row (`new_value = "(override removed)"`) → commit → bump version |
| Read (hot path) | per-process cache; re-validated against `zoho:cfg:version` at most every `ZOHO_CONFIG_CACHE_SECONDS` (10 s); **one** query loads every override |
| Redis down | cache reloaded from Postgres at most once a minute |
| Postgres down | last good overrides stay in force |
| Corrupt stored value (manual SQL) | ignored and logged `zoho.config.bad_override`; the module keeps its declared value |

Why the resolver does not use `system_settings_service.get_setting`
([ERRORS](ERRORS-AND-THEIR-RESOLUTIONS.md) E21):
* it falls back to the definition's `default_value`, which is the *first
  value ever set*, so a removed override would still apply;
* it casts by the definition's inferred type, which was fixed by that first write.

---

## 4. Operator API

```bash
# what is in force, and which layer supplied each value
curl https://$DOMAIN/api/zoho/admin/config/organizations -H "Authorization: Bearer $TOKEN"

# slow the weekly full down during a CDC incident
curl -X PUT https://$DOMAIN/api/zoho/admin/config/organizations/max_pages_per_run \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"value": 20, "reason": "Debezium catching up"}'

# back to the module default
curl -X DELETE "https://$DOMAIN/api/zoho/admin/config/organizations/max_pages_per_run?reason=recovered" \
  -H "Authorization: Bearer $TOKEN"
```

Response `data.knobs.<knob>` =
`{value, layer: override|module|environment|default, declared, type, min, max, choices, help}`.

---

## 5. Open items

| # | Item |
|---|---|
| 1 | Push / webhook / approval knobs (`zoho.<module>.push.*` …) arrive with Phases 7–8 |
| 2 | Per-lane knobs (a different page budget for `weekly_full` than for `scheduled`) |
| 3 | `min_interval_floor_s` per module (a floor declared by the module, stricter than the global bound) |
