# 08 — Build plan

Each phase ends deployable, migrated on dev, with its tests green and its docs updated. Migrations are hand-checked
Alembic revisions that produce exactly the DDL of [`catalogue_schema.sql`](catalogue_schema.sql) for their tables
(autogenerate as a starting point, then partial indexes, `NULLS NOT DISTINCT`, triggers and seeds by hand; random
revision ids; chained on the current head).

---

## 1. Package layout

```
app/modules/catalogue/
├── __init__.py
├── enums.py              CATALOGUE_SCHEMA, ItemStatus, TrackMode, Composition, UnitClass, IdentifierKind, HoldType …
├── model/                one file per table group (taxes-module style)
│   ├── reference.py      UqcCode, Unit, PackagingType, SalesChannel, ItemGroup, Attribute, AttributeOption
│   ├── product.py        Product, ProductAttribute
│   ├── item.py           Item, ItemMerchandising, ItemAttributeValue, ItemIdentifier, ItemComponent,
│   │                     ItemSalesChannel, ItemVendor
│   ├── item_unit.py      ItemUnit
│   └── batch.py          Batch, BatchHold
├── schema/               Pydantic DTOs: *SlimOut / *Out / *Create / *Update per resource
├── crud/                 SQL only; list_slim uses load_only, get_fat uses explicit loaders
├── service/              items.py, units.py (hierarchy service), batches.py, masters.py, identifiers.py (GTIN)
├── units.py              pure conversion functions (to_base, convert, breakdown)
├── pricing.py            quote() + explain trace
├── lines.py              ItemLine validator, to_zoho_line (07)
├── mixins.py             HasItemMixin / ItemLineMixin (document modules use these)
├── api_masters.py · api_items.py · api_batches.py
├── tools/import_case_sizes.py
└── zoho/                 units/, items/, item_groups/, composite_items/, batches/ adapters (spec, fields, hooks), backfill.py

app/modules/inventory/
├── enums.py · model.py (StorageLocation, ReasonCode, StockMovement(+Line), StockLedgerEntry, StockBalance,
│                        StockReservation, ReplenishmentPolicy, ExternalStockLevel)
├── posting.py            THE write path to ledger + balances (04 §4.1)
├── allocation.py         FEFO allocation, reservations
├── movements.py          draft/post/cancel of internal movements
├── partitions.py         monthly partitions (fieldops copy)
├── cutover.py            ledger_mode switch (04 §2.3)
├── reconciliation.py     drift report vs Zoho snapshot
└── api.py · schema.py · crud.py

app/modules/schemes/      model.py (pricing.schemes*), engine.py (pure), service.py, registry.py (usage sources), api.py, schema.py, crud.py
```

Import rules (`.importlinter`): `catalogue` may import `brands`, `manufacturers`, `parties`, `taxes`, `accounting`,
`categories`, `documents`, `media`, `comments`, `custom_fields`, `tags`, `currencies`; **nothing it imports may
import it** (`taxes-never-import-a-consumer` extended). `inventory` imports `catalogue`; `schemes` imports `catalogue`
and `price_lists`; none of the three imports a document module. Platform `zoho/*` never imports them (existing
source-scan test).

Relationships: every relationship `lazy="raise"` (masters) or `raise_on_sql` (polymorphic mixins); loaders stated in
each model docstring: lists → `load_only`; item detail → `selectinload(units, identifiers, components, channels,
vendors, attribute_values, media, tags, categories, tax_assignments, custom_field_values)` +
`joinedload(brand, manufacturer, base_unit, item_group, product, merchandising)`.

---

## 2. Phases

### P0 — Discovery & docs (≈1 day, no code)
* Probes P0.1–P0.12 (05 §2), read-only, logged.
* Vendor Zoho Inventory pages into `docs/zoho-docs-md/` (`inventory-items.md`, `batches.md`, `composite-items.md`,
  `item-groups.md`) and any probed undocumented endpoint as `*-live.md` with the probe evidence.
* Output: decisions recorded in this folder (`P0-findings.md`): item count, bulk size, filter support, units /
  manufacturers endpoints, batch fan-out size, first-sync budget in calls and hours.

### P1 — Catalogue masters
* Migration 1: schema `catalogue`; `uqc_codes` (+ seed), `units` (+ `seed_standard_units` for every organization and
  the organization-provisioning hook), `packaging_types`, `sales_channels`, `item_groups`, `attributes`,
  `attribute_options`; mixin indexes; `core.entity_types` rows for `item_group`.
* Services + API §2 of 06 (masters); permissions; media `item_group` banner.
* Zoho `units` adapter if P0.9 found an endpoint; `manufacturers` adapter if P0.10 did (+ `zoho_id`, `fssai_importer`).
* Tests: §3 below (masters).

### P2 — Items core
* Migration 2: `products`, `product_attributes`, `items`, `item_merchandising`, `item_attribute_values`, `item_units`
  (+ triggers), `item_identifiers`, `item_components` (+ trigger), `item_sales_channels`, `item_vendors`;
  registrations (taxes, accounts, comments, categories whitelisting on each org's Zoho taxonomy, entity types).
* **Media gallery** (platform change, own migration): `media.items.order_column` (smallint, default 0) +
  `COLLECTION_DEFAULTS["gallery"]` (public, thumb/medium/large conversions) + `media.service.add_image` /
  `reorder` / `remove_image` used by owner endpoints. Avatar behaviour unchanged (single-image collection).
* Enums: `DocumentLinkableType` += `item, product, batch, stock_movement`; document link role `coa`, `compliance`.
* Services: item create (composite payload in one transaction), hierarchy service, identifiers (GTIN check digit),
  components, channels, vendors, quote stub (item default + pack rate + price list base), data-quality report.
* API §3 of 06; search wiring (Debezium include, topic, registry).
* Tests: §3 (items).

### P3 — Zoho items inbound
* Engine change **E-C1** (bulk detail) with its own tests and docs update (`docs/ZOHO_SYNC_ENGINE.md`,
  `zoho-sync-implementation/apply-gate.md`).
* Adapters `items`, `item_groups`, `composite_items`; hooks (05 §4); `catalogue.zoho.backfill`.
* Migration 3: `pricing.price_list_items` + `item_id`/`item_unit_id`, backfill `item_id` from the crosswalk.
* First sync as **leased manual slices** (parties precedent), celery-beat stopped during it; audit afterwards: every
  stored Zoho key accounted for by a column, a hub (taxes/accounts/categories/identifiers/extfields/media), a
  volatile list, or a deliberate exclusion (the parties data audit method) → `adapters/items.md` §audit.
* Tests: §3 (sync).

### P4 — Batches
* Migration 4: `batches` (incl. `expiry_precision` / `effective_expires_on`), `batch_holds`; schema `inventory` with
  `storage_locations` (+ path trigger, `geo.places` scope key), `reason_codes` (+ seed), **`stock_policies`** (+ seeded
  organization layer, `effective_stock_policy()`), `v_batch_expiry`, and `external_stock_levels` — snapshots and holds reference them before the
  ledger exists. The `locations` adapter hook starts creating warehouse roots for Zoho locations here.
* Engine change **E-C2** (per-parent fan-out); `batches` adapter; `item_stock` INDEX lane.
* Batch API (06 §4), holds, QC, CoA documents; policy API + `inventory/policy.py` (batch resolver, same precedence as
  the SQL function — a parity test runs both); expiry report API.
* Tests: §3 (batches).

### P5 — Pricing & schemes
* Full `quote()` ladder (03 §2) incl. batch, channel, pack-level price lists; MRP guard.
* Migration 5: `pricing.schemes`, `scheme_targets`, `scheme_slabs`, `scheme_eligibility`.
* `schemes.engine` (pure) + service + API (06 §6) + daily expiry task (Celery `default` queue, planner-free: a beat entry
  is acceptable here — it is not a Zoho module).
* Tests: §3 (pricing, schemes).

### P6 — Inventory
* Migration 6: `stock_movements`(+lines), `stock_ledger_entries` (+ default partition, immutability trigger, first
  months), `stock_balances`, `stock_reservations`, `replenishment_policies`, view, `rebuild_balances`, entity types.
* Storage-location API (bins, zones) on top of the warehouse roots created in P4.
* posting, movements, allocation, reservations, partitions task, reconciliation report, cut-over command (not run).
* `ledger_mode` lives in `stock_policies` (organization layer; trigger-enforced); `guard_negative_stock`,
  `v_item_availability`, `v_item_warehouse_availability`, `stock_ageing()`; daily auto-mark-expired task
  (Celery `default` queue) and negative-stock / ageing APIs.
* Tests: §3 (inventory).

### P7 — Push (blocked on outbox v2)
`to_zoho_payload` for items and batches; flip directions to BIDIRECTIONAL; approval gate; ownership three-way rule.

### P8 — Document modules adopt 07
Out of this plan's build, but each document module's plan cites 07 and uses `ItemLineMixin`, `validate_line`,
`posting.post`, `allocation`, `schemes.evaluate`.

---

## 3. Tests (per `<testing_doctrine>`)

| Area | Layer | Tests |
|---|---|---|
| Conversions | unit | `to_base`/`convert`/`breakdown` incl. decimals, branches, retired levels; property test: `convert(convert(q,a,b),b,a) == q` |
| Hierarchy DB rules | integration | the 20 checks of `catalogue_schema_smoke_test.sql` as pytest (factor, immutability, retire-contained, base mismatch, base lock, cycle, kit stock, uniqueness, ledger immutability, idempotent legs, no negative, availability, holds, rebuild) |
| Items API | integration | create composite payload (one transaction, rollback on any child error), slim list column count (`load_only` asserted via SQL capture), N+1 guard (query count constant for 1 vs 50 items), row_version 409, `zoho_owned_field` 409, delete-in-use 409, RBAC `Perm` presence (existing route test) |
| Identifiers | unit | GTIN-8/12/13/14 check digits; whitespace normalization; scannable uniqueness across kinds |
| Zoho items | e2e (`ZohoWire`) | list→bulk detail, provenance (list never overwrites detail), hash no-op on stock-only change, brand by name + pending reference resolution, taxes/accounts/categories/identifiers/custom fields projected, price-list `item_id` linking, revive soft-deleted by zoho id, mass-delete guard |
| Engine E-C1/E-C2 | unit + e2e | bulk partial answer, 429 mid-bulk keeps cursor; fan-out resume across slices |
| Batches | integration | normalized uniqueness, expiry required, holds open/release history, QC gating availability |
| Quote | unit | every ladder step, `derive_price=false`, volume brackets per level, MRP guard, explain trace |
| Schemes | unit (pure engine) | level-scoped targets (CTN ≠ BTL), thresholds in another unit, repeat rewards, stacking/priority determinism, exclusions, eligibility, limits; golden examples of 03 §4 |
| Posting | integration | concurrent oversell (two transactions, one gets `insufficient_stock`), deterministic lock order (no deadlock under parallel opposite-order postings), replay idempotency, reversal, partition auto-create, rebuild == incremental |
| Availability/allocation | integration | FEFO / FIFO / manual per policy, shelf-life days and %, holds, lot + item reservation netting, over-promise shows negative |
| Stock policies | unit + integration | layer precedence per rule (item > group > warehouse > org > default), SQL vs Python parity, expired-sale `block/override/warn/allow`, negative stock allowed / refused / named-lot refused / towards-zero always allowed / non-available never negative, ledger insert refused in mirror mode |
| Expiry & ageing | integration | month precision (EXP 03/2027 → 31 Mar), expiry status and buckets, FIFO ageing incl. partial receipts, `as_of` reproducibility, auto-mark-expired task legs |
| Price windows | integration | consecutive windows accepted, overlap refused, quote picks the window of the document date |
| Cut-over | integration | opening movement equals snapshot, drift zero, mode flip refused when preconditions fail |
| Tenancy | conformance | every new table classified (ENTITY/LEDGER/GLOBAL with reason) |
| Search | unit | registry attributes exist on the model |
| Import contracts | unit | new `.importlinter` contracts |

Every table tests write to goes into `tests/conftest.py::_TEST_TABLES`. Never seed the pytest DB (memory:
seeding-vs-test-database); seeded units come from the migration, which is the suite's contract.

---

## 4. Docs to update (named, per phase)

`docs/MODULES.md` (catalogue, inventory, schemes), `docs/PROJECT_STRUCTURE.md`, `docs/ZOHO_SYNC_ENGINE.md` (E-C1,
E-C2), `docs/zoho-sync-implementation/README.md` (adapter rows) + `adapters/{units,manufacturers,items,item-groups,
composite-items,batches}.md`, `docs/zoho-sync-implementation/ERRORS-AND-THEIR-RESOLUTIONS.md` (append),
`docs/tenancy/README.md` (new GLOBAL/LEDGER entries), `docs/rbac-module.md` (permissions), `apps/core-platform/docs/
media-storage.md` (gallery), `deployment/config/debezium/zoho-mirror-connector.json` (`catalogue.items`), this folder
(as-built box at the top of README, like the contacts plan).

---

## 5. Definition of done (per phase)

- [ ] Migration up → down → up on scratch; `alembic check` shows only the known house-wide index-name drift.
- [ ] DDL matches `catalogue_schema.sql` for the phase's tables (column-ledger test).
- [ ] Nullability: business columns on Zoho-fed rows nullable unless a stated rule (tables here: NOT NULL only for
      flags we own with defaults, keys, and quantities of our own ledger).
- [ ] No `metadata` attribute; partial unique indexes on every soft-deletable uniqueness; live `zoho_id` indexes.
- [ ] Loader strategy stated for every relationship; slim lists use `load_only`; N+1 test exists.
- [ ] Zoho calls only through the engine/transport/governor; new adapters exercised through `ZohoWire`.
- [ ] Logging `structlog.get_logger("app.catalogue.<area>")` etc., structured kwargs.
- [ ] Every mutating route has `Perm`; new codes in `rbac/catalogue.py`.
- [ ] Search wiring complete (3 steps) where applicable.
- [ ] No new host port, Redis DB, image or extension (none needed: `pg_trgm` already installed; no pg_partman).
- [ ] Docs in §4 updated, not deferred.
