# Operator API — `/api/zoho/admin`

**Status:** ✅ live · **Code:** `app/modules/zoho/admin/` (`api.py`, `service.py`,
`crud.py`, `schema.py`, `deps.py`, `lang/en.py`) ·
**Tests:** `tests/zoho_core/test_operator_api.py`

---

## 1. Authorisation (⚠ interim)

There is no RBAC in the platform yet (`users.role_id` points at a roles table
that does not exist). Until there is, operators are an allow-list:

| `ZOHO_OPERATOR_EMAILS` | `DEBUG` | Who may call |
|---|---|---|
| `a@x.com,b@x.com` | any | those users (case-insensitive) |
| empty | `true` | any authenticated user (local development) |
| empty | `false` | nobody (403) |

The dependency is `ZohoOperator` (`admin/deps.py`); replacing it with a
role check later changes no route.

Every mutation takes a `reason`, and is written to `activity_logs`
(`zoho_switch_changed`, `zoho_module_paused/resumed`, `zoho_run_requested`,
`zoho_retention_changed`, `zoho_breaker_reset`, `zoho_config_changed`,
`zoho_config_cleared`). Switch and config changes are additionally in
`setting_audit_logs` with the caller's IP.

---

## 2. Endpoints

All responses use the standard envelope `{code, msg, data, request_id}`.

| Method & path | Body | Returns |
|---|---|---|
| `GET /health` | — | `{governor, switches, token, breakers[], planner, running_runs}` |
| `GET /governor` | — | governor snapshot (used, remaining, state, thresholds, allowance, tokens, in-flight, `resets_at`) |
| `GET /switches` | — | switch state |
| `PUT /switches/{name}` | `{value, reason}` | new switch state; `name` ∈ `engine_paused, pull_enabled, push_enabled, webhooks_enabled, paused_modules` |
| `POST /modules/{module}/pause` | `{reason}` | switch state (module added to `paused_modules`) |
| `POST /modules/{module}/resume` | `{reason}` | switch state |
| `POST /modules/{module}/runs` | `{mode?: full\|incremental\|index, reason?}` | 202 `{module, lane: "manual", mode, task_id}` |
| `GET /runs?module=&lane=&status=&limit=` | — | slim run list, newest first |
| `GET /runs/{run_id}` | — | full run (lease, counters, error category/fingerprint/message, request/trace ids) |
| `GET /records/{module}/{ref}/events?by=local\|zoho&event_type=&limit=` | — | the record's sync events, newest first |
| `GET /retention` | — | all retention policies |
| `PUT /retention/{policy_id}` | `{keep_days, enabled, reason}` | updated policy (approval class ≥ 365 d) |
| `POST /breakers/{group}/reset` | — | breaker snapshot after reset |
| `GET /config/{module}` | — | every runtime knob: `{value, layer, declared, type, min, max, choices, help}` |
| `PUT /config/{module}/{knob}` | `{value, reason}` | same shape after the change; 400 with the reason when a type/bound check fails |
| `DELETE /config/{module}/{knob}?reason=` | — | same shape; 404 when there was no override |

Knobs and layers: [`config-resolver.md`](config-resolver.md). Run rows now also
carry `unchanged`, `resurrected`, `stale_ignored`, `details_saved`,
`start_page`, `next_page` ([`apply-gate.md`](apply-gate.md) §6).

Examples:

```bash
# pause everything during month-end close
curl -X PUT https://$DOMAIN/api/zoho/admin/switches/engine_paused \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"value": true, "reason": "month-end close"}'

# what happened to organization 10229182?
curl "https://$DOMAIN/api/zoho/admin/records/organizations/10229182/events?by=zoho" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 3. Relationship to older endpoints

| Older endpoint | Status |
|---|---|
| `GET/POST /api/zoho/sync-engine/modules/...` | still served; `…/run` now goes through the leased `manual` lane |
| `POST /api/zoho/organizations/sync` | same — leased `manual` lane |
| `GET /api/zoho/sync/{entity}` | legacy v1 state table; to be removed in Phase 9 |

---

## 4. Open items

| # | Item |
|---|---|
| 1 | Replace the email allow-list with RBAC (Authentik group → role) |
| 2 | Cancel a running run (needs heartbeat-driven cooperative cancellation, Phase 6) |
| 3 | Outbox, approval and webhook-inbox endpoints (Phases 7–8) |
| 4 | Rate-limit mutating endpoints per operator |
