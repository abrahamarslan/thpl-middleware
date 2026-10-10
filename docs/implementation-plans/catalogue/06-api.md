# 06 — API

FBA layering per module (`api → schema → service → crud → model`), one router include each in `app/router.py`.
Envelope `{code, msg, data, request_id}`; lists return `PageModel`. Path references are **uuids** (`{ref}`), never
internal ids. Every mutating route has a `Perm(...)`; row-level routes pass `target=org_of(...)`
(`tests/test_rbac_routes.py` enforces both). Reads need an authenticated user (`CurrentUser`) — row-level read scope is
not built platform-wide (RBAC §12), so reads are organization-scoped through the tenancy filter and
`X-Organization-Code`.

---

## 1. Conventions

| Concern | Rule |
|---|---|
| Updates | `PATCH` with `row_version`; mismatch → 409 `stale_row_version`. Response returns the new `row_version` |
| Creates of documents/movements | `Idempotency-Key` header honoured through `core.idempotency_keys` (the fieldops module's) |
| Zoho-linked rows | Zoho-owned fields refused with 409 `zoho_owned_field` listing the fields (until P7) |
| Deletes | Soft delete with `reason`; refused when in use (409 `*_in_use`) — deactivate instead |
| Lists | Slim DTO backed by `load_only(...)`; cursor or page/size (max 200); filters are explicit query params; free text → search index (`/api/search/catalogue_items`) |
| Details | Fat DTO with explicit `selectinload`/`joinedload` (stated per relationship in the model docstring); `include=` opt-ins for heavy children (`media`, `documents`, `stock`) |
| Errors | `AppError` subclasses with stable `code`s (below); never bare `HTTPException` |
| Money/quantities | JSON strings of decimals (`"869.000000"`), parsed to `Decimal`; never floats |

---

## 2. Catalogue masters — `app/modules/catalogue/api_masters.py`

| Method & path | Perm | Notes |
|---|---|---|
| `GET /api/catalogue/uqc-codes` | auth | global list |
| `GET/POST /api/catalogue/units`, `GET/PATCH/DELETE /api/catalogue/units/{ref}` | `catalogue.unit:create/update/delete` | linked units: code/name/uqc Zoho-owned |
| `GET/POST /api/catalogue/packaging-types`, `GET/PATCH/DELETE …/{ref}` | `catalogue.packaging_type:*` | |
| `GET/POST /api/catalogue/sales-channels`, `GET/PATCH/DELETE …/{ref}` | `catalogue.sales_channel:*` | |
| `GET/POST /api/catalogue/item-groups`, `GET/PATCH/DELETE …/{ref}` | `catalogue.item_group:*` | `?tree=true` returns the hierarchy; `POST …/{ref}/media` banner |
| `GET/POST /api/catalogue/attributes`, `…/{ref}`, `POST/PATCH/DELETE …/{ref}/options[/{option_ref}]` | `catalogue.attribute:*` | |
| `GET/POST /api/catalogue/products`, `GET/PATCH/DELETE …/{ref}` | `catalogue.product:*` | detail includes axes and variant items (slim) |
| `POST /api/catalogue/products/{ref}/variants` | `catalogue.item:create` | create items for a set of axis combinations in one call (all-or-nothing) |

## 3. Items — `app/modules/catalogue/api_items.py`

| Method & path | Perm | Notes |
|---|---|---|
| `GET /api/catalogue/items` | auth | filters: `status, brand, manufacturer, item_group, product, category, can_be_sold, can_be_purchased, track_mode, hsn, zoho_linked, updated_since`; slim: `uuid, sku, name, status, brand{uuid,name}, base_unit{code}, sales_rate, mrp, hsn_or_sac, thumbnail_url` |
| `POST /api/catalogue/items` | `catalogue.item:create` | full create: item + optional `merchandising`, `units[]` (hierarchy, coarsest last), `identifiers[]`, `tax_preferences[]`, `accounts{}`, `categories[]`, `vendors[]`, `channels[]`, `custom_fields{}`, `tags[]` — one transaction |
| `GET /api/catalogue/items/{ref}` | auth | fat: everything above + `item_type` (computed), `zoho{linked, zoho_id, synced_at}`; `include=media,documents,stock,schemes` |
| `PATCH /api/catalogue/items/{ref}` | `catalogue.item:update` | scalar fields only; children have their own routes |
| `DELETE /api/catalogue/items/{ref}` | `catalogue.item:delete` | 409 `item_in_use` when referenced |
| `POST /api/catalogue/items/{ref}/activate` · `/deactivate` · `/discontinue` | `catalogue.item:update` | `discontinue` = sell-through only |
| `PUT /api/catalogue/items/{ref}/merchandising` | `catalogue.item:update` | 1:1 upsert; never Zoho-owned |
| `GET /api/catalogue/items/{ref}/units` | auth | the hierarchy, coarsest first, with `base_factor`, flags, prices, identifiers |
| `POST /api/catalogue/items/{ref}/units` | `catalogue.item:update` | add a level (`unit`, `contains: {level_ref, qty}`) |
| `PATCH /api/catalogue/items/{ref}/units/{level_ref}` | `catalogue.item:update` | flags, prices, physicals, label only — structure → 409 `item_unit_immutable` |
| `POST /api/catalogue/items/{ref}/units/{level_ref}/retire` | `catalogue.item:update` | optional `replacement` level in the same call (re-spec a carton) |
| `POST /api/catalogue/items/{ref}/units/convert` | auth | `{qty, from, to}` → quantity; `{qty_base}` → breakdown |
| `PUT /api/catalogue/items/{ref}/base-unit` | `catalogue.item:manage` | only while unused (409 `base_unit_locked`) |
| `GET/POST /api/catalogue/items/{ref}/identifiers`, `DELETE …/{id_ref}` | `catalogue.item:update` | GTIN check digit validated |
| `GET /api/catalogue/lookup?code=` | auth | barcode → `{item, level}` (scanner endpoint for FSA/DLP) |
| `GET/PUT /api/catalogue/items/{ref}/components` | `catalogue.item:update` | replace-set with validity; cycle → 422 `component_cycle` |
| `GET/PUT /api/catalogue/items/{ref}/channels` | `catalogue.item:update` | replace-set |
| `GET/PUT /api/catalogue/items/{ref}/vendors` | `catalogue.item:update` | vendor must be a vendor party (`assert_role`) |
| `GET/PUT /api/catalogue/items/{ref}/attributes` | `catalogue.item:update` | variant axis values |
| `POST /api/catalogue/items/{ref}/media` · `PATCH …/media/order` · `DELETE …/media/{media_ref}` | `catalogue.item:update` | owner-endpoint uploads (media doctrine: no generic upload route) |
| `POST /api/catalogue/items/{ref}/quote` | auth | 03 §2: `{level, qty, party?, price_list?, channel?, batch?, date?, direction}` → rate + explain |
| `GET /api/catalogue/items/{ref}/availability` | auth | per warehouse × batch (`source: ledger|zoho`, `as_of`) |
| `POST /api/catalogue/items/import` | `catalogue.item:import` | CSV dry-run/commit (P2 stretch; reuses the same create validator) |
| `GET /api/catalogue/data-quality` | `catalogue.item:manage` | items without base unit / HSN / tax, unresolved brand names, invalid GTINs, Zoho UQC unknown |

Taxes, accounts, categories, documents, comments, custom fields and tags keep their **existing generic routes**
(`/api/taxes/assignments/item/{id}`, `/api/accounting/assignments/…`, `/api/categorizables`, `/api/documents/…`,
`/api/comments`, `/api/custom-fields/…`, `/api/tags/sync`) — the item create/detail endpoints compose them, they do not
fork them.

## 4. Batches — `app/modules/catalogue/api_batches.py`

| Method & path | Perm | Notes |
|---|---|---|
| `GET /api/catalogue/batches` | auth | filters `item, expiring_within_days, expired, held, qc_status, supplier`; slim incl. `expires_on`, `days_to_expiry` (computed) |
| `POST /api/catalogue/batches` | `catalogue.batch:create` | `expires_on` required when the item is expiry-tracked |
| `GET/PATCH/DELETE /api/catalogue/batches/{ref}` | `catalogue.batch:update/delete` (`manage` for `expires_on` with stock) | |
| `POST /api/catalogue/batches/{ref}/holds` | `catalogue.batch_hold:create` | `{hold_type, reason_code, reason}` |
| `POST /api/catalogue/batches/{ref}/holds/{hold_ref}/release` | `catalogue.batch_hold:approve` | Q-5 |
| `POST /api/catalogue/batches/{ref}/qc` | `catalogue.batch:verify` | `{decision: passed|failed, note, document_ref?}` |
| `GET /api/inventory/batches/{ref}/trace` | auth | where it came from / went to (recall report) |
| documents (CoA), media, comments | existing generic routes with owner `batch` | |

## 5. Inventory — `app/modules/inventory/api.py`

| Method & path | Perm | Notes |
|---|---|---|
| `GET/POST /api/inventory/locations`, `GET/PATCH/DELETE …/{ref}`, `POST …/{ref}/move` | `inventory.storage_location:*` | tree; `move` re-parents |
| `GET /api/inventory/balances` | auth | by item / batch / location / status; `group_by=warehouse|batch|location` |
| `GET /api/inventory/ledger` | auth | by item / batch / location / source / date range (keyset paginated on `(business_date, id)`) |
| `GET /api/inventory/availability` | auth | the view, filterable |
| `POST /api/inventory/movements` | `inventory.stock_movement:create` | draft; Idempotency-Key |
| `GET/PATCH/DELETE /api/inventory/movements/{ref}` | `inventory.stock_movement:update/delete` | drafts only |
| `POST /api/inventory/movements/{ref}/post` | `inventory.stock_movement:approve` | 409 `insufficient_stock`, 409 `ledger_mode_mirror` when the org is not cut over |
| `POST /api/inventory/movements/{ref}/cancel` | `inventory.stock_movement:approve` | posts reversals |
| `GET/PUT /api/inventory/items/{item_ref}/replenishment` | `inventory.replenishment:update` | reorder level / qty, min / max, default bin per warehouse |
| `GET /api/inventory/reorder-suggestions` | auth | below reorder level, by warehouse |
| `GET/POST/PATCH /api/inventory/reason-codes` | `inventory.reason_code:*` | |
| `GET /api/inventory/reconciliation` | `inventory.stock:manage` | ledger vs Zoho snapshot drift |
| `GET /api/inventory/expiry` | auth | `v_batch_expiry`: filters `status` (near_expiry, below_min_shelf_life, expired…), `bucket`, `warehouse`, `brand`, `item_group`, `within_days`; totals per bucket |
| `GET /api/inventory/ageing` | auth | `stock_ageing()`: `as_of`, `warehouse`, `item`, `group_by=bucket|item|warehouse` |
| `GET /api/inventory/negative-stock` | auth | negative positions with age (work queue) |
| `GET /api/inventory/policies` · `GET /api/inventory/policies/effective?warehouse=&item=` | auth | layers, and the merged result with the layer each rule came from |
| `POST/PATCH/DELETE /api/inventory/policies[/{ref}]` | `inventory.stock_policy:update` | organization / warehouse / item-group / item layers; `ledger_mode` only via the cut-over command (`inventory.stock:manage`) |

Reservations and allocation have **no public write route**: document modules call the services (07).

## 6. Schemes — `app/modules/schemes/api.py` (tables in `pricing`)

| Method & path | Perm | Notes |
|---|---|---|
| `GET/POST /api/pricing/schemes`, `GET/PATCH/DELETE …/{ref}` | `pricing.scheme:create/update/delete` | targets/slabs/eligibility nested on create; PATCH only in `draft` |
| `PUT /api/pricing/schemes/{ref}/targets` · `/slabs` · `/eligibility` | `pricing.scheme:update` | replace-set, draft/paused only |
| `POST /api/pricing/schemes/{ref}/activate` · `/pause` · `/archive` | `pricing.scheme:update` | no approval step (owner decision); activation validates the scheme and records activity |
| `POST /api/pricing/schemes/evaluate` | auth | a draft document (party, lines) → applied/skipped per line (03 §5); used by FSA order capture for live previews |
| `GET /api/pricing/schemes/for-item/{item_ref}` | auth | active schemes touching an item (any level) — for the FSA catalogue badge |

## 7. Permission catalogue additions (`rbac/catalogue.py`)

```python
*_p("catalogue", "unit", "create update delete", "units of measure"),
*_p("catalogue", "packaging_type", "create update delete", "packaging types"),
*_p("catalogue", "sales_channel", "create update delete", "sales channels"),
*_p("catalogue", "item_group", "create update delete", "merchandising groups"),
*_p("catalogue", "attribute", "create update delete", "variant attributes"),
*_p("catalogue", "product", "create update delete", "variant templates"),
*_p("catalogue", "item", "create update delete manage import export", "items (SKUs)"),
*_p("catalogue", "batch", "create update delete manage verify use", "batches (lots); use = sell an expired lot under the override policy"),
*_p("catalogue", "batch_hold", "create approve", "batch holds (place / release)"),
*_p("inventory", "storage_location", "create update delete", "warehouses and bins"),
*_p("inventory", "stock_movement", "create update delete approve", "stock movements (post / cancel = approve)"),
*_p("inventory", "stock_policy", "update", "stock rules: negative stock, expiry, shelf life, allocation, ageing"),
*_p("inventory", "replenishment", "update", "reorder policies"),
*_p("inventory", "reason_code", "create update delete", "stock reason codes"),
*_p("inventory", "stock", "manage", "reconciliation and cut-over"),
*_p("pricing", "scheme", "create update delete", "offers / schemes (no approval step)"),
```

Role templates: `member` gets none of the writes (catalogue maintenance is an operations role); `admin` gets all
except `inventory.stock:manage` (owner-only: cut-over).

## 8. Error codes (stable)

`item_in_use`, `item_unit_immutable`, `item_unit_in_use`, `base_unit_locked`, `tracking_locked`, `unit_not_sellable`,
`unit_not_purchasable`, `pack_unit_must_count`, `unit_class_mismatch`, `fractional_base_quantity`, `component_cycle`,
`invalid_gtin`, `duplicate_identifier`, `zoho_owned_field`, `expiry_required`, `batch_in_use`, `batch_required`,
`batch_not_allowed`, `batch_on_hold`, `batch_expired`, `expiry_override_required`, `shelf_life_too_short`,
`shelf_life_too_short_on_receipt`, `insufficient_stock`, `price_window_overlap`,
`storage_condition_mismatch`, `ledger_mode_mirror`, `no_price_for_unit`, `rate_above_mrp`, `scheme_not_editable`,
`scheme_limit_reached`, `stale_row_version`.

## 9. Search

One `SearchableEntity` (`catalogue_items`) over the `catalogue.items` CDC rows as they are: searchable `name, sku,
print_name, code, hsn_or_sac`, filterable `status, brand_id, manufacturer_id, item_group_id, product_id, can_be_sold,
track_mode, organization_id`, sortable `name, updated_at`. Three-step wiring: Debezium include list
(`catalogue.items`), `SEARCH_CDC_TOPICS`, the registry entry. Hydration through `ScoutBuilder` with the items Slim DTO.
Barcodes are **not** indexed: a scanned code is an exact lookup (`/api/catalogue/lookup`), and the indexer only sees
single-table CDC rows (a denormalized brand name or identifier array would need a second pipeline — not built).
Batches become searchable by number later if FSA asks.
