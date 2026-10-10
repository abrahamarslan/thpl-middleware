# Adapter: `price_lists` — Zoho Books `/pricebooks` → `pricing.price_lists`

**Package:** `app/modules/price_lists/zoho/` · **Migrations:** `20261008_1400_02b470ed2792` (created as
"pricebooks"), `20261008_1600_7c3e91a05d24` (renamed to price lists)
**Design:** [`docs/implementation-plan/price-lists-module.md`](../../implementation-plan/price-lists-module.md)
**API doc:** https://www.zoho.com/books/api/v3/pricelists/ (not vendored)

**Naming.** Zoho's API calls the resource a *pricebook* (`/pricebooks`, `pricebook_id`, `pricebook_items`,
`pricebook_rate` …). The platform calls it a **price list** everywhere it owns the name: module key
`price_lists`, tables `pricing.price_list*`, columns `price_list_type` / `price_list_id` / `rate` /
`discount`, classes `PriceList*`, route `/api/price-lists`. Zoho's spelling appears only on the Zoho side
of the field map and in the wire fixtures that imitate Zoho.

## Contract

| | |
|---|---|
| Endpoint | `GET /pricebooks` (paginated, `page_context`); detail `GET /pricebooks/{pricebook_id}` — **undocumented** (the docs list create / list / update / delete / active / inactive only), works live, and is the only source of the items |
| Identity | crosswalk `sync.sync_records` (module `price_lists`, `external_id` = Zoho `pricebook_id`) + engine-maintained `zoho_id` echo |
| Strategy | **FULL**. No modified-since filter is documented for the list → `modified_since_param=None`, `sort_column=None` |
| Detail | `detail_required` + `index_then_detail`: the list row writes the price list, the detail completes it (`is_default`) and projects the items. **`detail_max_age_minutes=1440`**: the detail has no `last_modified_time`, and Zoho does not say whether an item-rate edit bumps the list's, so each detail is re-confirmed at least daily (1 call per list). `wait_between_calls=1.0` |
| Schedule | every 360 min; no weekly lane (every run is already full) |
| Deletion | `soft_delete_missing=True` — the list returns active AND inactive price lists (verified), so absence from a complete scan = deleted in Zoho. Engine guards apply (`ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING`, mass-delete ceiling) |
| Direction | INBOUND; the API is read-only |
| Matching | `match_on=("zoho_id",)` — re-adoption only, never by name |
| References | `currency_id` → `currencies` (`ReferenceRule`, DEFER). `""` (percentage lists) = base currency → the hook writes NULL |
| Organization | the connection's (`ZOHO_ORGANIZATION_ID` → THPL), else `DEFAULT_TENANT_CODE` / `DEFAULT_ORGANIZATION_CODE` |

## Shapes (live probe, THPL, 2026-10-08)

* **List row:** `currency_code, currency_id, decimal_place, description, is_increase, last_modified_time, name,
  percentage, pricebook_id, pricebook_rate, pricebook_type, pricing_scheme, rounding_type,
  sales_or_purchase_type, status`. No `is_default`.
* **Detail** (`{"code", "message", "pricebook"}`): the list's keys minus `last_modified_time` (and minus
  `pricing_scheme` on percentage lists), plus `is_default`, `products` (`[]`), `pricebook_items`.
* **Unit item:** `pricebook_item_id, item_id, name, can_be_sold, can_be_purchased, pricebook_discount (""),
  pricebook_rate`.
* **Volume item:** `item_id, name, can_be_sold, can_be_purchased, price_brackets` — **no** `pricebook_item_id`,
  no rate (the docs' example shows `sales_rate`; the live API does not send it).
* **Bracket:** `pricebook_item_id` (**unique per bracket** — the docs call it the parent item's id),
  `start_quantity, end_quantity ("" = open-ended), pricebook_discount, pricebook_rate`. Integer ranges
  (10–19, 20–49 …).
* Blanks: `percentage` / `pricebook_rate` are `""` on per_item lists; `pricing_scheme` and `currency_id` are
  `""` on percentage lists.

## Field map (`fields.py`)

| Zoho | → ours | Dir | Note |
|---|---|---|---|
| `name`, `description` | same | BOTH | `""` → NULL |
| `pricebook_type` | `price_list_type` | BOTH | CHECKed closed set |
| `sales_or_purchase_type` | same | BOTH | CHECKed closed set |
| `pricing_scheme` | same | BOTH | `""` → NULL (CHECK: NULL / unit / volume) |
| `percentage` | same | BOTH | decimal; `""` → NULL |
| `pricebook_rate` | `rate` | IN | list-level; observed = `percentage` |
| `is_increase`, `rounding_type`, `decimal_place` | same | BOTH | rounding key stored as text (no CHECK: Zoho's list is longer than its docs) |
| `status` | `status` | IN | `active` / `inactive` (activity changes via `/active`, `/inactive`) |
| `is_default` | same | IN | detail only |
| `currency_id` | `currency_id` | ref + hook | DEFER; `""` → NULL by the hook |
| `pricebook_items[]` | `pricing.price_list_items` | hook | replace-set: match by `item_id`; update changed columns only; soft-delete leavers (`deleted_reason='zoho:removed_from_price_list'`) |
| ↳ `pricebook_item_id`, `name`, `pricebook_rate`, `pricebook_discount`, `can_be_*` | `zoho_id`, `item_name`, `rate`, `discount`, `can_be_*` | hook | |
| `…price_brackets[]` | `pricing.price_list_item_brackets` | hook | match by bracket `pricebook_item_id`, else by position |
| ↳ `pricebook_item_id`, `start_quantity`, `end_quantity`, `pricebook_rate`, `pricebook_discount` | `zoho_id`, `start_quantity`, `end_quantity`, `rate`, `discount` | hook | `""` end → NULL (open) |

A payload without `pricebook_items` (the list row) never touches the children; `[]` empties them.

## Gate behaviour

| Situation | Calls | Writes |
|---|---|---|
| Nothing changed, detail < 24 h old | 1 list | none |
| Nothing changed, detail ≥ 24 h old | 1 list + 1 per price list | only `raw_synced_at` stamped (confirmation) |
| Price list edited (timestamp moved) | 1 list + 1 per changed list | header from list, items from detail |
| Item edited, timestamp not moved | caught by the next age refresh (≤ 24 h) | items |

## Live (THPL, 2026-10-08)

See the plan's *As built*: first sync, the rename, and the population audit against live Zoho (0 problems).
