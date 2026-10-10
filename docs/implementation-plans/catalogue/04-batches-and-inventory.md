# 04 — Batches & inventory

---

## 1. Batches (lot master)

`catalogue.batches` is the **identity of a lot of an item** — what is printed on the pack — and nothing else.

| Fact | Where |
|---|---|
| Lot number, manufacturer/supplier lot numbers | `batch_number` (+ normalized unique key per item), `manufacturer_batch_number`, `supplier_batch_number` |
| Dates | `manufactured_on`, `expires_on`, `best_before_on` (business dates, `date`) |
| Commercials printed/agreed per lot | `mrp` (Zoho `label_rate`), `sales_rate` |
| Who made / supplied it | `manufacturer_id` (when it differs from the item's), `supplier_id` (party, role vendor) |
| Quality | `qc_status` (`not_required` → `pending` → `passed`/`failed`), `qc_decided_at/by`; CoA = document link role `coa` |
| Holds | `catalogue.batch_holds` (§1.2) |
| How much, where | **never here** — `inventory.stock_balances` / ledger; Zoho's `balance_quantity` → `inventory.external_stock_levels` |
| Custom attributes | `extfields` (Zoho `batch_custom_fields`) |
| Documents, photos, comments, tags | `HasDocumentsMixin`, `HasMediaMixin`, `HasCommentsMixin`, `HasTagsMixin` |

### 1.1 Lifecycle and rules
* Created by a receipt (purchase module), an opening movement, the Zoho sync, or `POST /api/catalogue/batches`.
* `requires_qc` items get `qc_status='pending'` on creation; stock of a pending/failed lot is not available (view).
* `expires_on` required when the item is `expiry_tracked` (service, 422 `expiry_required`); derived default
  `manufactured_on + shelf_life_days` offered by the API, never silently written.
* `expiry_precision`: `day` (exact) or `month` (the pack prints "EXP 03/2027"). The generated `effective_expires_on`
  (31 Mar 2027 in that example) is the **only** expiry date any rule, view, report or allocation reads.
* Receiving a lot with less than the policy's `receipt_min_shelf_life_days` left → 422 `shelf_life_too_short_on_receipt`
  (a warning instead when the receiving user holds `catalogue.batch:manage`).
* Batch number uniqueness is per item on the whitespace-free upper-cased value (`b-2026 01` ≡ `B-202601`).
* A batch with ledger rows cannot be deleted (409 `batch_in_use`); it is deactivated.
* Editing `expires_on` on a lot with stock is allowed (misprint corrections happen) but recorded in activity with
  before/after and requires `catalogue.batch:manage`.

### 1.2 Holds
`batch_holds` rows are **effective-dated facts**: placed_at → released_at. At most one open hold per (lot, type); holds
of different types may overlap (a recall during QC). A lot with any open hold is excluded from availability and from
allocation. Releasing sets `released_at/by` + note; the row stays. "Was this lot quarantined last Tuesday?" =
`placed_at <= t AND (released_at IS NULL OR released_at > t)`.

Recall workflow (thin, on purpose): place a `recall` hold on every lot named in the recall → availability drops to
zero immediately → the ledger answers "who received it" (`source_type` sale/invoice, `batch_id`) for the recall
report (`GET /api/inventory/batches/{ref}/trace`).

### 1.3 Expiry, shelf life and ageing — configurable (rev 2)

All rules live in `inventory.stock_policies` (sparse layers: organization → warehouse → item group → item; the most
specific non-NULL value of each rule wins, then the built-in default). The organization layer is seeded with the
defaults below so they are visible and editable.

| Rule | Default | Effect |
|---|---|---|
| `expired_sale_policy` | `block` | `block`: an expired lot can never be allocated or sold. `override`: allocatable only by a user holding `catalogue.batch:use`, with a reason recorded on the line. `warn`: sellable, the line carries `expiry_warning`. `allow`: sellable silently (e.g. non-medicinal FMCG past best-before, if the business wants it) |
| `near_expiry_days` | 90 | Lots inside this window are `near_expiry` on dashboards, availability and the FSA catalogue (clearance candidates) |
| `min_remaining_shelf_life_days` / `_pct` | 0 / 0 | Do not **sell** a lot with fewer days / less % of its shelf life left; the stricter wins (status `below_min_shelf_life`). Party-specific minimums (hospital tenders demanding 75 %) are a later item layer on the party |
| `receipt_min_shelf_life_days` | 0 | Do not **receive** short-dated supplier stock (§1.1) |
| `auto_mark_expired` | true | Daily task (authoritative mode): moves every expired lot's `available` stock to status `expired` with `status_out`/`status_in` legs and reason `expired`, so expired stock is physically and financially segregated. `false` leaves it in place and relies on `expired_sale_policy` |
| `allocation_strategy` | `fefo` | `fefo` (earliest effective expiry first), `fifo` (earliest receipt first), `manual` (the user picks lots) |
| `ageing_bucket_days` | {30,60,90,180,365} | Bucket edges for both reports below |

Reports (organization-scoped, policy applied):

* **`inventory.v_batch_expiry`** — per lot: `days_to_expiry` (negative once expired), `shelf_life_left_pct`,
  `ageing_days` (how long *we* have held it, from `first_received_on`), `expiry_status`
  (`no_expiry` | `in_date` | `near_expiry` | `below_min_shelf_life` | `expired`), `expiry_bucket_days`, `is_held`,
  `is_sellable`. API: `GET /api/inventory/expiry` with status / bucket / warehouse / brand filters.
* **`inventory.stock_ageing(tenant, org, as_of)`** — how long current stock has been held, per item × warehouse × lot,
  bucketed. FIFO attribution: on-hand quantity is assigned to the most recent inbound legs (receipts, openings,
  returns, transfers-in) newest-first until covered — the standard method for stock without lots, exact per lot.
  A transfer resets age at the receiving warehouse by design. API: `GET /api/inventory/ageing`.
* `as_of` makes ageing reproducible for an audit (the ledger is the history).

---

## 2. Who is the stock master — and the cut-over

Today Zoho Inventory holds THPL's stock, batches and their balances, and every bill, invoice and adjustment that moves
stock is still created there. A local ledger that is not fed by *every* stock-moving document would be a second,
wrong truth. So:

### 2.1 `ledger_mode` per organization (`inventory.stock_policies`, organization layer only)
| Mode | Meaning |
|---|---|
| `mirror` (default) | Zoho is the stock master. Our ledger is not written for this organization; availability APIs answer from `external_stock_levels` (Zoho's per-location and per-batch figures), labelled `source: zoho, as_of`. Batches still sync (identity, dates, MRP) |
| `authoritative` | Our ledger is the stock master. Every stock-moving document posts here first; Zoho receives the documents through the outbox |

The database enforces it: `inventory.require_authoritative_ledger` refuses any ledger insert for an organization still
in `mirror` (SQLSTATE 55000 → 409 `ledger_mode_mirror`). A partial ledger cannot come into existence by accident.

### 2.2 Preconditions to switch (checked by the cut-over command, refused otherwise)
1. Document modules that move stock (sales invoices/deliveries, credit notes/returns, bills/receipts, adjustments,
   transfers) post to the ledger and push to Zoho (outbox v2).
2. Storage locations exist for every Zoho location with stock (`zoho_location_id`).
3. A fresh Zoho stock snapshot (≤ 1 h) for every tracked item and batch.

### 2.3 The cut-over (`python -m app.modules.inventory.cutover --organization THPL --as-of 2026-12-31`)
1. Freeze Zoho stock edits (operational step, documented in the runbook).
2. Refresh snapshots; build one `opening` stock movement per warehouse whose lines are Zoho's per-batch,
   per-location balances (base units; `unit_cost` from Zoho's valuation when available).
3. In ONE transaction: flip `ledger_mode` to `authoritative`, post the opening movement, reconcile `stock_balances` vs
   the snapshot (must be zero drift) — any drift rolls the whole cut-over back, leaving the organization in `mirror`.
4. From then on, `external_stock_levels` is only a reconciliation input (nightly drift report, never auto-corrected).

---

## 3. Storage locations

`inventory.storage_locations`: `warehouse → zone → aisle → rack → shelf → bin` (+ `staging`, `virtual` roots such as
"in transit"), materialized path `/<root>/…/<id>/` maintained by trigger (house style: text path, not ltree).

* A **warehouse** root is created for each Zoho location by the `locations` adapter's `post_upsert` hook
  (`zoho_location_id`, `place_id` = the geo place that hook already projects). Warehouses can also be created locally.
* `counts_as_available=false` marks QC, returns and damage areas; `is_pickable` / `is_receivable` steer the
  allocation and putaway services; `temperature_zone` must satisfy the item's `storage_condition` (putaway refuses
  a cold-chain item into an ambient bin: 422 `storage_condition_mismatch`).
* Moving a subtree re-roots descendants in one statement (trigger, no `row_version` bump — the teams precedent).

---

## 4. The stock ledger

`inventory.stock_ledger_entries` — the only stock truth.

* **Grain**: one row per (source line, item, batch, location, stock status, movement type) leg.
* **Signed** `quantity_base` in the item's base unit: `+` into the location/status, `−` out. A transfer is two legs
  (`transfer_out` −, `transfer_in` +); a status change is two legs (`status_out`, `status_in`).
* **Snapshots** of how the source expressed it: `item_unit_id`, `unit_code`, `quantity_in_unit`, `conversion_factor`.
  Never recomputed.
* **Source**: `source_type` (a `core.entity_types` code: `stock_movement`, `invoice`, `credit_note`, `bill`,
  `sales_return`, …), `source_id`, `source_line_id`, `source_number` (display). Any module can post; the FK to the
  registry keeps the type honest.
* **Immutable**: UPDATE/DELETE raise (trigger). Corrections are `reversal` legs referencing the reversed entry
  (`reverses_entry_id`, `reverses_business_date` — the partition key travels with the reference).
* **Idempotent**: `uq_stock_ledger_entries_source_leg` — replaying a posting (retry, outbox redelivery) cannot
  double-book.
* **Value**: `unit_cost`, `value_delta` at posting time (organization base currency). FIFO layers / landed cost are
  out of scope (Zoho values stock until a costing module exists).
* **Time**: `business_date` (the document's date; partition key) and `posted_at` (when it hit the ledger). Back-dated
  postings are allowed within an open period; a period lock (`inventory.period_locks`, later) will refuse posting
  before a closed date.
* **Partitions**: monthly, app-managed by `inventory/partitions.py` (copy of `fieldops/partitions.py`: create the
  month on demand inside the posting path when missing, plus a daily task creating three months ahead), DEFAULT
  partition as the safety net with an alert when it receives rows.

### 4.1 Posting (the one write path)
`inventory.posting.post(entries: list[LedgerLeg], *, source) -> PostResult`, called inside the caller's transaction:

1. Validate legs (item tracked, batch required iff `track_mode` batch, location receivable/pickable, statuses).
2. Sort legs by `(item_id, batch_id, location_id, status)` — deterministic lock order, no deadlocks between two
   postings touching the same positions.
3. `INSERT` the ledger rows (one multi-row statement).
4. Upsert balances in the same order:
   `INSERT … ON CONFLICT (tenant, org, item, batch, location, status) DO UPDATE SET quantity_on_hand =
   stock_balances.quantity_on_hand + EXCLUDED.quantity_on_hand, last_entry_at = …, updated_at = now()`.
   The `guard_negative_stock` trigger evaluates the incremented row while it is locked. A position that would go
   below zero is refused — unless the effective policy allows it (§4.2) — so the whole posting rolls back →
   409 `insufficient_stock` with the item/batch/location named.
5. Consume matching reservations (§6).

No Celery, no projector: the balance is correct the moment the transaction commits. `inventory.rebuild_balances()`
recomputes from the ledger; a nightly job runs it into a shadow comparison and reports drift (expected: none).

---

### 4.2 Negative stock — configurable (rev 2)
* `allow_negative_stock` (default false) lets a **non-lot** `available` position go below zero — the "goods left before
  the purchase paperwork was entered" case. Scoped like every rule: allow it for one warehouse or one item group only.
* `allow_negative_batch_stock` (default false, separate on purpose): a **named lot** below zero means the wrong lot was
  picked; it stays refused unless explicitly allowed.
* Only `available` status can ever be negative (CHECK) — a negative damaged or in-transit bucket is always a bug.
* A posting that moves a negative position **towards** zero is always accepted, even after the policy is switched off,
  so the backlog can always be booked in.
* Negative positions are a work queue: `ix_stock_balances_negative`, `GET /api/inventory/negative-stock`, and the
  nightly reconciliation report lists them with age.
* Valuation: an issue against negative stock carries the item's last known cost; the receipt that clears it records
  its real cost (no retroactive correction — Zoho values stock, §8).

## 5. Internal stock movements

`inventory.stock_movements` + `stock_movement_lines` (draft → posted → cancelled) for what is not a sales/purchase
document:

| movement_type | Legs per line |
|---|---|
| `opening` | `+` at `to_location` |
| `adjustment` | `+` or `−` (reason code direction) |
| `write_off` | `−` (reason required; expired/damaged) |
| `transfer` | `−` from, `+` to (two-step transfers use the virtual "in transit" root) |
| `cycle_count` | the difference between `counted_quantity_base` and the balance at posting time |
| `status_change` | `status_out` / `status_in` (available → damaged, quarantine → available) |
| `assembly` | `−` each component (BOM × qty, wastage applied), `+` the assembled item |
| `disassembly` | the reverse |

Numbering: `movement_number` from a per-organization sequence (`ADJ-2026-000123`), assigned at posting. Cancelling a
posted movement posts exact reversal legs and sets `cancelled_*`; the original legs stay.

---

## 6. Availability, reservations, allocation

* **Availability**:
  * `inventory.v_item_availability` — per item × warehouse × lot: on hand in `available` status in locations that count
    as available (negative positions included so allowed negatives net correctly), lot reservations, `quantity_free`,
    plus the lot's `effective_expires_on`, `days_to_expiry`, `expiry_status`, `is_held`, `is_sellable` (policy applied).
  * `inventory.v_item_warehouse_availability` — per item × warehouse: on hand, **sellable**, reserved (lot **and**
    item-level), **available to promise**, earliest sellable expiry, near-expiry and expired quantities. A negative
    available-to-promise means the warehouse is over-promised.
* **Reservations** (`inventory.stock_reservations`): open sales documents reserve at warehouse level (optionally a
  lot). Consumed by the document's issue posting, released on cancel, expired by a sweep (`expires_at`).
* **Allocation** (`inventory.allocation.allocate(item, qty_base, warehouse, rules)`): the policy's
  `allocation_strategy` (FEFO by `effective_expires_on` by default) over sellable lots, honouring the shelf-life
  minimums and the expired-sale policy (an `override` lot only when the caller passes an authorized override),
  splitting across lots; locks the chosen balance rows `FOR UPDATE` in the deterministic order of §4.1. Returns the
  lot/bin split the line contract records (07 §3).

---

## 7. Zoho stock while in `mirror` mode

* `items` adapter: the item detail's `locations[]` (`location_stock_on_hand`, `location_available_stock`,
  `location_actual_available_stock`) → `external_stock_levels` (batch NULL).
* `batches` adapter: `balance_quantity`, `in_quantity`, `location_id` / `associated_locations` → `external_stock_levels`
  per batch. Field names come from the vendored Inventory doc and probe P0.7.
* Stock moves do **not** bump an item's `last_modified_time` (platform architecture doc) — stock therefore runs on its
  own lane: an INDEX-style sweep every 30 min that fetches `/itemdetails?item_ids=` in bulk for inventory-tracked
  items (P0.3 sets the batch size), writing only snapshots (hash-guarded, no item row writes).

---

## 8. Deliberately deferred
Serial numbers · handling units (02 §7) · temperature logs · FIFO cost layers · period locks · putaway/pick task
lists · inter-organization transfers (stock-transfer invoices between GSTINs are a document-module concern). Each has
an extension point in the model and none blocks the phases above.
