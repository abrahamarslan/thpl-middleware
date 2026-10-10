# 05 — Zoho sync

Everything here goes through the existing engine (`app/modules/zoho/sync/`), control plane, governor and crosswalk.
No new client, limiter, breaker or identity table. Adapters live in `app/modules/<feature>/zoho/{spec,fields,hooks}.py`
and are registered via `_ADAPTER_PACKAGES`; every adapter is exercised through `tests/zoho_core/test_masters_e2e.py::ZohoWire`.

---

## 1. Ground rules (from the platform, restated because they bind every adapter)

* **Docs are law.** An adapter is built against a page in `docs/zoho-docs-md/`. Today only the Books `items.md` is
  vendored. P0 vendors the Zoho Inventory pages (items, batches, composite items, item groups) and records any
  undocumented endpoint as *probed live*, with the probe log, exactly as brands and price lists did.
* **Crosswalk entities**: identity, fence, hash, raw document and custom fields live in `sync.sync_records`; tables
  carry business columns + a `zoho_id` echo with a live partial unique index.
* **Apply gate**: `last_modified_time` fence, payload provenance (list rows never overwrite detail data), hash no-op.
* **Ownership**: a linked row's Zoho-fed fields are read-only through our API until push exists (409
  `zoho_owned_field`); everything else is locally editable.
* **Budget**: documented 100 requests/min/org and a plan-dependent daily cap; the governor admits every call. The
  accounts module observed an undocumented 429 (`code 43`) after ~190 detail calls in 3.5 min — first syncs of
  detail-heavy modules must be **sliced** (leased manual slices, as the parties first sync did).

---

## 2. Phase 0 — discovery probes (read-only)

All GETs, against THPL, logged to `docs/zoho-sync-implementation/adapters/catalogue-probes.md`. No POST/PUT/DELETE is
ever sent to discover anything.

| # | Probe | Decides |
|---|---|---|
| P0.1 | `GET /items` (Books) page 1 with `filter_by=Status.All`; count pages | Item count → first-sync budget; whether inactive items need `Status.All` (contacts did) |
| P0.2 | List row keys vs `GET /items/{id}` keys, on 10 items incl. batch-tracked, composite, service | Which fields are detail-only → `index_then_detail`; presence of `unit_id`, `brand`, `manufacturer`, `category_id`, `track_batch_number`, `package_details`, `upc/ean/isbn/part_number`, `item_tax_preferences`, `locations`, `image_*`, `group_id`, `is_combo_product` |
| P0.3 | `GET /itemdetails?item_ids=` (documented, Books) with 10/25/50/100 ids | Max ids per call → bulk detail size (engine change E-C1) |
| P0.4 | `GET /items?last_modified_time=…` (+0000 format, like categories) | Whether INCREMENTAL is real (undocumented for items) — if the filter is ignored, FULL + gate |
| P0.5 | Same item via Inventory API (`/inventory/v1/items/{id}`) vs Books | Whether Inventory carries more (batch flags, packaging); which API the adapter reads |
| P0.6 | `GET /itemgroups` (Inventory, documented) | Variant templates exist? count, attribute shapes |
| P0.7 | `GET /items/batches?item_id=…` for 3 batch-tracked items; detail `GET /items/batches/{id}` | Batch fields (`balance_quantity`, `location_id`, `associated_locations`, `label_rate`), pagination, whether a list without `item_id` is refused |
| P0.8 | `GET /compositeitems` (Inventory, documented) | Composite count, `combo_type`, `mapped_items` |
| P0.9 | Units: candidate `GET /settings/units` (Books/Inventory); your payload shape `{unit_id, name, unit, uqc, status, quantity_decimal_place, last_modified_time}` | Whether a units endpoint exists and where; whether unit conversions exist |
| P0.10 | Manufacturers: candidate `GET /manufacturers` (your payload `{manufacturer_id, manufacturer, address{…}, gst_no, brand_fssai_no, importer_fssai_no}`) | Endpoint, pagination, detail |
| P0.11 | Item image: documented Inventory image endpoints | How to fetch the bytes for the media gallery |
| P0.12 | A price list detail's `pricebook_items[].item_id` vs `GET /items` ids | Confirms the `item_zoho_id → item_id` backfill joins |

Candidate paths in P0.9–P0.10 are **hypotheses to probe**, not facts. If a probe 404s, the adapter is not built and the
master stays local (as brands was before its endpoint was found).

---

## 3. Adapters

Registry order matters (it is import order): `organizations` → … → `units` → `manufacturers` → `brands` (exists) →
`items` → `item_groups` → `composite_items` → `batches` → `price_lists` (exists; its hook gains item linking).

| Module key | Endpoint (Zoho name) | Table | Strategy | Detail | Direction (P3–P6) | Notes |
|---|---|---|---|---|---|---|
| `units` | P0.9 | `catalogue.units` | FULL | list = detail (expected) | INBOUND | `match_on=("code",)` adopts seeded units (D-6); `uqc` → `uqc_code` (unknown codes → NULL + data-quality report, never invented) |
| `manufacturers` | P0.10 | `core.manufacturers` | FULL | per probe | INBOUND | `match_on=()` (never merge by name — brands rule); hook writes identifiers + address link |
| `items` | `/items` + `/itemdetails` | `catalogue.items` | FULL (INCREMENTAL only if P0.4 proves the filter) | `index_then_detail`, **bulk** (E-C1), `detail_max_age_minutes` 1440 | INBOUND → BIDIRECTIONAL in P7 | main adapter, §4 |
| `item_groups` | `/itemgroups` | `catalogue.products` | FULL | detail for `items[]` + attributes | INBOUND | Zoho spelling only in the field map; hook writes `product_attributes`, `attribute_options`, `item_attribute_values`, `items.product_id` |
| `composite_items` | `/compositeitems` | `catalogue.items` (composition) + `item_components` | FULL | detail for `mapped_items` | INBOUND | Same Zoho id space as items? P0.8 decides whether a composite is also returned by `/items` (then this adapter only projects components onto the existing item) |
| `batches` | `/items/batches?item_id=` | `catalogue.batches` | FULL, **per-parent fan-out** (E-C2) | detail only if the list is thin | INBOUND → BIDIRECTIONAL in P7 | §5 |
| `item_stock` | `/itemdetails` (bulk) | `inventory.external_stock_levels` | INDEX lane, 30 min | — | INBOUND | snapshot only, never touches `items` rows (04 §7) |

---

## 4. Items — field map

Columns listed are Zoho's documented attribute names (Books `items.md`) or confirmed by P0.2; anything else waits for
the probe. Every unmapped key survives in `sync.sync_records.raw`.

| Zoho | Local | Notes |
|---|---|---|
| `item_id` | crosswalk + `zoho_id` | |
| `name` | `items.name` | max 100 in Zoho → the service refuses longer names for linked items |
| `sku` | `items.sku` | uniqueness collision with a local item → per-record failure, never a merge |
| `description` / `purchase_description` | same | |
| `status` | `items.status` (`active`/`inactive`) | |
| `product_type` | `items.product_type` | open set, no CHECK |
| `item_type` | `can_be_sold`, `can_be_purchased`, `is_inventory_tracked` | `sales` → sold only; `purchases` → purchased only; `sales_and_purchases`; `inventory` → both + tracked |
| `track_inventory` (P0.2) | `is_inventory_tracked` | wins over `item_type` when present |
| `track_batch_number` (P0.2) | `track_mode = 'batch'` | + `expiry_tracked` when the org tracks expiry (setting) |
| `unit` / `unit_id` | `base_unit_id` on first sight; afterwards the level named by `zoho_item_unit_id` | `unit_id` via `units` crosswalk (ReferenceRule, DEFER); `unit` string → by normalized code when no id; neither → NULL + data-quality flag. If a linked item's base unit was changed locally (e.g. Zoho keeps BOX, we stock PCS), Zoho's unit maps to `zoho_item_unit_id` and the base is not overwritten |
| `rate`, `purchase_rate` | `sales_rate`, `purchase_rate` | Decimal via `str()`; **divided by the `zoho_item_unit_id` level's `base_factor`** when that level is not the base (rates are stored per base unit) |
| `label_rate` (P0.2) | `mrp` | |
| `hsn_or_sac` | `hsn_or_sac` | |
| `is_taxable`, `tax_exemption_id` | `is_taxable`; exemption → `tax_assignments` | |
| `item_tax_preferences[] {tax_id, tax_specification}` | `tax.tax_assignments` (owner `item`, `source_system='zoho'`) | `tax_specification` intra/inter; unsynced tax → pending row + reconcile waiter (the categories hook, reused) |
| `account_id`, `purchase_account_id`, `inventory_account_id` | `accounting.account_assignments` (sales / purchase / inventory_asset) | `external_ref` keeps Zoho's id (accounts rule) |
| `vendor_id` | `item_vendors` (preferred) | parties crosswalk; merged ids resolve to the survivor |
| `reorder_level` | `reorder_level_base` | × the Zoho level's `base_factor` |
| `brand` (name string, live) | `brand_id` | lookup by `core.brands.name_normalized` in the org; no match → NULL + `sync.pending_references` keyed by name, resolved when the brands sync creates it (brands carry their own Zoho ids; items reference by name — the memory note) |
| `manufacturer` (name string) | `manufacturer_id` | same as brand |
| `category_id` (P0.2) | `core.categorizables` (Zoho taxonomy, owner `item`) | via `categories.service` |
| `upc`, `ean`, `isbn`, `part_number` | `item_identifiers` (base level, `source='zoho'`) | replace-set of Zoho-sourced rows only; local codes untouched |
| `package_details {length,width,height,weight,weight_unit,dimension_unit}` (P0.2) | `length/width/height`, `net_weight`, `weight_unit_id`, `dimension_unit_id` | units by code (`kg`,`g`,`lb`,`oz`,`l`; `cm`,`in`) |
| `custom_fields[]` | `extfields` (owner `item`, definitions learned with `zoho_field_id`) | parties pattern |
| `locations[]` | `external_stock_levels` (item lane) | volatile → `hash_volatile_keys` (a stock change is not an item change) |
| `image_id/name/type` | media gallery (task fetches bytes, P0.11) | `image_*` volatile for the hash; re-fetch only when `image_id` changes |
| `group_id` (Inventory) | `items.product_id` via `item_groups` crosswalk | DEFER |
| `created_time` | `source_created_at` | |
| `last_modified_time` | crosswalk fence | never a column |
| `stock_on_hand`, `available_stock`, … | **volatile**, not stored on items | |

Hook (`catalogue/zoho/hooks.py::after_item_upsert`): taxes, accounts, categories, vendors, identifiers, custom fields,
`item_units` base level (create when a base unit is known and none exists; never alter an existing hierarchy), and
**price-list linking**:

```sql
UPDATE pricing.price_list_items SET item_id = :item_id
 WHERE tenant_id = :tenant AND organization_id = :org AND item_zoho_id = :zoho_item_id
   AND item_id IS DISTINCT FROM :item_id AND deleted_at IS NULL;
```

plus a one-off backfill in the P3 migration over existing rows (zero API calls). `price_lists`' own hook does the
reverse lookup for rows it projects after items exist.

Backfill tool: `python -m app.modules.catalogue.zoho.backfill` replays stored documents (no API calls) after a hook
change — needed because the apply gate skips unchanged rows (the categories/accounts precedent).

### 4.1 Engine change E-C1 — bulk detail dispatch
Detail per item would be N calls; `/itemdetails?item_ids=` is documented. Add `detail_dispatch="bulk"` with
`bulk_detail_endpoint`, `bulk_id_param`, `bulk_size` (from P0.3) and `bulk_result_key` to `resolve_module_config`. The
engine groups the page's detail-needing ids (after the gate's skip) into bulk calls and applies each document as if it
came from a single detail call (same provenance class). Tests: provenance, partial bulk responses (an id missing from
the answer → that record's detail fails alone), 429 mid-bulk (E1 semantics: page committed, cursor stays).

---

## 5. Batches

Zoho documents the batch list **per item** (`item_id` is required). That is a fan-out: one list call per batch-tracked
item per run.

### 5.1 Engine change E-C2 — per-parent fan-out
`parent_module="items"`, `parent_filter` (only items with `track_mode` batch), `parent_param="item_id"`. The planner
treats each parent as a sub-cursor inside the run's lease (resume mid-way after a slice yields). With `include_empty_batches`
false by default, exhausted lots stop appearing; `filter_by=Status.All` (P0.7) keeps inactive ones.

Budget: THPL's batch-tracked item count × pages. If that is large, the lane runs daily for all parents and hourly
only for parents whose item `last_modified_time` moved or which appear in recent documents (a "hot parents" set kept in
Redis DB 0 under `zoho:batches:hot`).

### 5.2 Field map
| Zoho | Local |
|---|---|
| `batch_id` | crosswalk + `zoho_id` |
| `item_id` | `item_id` (ReferenceRule → items, DEFER) |
| `batch_number`, `manufacturer_batch_number` | same |
| `manufactured_date`, `expiry_date` | `manufactured_on`, `expires_on` |
| `label_rate`, `sales_rate` | `mrp`, `sales_rate` |
| `status` | `status` |
| `batch_custom_fields[] {custom_field_id, label, value}` | `extfields` (owner `batch`) |
| `balance_quantity`, `in_quantity`, `location_id`, `associated_locations` | `external_stock_levels` (volatile for the batch hash) |

---

## 6. Outbound (P7) — after outbox v2

* `catalogue.service.to_zoho_payload(item, intent)` builds Zoho's **write contract** (documented `POST/PUT /items`
  arguments), never the read document. Derived `item_type` from the booleans; `unit` from the code of the
  `zoho_item_unit_id` level (base when NULL) and `rate` / `purchase_rate` converted into it;
  `item_tax_preferences` from assignments; accounts from assignments; custom fields from `extfields` (`zoho_field_id`).
* Batches: documented `POST /items/batches`, `PUT /items/batches/{batch_id}`, `/active`, `/inactive`.
* Ownership after the flip: Zoho-fed fields become **co-owned**; the apply gate's three-way rule (field hash of the
  last pushed value) decides pull-vs-push conflicts — the platform's conflict/echo design (`zoho-sync-platform-
  architecture.md` G2), not something this module invents.
* Not pushed: merchandising, local barcodes per level, pack levels other than base, schemes, holds, storage
  locations, ledger (Zoho receives *documents*, and recomputes its own stock from them).
* Approval gate: local item creation can require approval before push (`zoho.module.items.push_requires_approval`).

---

## 7. Observability
Logger names `app.zoho.items`, `app.zoho.batches`, `app.catalogue.*`, `app.inventory.*` (per-module YAML in
`config/logging/modules/`). Runs, events and per-record failures appear in the existing operator API
(`/api/zoho/admin/*`) and Grafana panels with no new tables.
