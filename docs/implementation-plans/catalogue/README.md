# Catalogue, Batches & Inventory — implementation plan

> **Build progress (as built — this box wins over the plan where they differ)**
>
> | Phase | State | Where |
> |---|---|---|
> | P0 Zoho probes / vendored Inventory docs | ⏳ not started (needs the live connection) | — |
> | **P1 masters** | ✅ **built 2026-10-10** | migration `20261010_0900_66d0b2e09e76`; `app/modules/catalogue/`; `tests/test_catalogue_masters.py` (11) |
> | P2 items core … P8 | ⏳ | — |
>
> P1 as built: `catalogue.uqc_codes` (seeded, GLOBAL), `units`, `packaging_types`, `sales_channels`, `item_groups`,
> `attributes`, `attribute_options`; API `/api/catalogue/...`; permissions `catalogue.{unit,packaging_type,
> sales_channel,item_group,attribute}:{create,update,delete}`. Differences from the plan: (1) standard units are
> also seeded for **every new organization** by the `AFTER INSERT` trigger `trg_organizations_seed_catalogue` on
> `org_management.organizations` (the plan only named "the provisioning hook"; a DB trigger needs no tenancy-core
> import of the catalogue); (2) the migration's DDL is generated verbatim from `catalogue_schema.sql` and its
> table/column comments from the ORM models, so `alembic check` shows zero catalogue drift; (3) `alembic/env.py`'s
> `_OWNED_SCHEMAS` gained `catalogue` (without it `alembic check` never compared the schema); (4) `products` /
> `product_attributes` moved to P2 with the items they template. Permission targets resolve rows by uuid/id only
> — never by code, which is unique only per organization.

**Status:** PLAN, **revision 2** (2026-10-09) · nothing built yet · **Schemas:** `catalogue`, `inventory`, additions to
`pricing`, `core`, `geo`
**Packages (to be created):** `app/modules/catalogue/`, `app/modules/inventory/`, `app/modules/schemes/`
(+ changes to `price_lists`, `manufacturers`, `media`, `locations`, `zoho/sync`)
**Target SQL:** [`catalogue_schema.sql`](catalogue_schema.sql) — 33 new tables (+ the ledger's default partition), 3 views,
4 existing tables altered, 15 functions, 8 triggers; applied cleanly to a schema-only copy of the dev database (head
`5b8d2e71c4a9`, PostgreSQL 18.1). [`catalogue_schema_smoke_test.sql`](catalogue_schema_smoke_test.sql) — **36
behavioural checks, 36/36 passed** (hierarchy, immutability, cycles, ledger mode, ledger immutability, configurable
negative stock, month-precision expiry, expired-sale and shelf-life policies, availability-to-promise, FIFO ageing,
price windows, schemes), inside a rolled-back transaction.

> **Revision 2 (owner answers, same day).** Stock stays in `inventory` · negative stock is **configurable per
> organization** (and narrower scopes) · selling beyond expiry and the whole expiry/ageing rule set are
> **configurable** · offers need **no approval**. These became `inventory.stock_policies` (D-13) and
> [§6 Gap review](#6-gap-review-revision-2), which lists every other gap found on the second pass and how it was closed.

| Document | What it decides |
|---|---|
| **README.md** (this) | What was asked, the 12 architecture decisions, scope, phases at a glance, open questions |
| [01-domain-model.md](01-domain-model.md) | Every table, why it exists, how each pasted design was reconciled with what the platform already has, ERD |
| [02-units-and-packaging.md](02-units-and-packaging.md) | Units of measure, UQC, the packaging hierarchy, conversions, barcodes per level, rules |
| [03-pricing-and-offers.md](03-pricing-and-offers.md) | Pack-level prices, the quote order, the scheme (offer) engine |
| [04-batches-and-inventory.md](04-batches-and-inventory.md) | Lot master, holds/QC/expiry, storage locations, the stock ledger, balances, reservations, cut-over from Zoho |
| [05-zoho-sync.md](05-zoho-sync.md) | Adapters (units, manufacturers, items, item groups, composite items, batches), field maps, probes, engine changes |
| [06-api.md](06-api.md) | Every endpoint, permissions, DTOs (slim/fat), errors, idempotency |
| [07-document-lines.md](07-document-lines.md) | The contract estimates / invoices / sales returns / credit notes use to reference items, packs, batches, schemes |
| [08-build-plan.md](08-build-plan.md) | Phases, file layout, migrations, tests, docs to update, definition of done |

---

## 1. Understanding

You asked for an enterprise-grade **Item module**, plus a **Batch module** and a **Location/Inventory module**, that:

* is **organization-scoped** like everything else here;
* lets users attach **media, documents and comments** to items, products and batches;
* is **synced with Zoho** (Books/Inventory items, batches) through the existing sync engine — "for now", i.e. Postgres
  becomes the truth and Zoho one more synced system;
* will be referenced by **estimates, invoices, sales returns and credit notes**, so the line contract must be right;
* has a **packaging hierarchy** (carton → box → bottle → piece) on which **offers** can apply at any level;
* ships **full create / read / update APIs**.

You pasted ten source designs: brand owners, item sales channels, item components, item groups, item packs, an item
list example, packaging types, sales channels, tax groups, units; a batch audit (`wms.*`) with its target DDL and
architecture; a products/variants schema (`catalog.*` + `promo.*` + `sales.line_items`); Zoho manufacturer and unit
payloads; Zoho weight units; and a UoM/packaging-hierarchy design guide. All of it was read. The platform already
owns several of the things those designs create a second time; [01-domain-model.md §2](01-domain-model.md#2-reconciling-the-pasted-designs)
maps every pasted table to a decision, and none was dropped silently.

What I verified rather than assumed:

* **Codebase:** brands (`core.brands`, Zoho-fed), manufacturers (`core.manufacturers` + identifiers — and
  `brand_manufacturers.kind` already has `brand_owner`), parties (vendors), price lists (`pricing.*`, items referenced by
  `item_zoho_id` "until an items module exists"), taxes (`tax_assignments`), accounts (purposes `sales` / `purchase` /
  `inventory_asset` already seeded for items), categories, documents, media, comments, custom fields, tags, geo, the
  Zoho `locations` mirror, the sync crosswalk and apply gate. The registration helpers' own docstrings already use
  `code="item", target_schema="catalog"` as their example — this module was anticipated.
* **Zoho docs:** `docs/zoho-docs-md/items.md` (Books). The vendored set has **no** Inventory pages; Zoho's public
  Inventory API documents `/items/batches` (list needs `item_id`), `/compositeitems` (`combo_type` assembly | kit,
  `mapped_items`), `/itemgroups` (`attribute_name1..3`) and item `upc`/`ean`/`isbn`/`part_number`/`unit_id`/`group_id`.
  Units and manufacturers endpoints are not documented anywhere I could find — they are **probes**, never assumptions
  ([05-zoho-sync.md §2](05-zoho-sync.md#2-phase-0--discovery-probes-read-only)).
* **GST UQC list** (the codes an invoice line must carry for GSTR-1 HSN summaries) — seeded as a global reference.

---

## 2. Architecture decisions

| # | Decision | Why (one line) |
|---|---|---|
| **D-1** | Item master data lives in schema **`catalogue`** (as you asked — not `wms`/`catalog`); stock lives in **`inventory`**; offers join the existing **`pricing`** schema | Master data and stock movements have different owners, write rates and retention. If you want *everything* in `catalogue`, it is a schema rename in the migrations — say so before Phase 6 |
| **D-2** | **Item = the SKU** that documents reference; **product = optional variant template** (Zoho "item group"); **item group = merchandising group** (your Oral Care / Men's Grooming) | Three different concepts that the pasted designs and Zoho name inconsistently. Ours on our side; Zoho spelling only in field maps (the price-lists naming rule) |
| **D-3** | **One `catalogue.units` table** for count units (PCS, BOX, CTN) *and* physical units (g, kg, ml, l, cm, in), with `unit_class` + `si_factor`; GLOBAL `catalogue.uqc_codes` | Your "common table with types". Zoho's `weight_unit` strings (`kg, g, lb, oz, l`) resolve by code — `l` correctly lands as volume |
| **D-4** | **Packaging hierarchy = `catalogue.item_units`**, chained (each level contains N of another level of the same item), cached `base_factor`, **structure immutable** (change = retire + new level) | Preserves physical structure (pack-breaking, picking) *and* O(1) conversion; immutability makes the chain acyclic by construction and keeps historic documents correct |
| **D-5** | **Stock is only ever in base units**; lines store `(item_unit, qty)` as the customer said it **and** the snapshotted factor and base quantity | The classic mixed-UoM double-count bug cannot happen; a carton re-spec never recalculates history |
| **D-6** | Zoho units **adopt** the seeded standard units by normalized code (`match_on=("code",)`) | Deliberate exception to the "never merge by name" rule (brands/taxes): a unit symbol is a closed vocabulary, not a name. Flagged for your sign-off (Q-2) |
| **D-7** | **Batches are a slim lot master** (`catalogue.batches`); quantities, holds, CoA, custom fields, schemes, Zoho ids each go to the place the platform already has for them | Implements the batch audit's split without its parallel infrastructure (its L3 edge, lot-attribute EAV, own audit log, duplicate queue all already exist here as `sync.*`, `extfields`, activity, crosswalk) |
| **D-8** | **One append-only stock ledger** (signed base quantities, item × batch × location × status), **balances updated in the same transaction** by an atomic increment; a trigger on the incremented, locked row enforces the negative-stock policy; app-managed monthly partitions | ERPNext/Odoo-proven shape; overselling is impossible under concurrency unless the organization allows it; no async projector lag for allocation; pg_partman stays unused (house rule) |
| **D-9** | **Zoho stays the stock master until an explicit per-organization cut-over** (`ledger_mode: mirror → authoritative`, with an opening-balance movement from Zoho's figures) | Our ledger cannot be the truth while bills, invoices and adjustments are still created in Zoho. Until then Zoho's stock is a snapshot (`inventory.external_stock_levels`) |
| **D-10** | **Pack-level prices** = `pricing.price_list_items.item_unit_id` (+ explicit pack rates on `item_units`); **offers** = `pricing.schemes` with targets at **any catalogue level including a pack level or a batch** | "10+1 on cartons" ≠ "10+1 on pieces". One engine, one quote order, explain trace |
| **D-11** | **Inbound sync first, push second**: items/batches ship INBOUND with the `to_zoho_payload` seam; Zoho-owned fields on a linked item are read-only until outbox v2 lands, then the module flips to BIDIRECTIONAL | Without an outbox, a local edit to a Zoho-owned field is overwritten by the next pull (apply gate: Zoho wins). Local-only items and every local field are fully editable from day one |
| **D-12** | Media/documents/comments/custom fields/tags/taxes/accounts/categories come from the **existing polymorphic modules** via their mixins and registrations; the only platform change is a **media gallery** (ordered multi-image collection) | Extend, don't duplicate (master prompt directive 2) |
| **D-13** | **Stock rules are configurable as sparse scoped layers** — `inventory.stock_policies` at organization → warehouse → item group → item; per rule the most specific non-NULL value wins, then built-in defaults. Rules: `ledger_mode`, negative stock (separately for named lots), expired-sale policy (`block` / `override` / `warn` / `allow`), near-expiry days, minimum remaining shelf life (days and %), receiving shelf life, auto-mark-expired, allocation strategy (FEFO/FIFO/manual), ageing buckets | Your answers. Same shape as the fieldops policy layers. Typed columns, not the generic settings store, because the database enforces two of them (negative stock, ledger mode) in triggers |
| **D-14** | **Expiry has a precision** (`day` or `month`); every rule reads the generated `effective_expires_on` (end of month for "EXP 03/2027") | Indian pharma/FMCG packs print month/year; treating `03/2027` as 1 March would block a month of good stock |

---

## 3. Scope

**In scope (this plan):** units & UQC; packaging types; sales channels; item groups; attributes & variant templates;
items (+ merchandising, packaging hierarchy, identifiers/barcodes, components/BOM/kits, channel listings, vendors);
batches & holds; storage locations; stock movements, ledger, balances, reservations, stock policies; Zoho stock
snapshots; pack prices; offers/schemes; Zoho adapters for units, manufacturers, items, item groups, composite items,
batches; full API; search; the document-line contract.

**Out of scope, deliberately (and where it goes):**

| Not built | Why / where |
|---|---|
| Estimates, invoices, credit notes, sales returns themselves | Separate document modules; this plan defines the **contract** they consume ([07](07-document-lines.md)) |
| Purchase receipts (GRN), bills | Purchase module; it posts to the same ledger with `source_type='bill'`/`'purchase_receipt'` |
| Serial numbers | `track_mode` reserves `serial`; no tables until a SKU needs it |
| License plates / handling units (sealed vs opened cartons, SSCC) | Deferred until pick-face accuracy needs it ([02 §7](02-units-and-packaging.md#7-when-scalar-stock-is-not-enough-handling-units)) |
| FIFO cost layers, GL posting | Zoho does valuation and accounting; the ledger stores cost at posting time |
| Temperature logs, CoA lab-result EAV, batch duplicate-review queue | No sensor feed; CoA = documents; duplicates prevented by a unique key |
| Webhooks | Platform item (`webhooks.md` planned); polling lanes cover it |

---

## 4. Phases at a glance

| Phase | Delivers | Depends on |
|---|---|---|
| **P0** | Read-only Zoho probes + vendor the Inventory docs into `docs/zoho-docs-md/` | Zoho connection (live) |
| **P1** | `catalogue` masters: UQC, units (+ Zoho units adapter if P0 finds an endpoint), packaging types, sales channels, item groups, attributes | — |
| **P2** | Items core: items, merchandising, item_units, identifiers, attribute values, products, vendors, channels, components; mixin registrations; media gallery; full API; search | P1 |
| **P3** | Zoho items inbound (+ item groups → products, composite items → components, manufacturers), price-list `item_id` backfill | P2, P0 |
| **P4** | Batches + holds + Zoho batches adapter + Zoho stock snapshots | P3 |
| **P5** | Pack pricing quote service + schemes engine + evaluate API | P2 |
| **P6** | Inventory: storage locations, movements, ledger, balances, reservations, policies; cut-over runbook | P4 |
| **P7** | Push to Zoho (items, batches) on outbox v2 | Outbox v2 (platform) |
| **P8** | Document modules adopt the line contract | P5, P6 |

Details, migrations, tests and the definition of done: [08-build-plan.md](08-build-plan.md).

---

## 5. Questions

### 5.1 Answered (revision 2)

| # | Question | Answer → where it landed |
|---|---|---|
| **Q-1** | Stock tables in `inventory` or `catalogue`? | **`inventory`** (D-1 confirmed) |
| **Q-3** | Negative stock? | **Configurable per organization**, narrowed per warehouse / item group / item (`allow_negative_stock`); named lots separately (`allow_negative_batch_stock`, default false); only `available` status may ever be negative (CHECK). D-13, 04 §4.2 |
| **Q-4** | Sellable on/after expiry? Ageing? | **Configurable**: `expired_sale_policy` (`block` default / `override` with permission / `warn` / `allow`), near-expiry window, minimum remaining shelf life in days **and** %, receiving shelf life, auto-mark-expired, ageing buckets; month-precision expiry; expiry and FIFO stock-ageing reports. D-13, D-14, 04 §1.3 & §6 |
| **Q-6** | Offer approval? | **None** — `requires_approval` and the approve gate removed; activating needs `pricing.scheme:update` |

### 5.2 Still open (the default applies if you say nothing)

| # | Question | Default |
|---|---|---|
| **Q-2** | Zoho units adopt seeded units by code (D-6)? | Yes |
| **Q-5** | Who may release a recall/regulatory hold — any `catalogue.batch_hold:approve` holder, or a named QA role? | Permission only |
| **Q-7** | Must invoices refuse a rate above the (batch) MRP? | Yes, 422 `rate_above_mrp` for MRP items |
| **Q-8** | Which organizations allow negative stock initially, and should a negative position block *invoicing* or only warn? | Seeded `false` everywhere; when allowed, the line shows a warning |
| **Q-UQC** | GSTN "Great gross" code: GGK or GGR? Sources disagree | GGK (verify on the GST portal before go-live) |

---

## 6. Gap review (revision 2)

A second pass over every pasted design (the UoM/packaging guide, the products/variants schema, the `wms` batch DDL,
the promo/sales DDL) against revision 1. Each row is a real gap that revision 1 left open; all are closed in the SQL
and the documents, and the new behaviour is covered by the smoke test where the database owns it.

| # | Gap (source) | Fix |
|---|---|---|
| G-1 | Negative stock was a hard CHECK (your answer) | Policy-driven trigger `guard_negative_stock`; named lots separate; non-available statuses never negative; moving a negative position towards zero always allowed; `ix_stock_balances_negative` work queue (04 §4.2) |
| G-2 | Expiry selling and ageing were hard-coded (your answer) | `stock_policies` expiry rules; `v_batch_expiry` (days to expiry, % shelf life left, status, bucket, sellable); `stock_ageing()` FIFO ageing with policy buckets; daily auto-mark-expired task (04 §1.3, §6) |
| G-3 | "EXP 03/2027" packs: an exact date would expire stock a month early | `expiry_precision` + generated `effective_expires_on` (D-14) |
| G-4 | `min_remaining_shelf_life_days` sat on the item, so one item had one rule everywhere | Moved into the policy layers (item → group → warehouse → org), plus a % rule and a receiving rule |
| G-5 | `ledger_mode` was a soft application setting — a stray posting in mirror mode would silently create a second truth | Organization-scope policy column + `require_authoritative_ledger` trigger; cut-over flips and posts the opening movement in one transaction |
| G-6 | UoM guide: "an alternate UoM is not sellable without an explicit price" — revision 1 defaulted `derive_price` to true | Default **false**; deriving is an explicit per-level opt-in (02 §2.1, 03 §2) |
| G-7 | UoM guide: price-list lines have validity windows (`effective_from/to`); ours had none, so a carton re-price overwrote history | `valid_from`/`valid_to` on `pricing.price_list_items`, overlap refused by trigger (no btree_gist); Zoho rows stay window-less (03 §1) |
| G-8 | Zoho knows ONE unit per item; if THPL stocks in PCS but Zoho sells in BOX, revision 1 would have pushed/pulled rates and quantities in the wrong unit | `items.zoho_item_unit_id` — the level Zoho's unit means; every Zoho rate/quantity converts through it (05 §4, 07 §5) |
| G-9 | Availability netted only lot-level reservations; item-level promises (an order without a chosen lot) were ignored | `v_item_warehouse_availability` nets both and reports sellable / near-expiry / expired quantities and the earliest sellable expiry |
| G-10 | Pharma search: products are asked for by salt and trade aliases ("Crocin") | `items.generic_name` + `alias_names[]` with trigram/GIN indexes and in the search registry |
| G-11 | Products paste: storefront flags (`is_featured`, short description) had no home | Added to `item_merchandising` |
| G-12 | UoM guide line contract snapshots the base unit too | `base_unit_code` added to the line contract (07 §1) |
| G-13 | Offer approval workflow (your answer) | Removed: no `requires_approval`, no `pricing.scheme:approve` |
| G-14 | Revision 1 used the pre-rename index name `uq_price_list_items_book_item`; the live name is `uq_price_list_items_list_item` (found by applying the SQL to the dev schema) | Corrected |
| G-15 | `item_stock_policies` (reorder settings) would have collided by name with the new rule layers | Renamed `inventory.replenishment_policies` |

Checked and **deliberately unchanged**: LPN/handling units (still deferred, 02 §7); customer-specific override table
(a party price list already is one); a generic "repack" movement (re-denominating moves nothing, 02 §6); the `wms`
compatibility views, temperature logs, lot-attribute EAV and duplicate queue (01 §2.3 — no legacy readers, no sensor
feed, `extfields` exists, exact lot keys).

---

## 7. Sources

Research used where the codebase and the vendored docs were silent:

* Zoho Inventory API: [Items](https://www.zoho.com/inventory/api/v1/items/) ·
  [Batches](https://www.zoho.com/inventory/api/v1/batches/) ·
  [Composite items](https://www.zoho.com/inventory/api/v1/compositeitems/) ·
  [Item groups](https://www.zoho.com/inventory/api/v1/itemgroups/) — to be vendored into `docs/zoho-docs-md/` in P0
  (the "docs are law" rule: adapters are built against vendored docs, not memory).
* GST UQC list: [Zoho Books India KB — unit code list](https://zoho.com/in/books/kb/gst/unit-code-list.html),
  [ClearTax](https://Cleartax.in/s/gst-unit-quantity-code-uqc),
  [Tally](https://tallysolutions.com/gst/uqc-unit-quantity-code-under-gst/).
* Patterns (from training knowledge, not fetched): GS1 packaging hierarchy (a GTIN per level); SAP alternative units
  of measure; ERPNext Stock Ledger Entry + Bin (signed quantity ledger + in-transaction balance); Odoo stock moves /
  quants. Compliance items (Drugs & Cosmetics Rules schedules, FSSAI, DPDP) are **verify with counsel**.
