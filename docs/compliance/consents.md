# Consent API (DPDP Act, 2023)

**Status:** ✅ built (2026-10-06) · **Code:** `app/modules/compliance/consents.py`, `api.py` · **Table:**
`consent_records` (existing) · **Tests:** `tests/test_sessions_consent_privacy.py`

Before this there was no API to record consent, so with the default policy (`consent.required = true`)
no field user could start a shift (`422 location_consent_required`).

| Route | |
|---|---|
| `GET /api/me/consents?include_inactive=` | my live consents (or the full history) |
| `POST /api/me/consents` | `{consent_type, consent_text_version, consent_language?, purpose_text?, consent_channel?, device_info?}` — `201` recorded, `200` same version already given |
| `POST /api/me/consents/{consent_type}/withdraw` | stamps `withdrawn_at`, deactivates; fires listeners |

* Giving a **new** version supersedes the old live row (kept, `is_active = false`).
* IP is stamped from the request; `legal_basis_reference` = "DPDP Act 2023 s.6".
* **Withdrawing `location_tracking` ends the open shift** (`end_reason = consent_withdrawn`) — registered by
  field operations (`fieldops/service/consent_hooks.py`); compliance never imports feature modules.
* `GET /api/me/fieldops/current` reports `consent.location_tracking: {given, version, required}` so the app
  can prompt before a start fails; the `422` now carries `consent_endpoint`.
