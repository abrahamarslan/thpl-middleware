# Adapter — currencies (O1 master)

**Status:** ✅ live (pull) · **Code:** `app/modules/currencies/` ·
**Migration:** `91e970e99176` (`zoho_currencies`) · **Tests:** `tests/zoho_core/test_masters.py`
· **Source:** `docs/zoho-docs-md/currency.md`

| Aspect | Value | Why |
|---|---|---|
| Endpoint | `GET /settings/currencies` (Books) | — |
| Pagination | **none** (`paginated=False`) | the documented response has no `page_context`; a paginated walk would raise `ZohoContractError` **[verify]** in Phase 0 |
| Id attribute | `currency_id` | — |
| Strategy | `full`, every 1440 min; no weekly lane | no `last_modified_time`; a full pull is **1 call** |
| Detail call | none | the list row carries every mirrored attribute |
| Direction | inbound only | currencies are managed in Zoho |
| No-op | the apply-gate hash → an unchanged list writes nothing | — |
| Mixins | Identity + Mirror (no push columns) | read-only master |

| Column | Zoho attribute | Transform |
|---|---|---|
| `currency_code` | `currency_code` | str |
| `currency_name` | `currency_name` | str |
| `currency_symbol` | `currency_symbol` | str |
| `currency_format` | `currency_format` | str |
| `price_precision` | `price_precision` | int |
| `is_base_currency` | `is_base_currency` | bool |
| `exchange_rate` | `exchange_rate` | decimal (`numeric(24,10)`) |
| `effective_date` | `effective_date` | zoho_date |

HTTP (read-only, authenticated): `GET /api/zoho/currencies` (base currency
first) · `GET /api/zoho/currencies/{ref}`, where `ref` is the local id, the
Zoho id or the ISO code (`inr`).

Open: exchange-rate history (`/settings/currencies/{id}/exchangerates`) as a
child collection; wiring `contacts.currency_id` → `zoho_currencies` via a nested
rule when contacts land (Phase 6).
