# 07 — The document-line contract

Estimates, sales orders, invoices, delivery challans, sales returns, credit notes — and on the purchase side bills,
receipts, vendor credits — all reference items. They are **separate modules** (not built here), but they must all
reference items the same way, or GST returns, stock and scheme accounting drift apart. This document is the contract;
the catalogue ships the mixins and services that make it one line of inheritance per document module.

Rejected: one shared `sales.line_items` table with an exclusive-arc owner (the pasted design). Each document owns its
lines (different lifecycles, different Zoho sync modules, different retention); what they share is **shape and
rules**, delivered as a mixin.

---

## 1. `ItemLineMixin` (`app/modules/catalogue/mixins.py`)

Gives a line table these columns (all snapshot-on-write unless marked *live*):

| Column | Type | Meaning |
|---|---|---|
| `item_id` *live FK* | bigint | `catalogue.items` (composite same-org FK, helper `item_fk(table)`) |
| `item_unit_id` *live FK* | bigint NULL | the pack level the customer ordered (`(item_id, item_unit_id)` composite FK) |
| `quantity` | numeric(18,6) | in that level ("1 CTN") |
| `conversion_factor` | numeric(24,6) | `base_factor` at the time of writing |
| `quantity_base` | numeric(18,6) | `quantity × conversion_factor` ("960 PCS"); CHECK enforced |
| `unit_code`, `uqc_code` | varchar | level unit code and its GST UQC — what the printed invoice and GSTR-1 HSN summary show |
| `base_unit_code` | varchar | the item's base unit at the time ("960 **PCS**") |
| `expiry_warning`, `expiry_override_reason`, `negative_stock_warning` | boolean / text | set by the validator when the stock policy is `warn` / `override` (expired lot) or allows negative stock; printed on internal copies, never on the customer invoice |
| `item_name`, `item_sku`, `hsn_or_sac` | text | as printed |
| `rate` | numeric(18,6) | per **ordered level**, from `quote()` or typed (with permission) |
| `rate_source` | varchar | `price_list:<uuid>` / `channel` / `batch` / `pack_rate` / `item_default` / `manual` |
| `mrp` | numeric(18,6) NULL | MRP per ordered level at the time (batch MRP when allocated) |
| `discount_amount`, `discount_percent` | numeric | manual line discount (separate from scheme discount) |
| `scheme_discount_amount` | numeric | sum of scheme discounts applied to this line |
| `is_free_goods` | boolean | a scheme's free line (rate 0) |
| `scheme_id` | bigint NULL | the scheme that generated a free line |
| `taxable_value` | numeric | after all discounts |
| tax snapshot | — | via `taxes.assignment_service.freeze_owner` on the **line** (owner type `<doc>_line`, `allows_multiple=True`) — the platform's existing frozen-snapshot mechanism, not columns |

Helpers on the mixin: `item_fk(table)`, `item_unit_fk(table)`, `zoho_item_reference()` (ReferenceRule: module `items`,
DEFER) — the `HasCustomerMixin` pattern.

## 2. Line lifecycle per document type

| Document | Stock effect | Reservation | Batch | Schemes | Notes |
|---|---|---|---|---|---|
| Estimate | none | none | optional preference | previewed (`evaluate`), stored as applied snapshot | re-quoted when converted |
| Sales order | none | **reserve** at confirm (warehouse, FEFO lot optional) | optional | applied | released on cancel |
| Invoice (goods leave on invoice) | **post `sale` legs** at issue | consumed | **required** for batch items: allocations (§3) | applied, frozen | issue freezes taxes, schemes, rates |
| Delivery challan (goods leave before invoice) | posts at dispatch; invoice then posts nothing | consumed | required | — | whichever document moves goods posts; the other references it |
| Sales return | **post `sales_return` legs** into a returns location (`counts_as_available=false`) or available, per reason code | — | **the original lot** (from the invoice allocation) | reverses the original line's scheme share pro rata | `return_of_line_id` required |
| Credit note | posts only if it carries a return (goods back); a price-only credit note has no stock effect | — | from the return | cash discounts land here | references invoice lines |
| Bill / purchase receipt | post `receipt` legs | — | **creates** lots (number, dates, MRP) | vendor schemes later | `unit_cost` from the bill line |
| Vendor credit / purchase return | post `purchase_return` legs | — | the received lot | — | |

Rules every module enforces through the catalogue's validator (`catalogue.lines.validate_line(...)`):

1. Item `status` must allow the direction (`draft` never; `discontinued` → sales from stock only, no purchases).
2. Level must be `is_sellable` (sales) / `is_purchasable` (purchases) and current on the document date.
3. `quantity_base` respects the base unit's decimal places; `min_order_qty` / `order_multiple` of the level.
4. Batch-tracked items: allocations required at stock-moving time; sum of allocations = `quantity_base`; each lot
   active, not held, QC passed/not required, ≥ the policy's minimum remaining shelf life (`shelf_life_too_short`);
   an expired lot follows `expired_sale_policy` — `block` → 422 `batch_expired`, `override` → 403
   `expiry_override_required` unless the user holds `catalogue.batch:use` and gives a reason, `warn` → accepted with
   `expiry_warning`, `allow` → accepted. Expiry is always `effective_expires_on`.
4a. Insufficient stock follows `allow_negative_stock` / `allow_negative_batch_stock` (04 §4.2).
5. Rate vs MRP (Q-7).
6. Returns: `quantity_base` ≤ original − already returned (per lot).

## 3. Batch allocations (one child table per stock-moving document)

```sql
-- template; each document module creates its own, e.g. sales.invoice_line_batches
CREATE TABLE <schema>.<doc>_line_batches (
    line_id              bigint        NOT NULL,   -- composite FK to the line
    item_id              bigint        NOT NULL,
    batch_id             bigint        NOT NULL,   -- FK (item_id, batch_id) → catalogue.batches (item_id, id)
    storage_location_id  bigint        NOT NULL,
    quantity_base        numeric(18,6) NOT NULL CHECK (quantity_base > 0),
    batch_number         varchar(100)  NOT NULL,   -- snapshot (printed on the invoice)
    expires_on           date,                     -- snapshot
    mrp                  numeric(18,6),            -- snapshot
    -- standard OrgEntity block …
);
```

The ledger legs reference `(source_type='<doc>', source_id=document id, source_line_id=line id)`; a lot's full trail
(`/api/inventory/batches/{ref}/trace`) is a ledger query.

## 4. Scheme applications (per document module)

```sql
CREATE TABLE <schema>.<doc>_line_schemes (
    line_id          bigint NOT NULL,
    scheme_id        bigint NOT NULL,      -- pricing.schemes (same-org composite FK)
    scheme_slab_id   bigint NOT NULL,
    reward_kind      varchar(16) NOT NULL, -- percent | amount | fixed_price | free_goods
    amount           numeric(18,6) NOT NULL DEFAULT 0,
    free_line_id     bigint,               -- the generated free line
    scheme_code      varchar(40) NOT NULL, -- snapshot
    -- standard block …
);
```

`pricing` counts usage from these tables through a registered counter (`schemes.registry.register_usage_source(
"invoice_line_schemes", ...)`) — `pricing` never imports a document module (`.importlinter` contract
`pricing-never-imports-documents`).

## 5. Zoho line mapping (when documents sync)

| Ours | Zoho line |
|---|---|
| `item_id` | `item_id` (crosswalk) |
| `quantity` + level | Zoho knows only ONE unit per item — the level `items.zoho_item_unit_id` names (base when NULL). Send the quantity converted into that level (`quantity_base / zoho_level.base_factor`) and the rate converted to match, rounded **up** to Zoho's precision (so the residue is never negative), with "2 CTN (= 1920 PCS)" in the line `description`. The rounding residue is carried as a line discount so the line total matches exactly. If the quantity is fractional in Zoho's unit and that unit allows no decimals (3 PCS of a BOX-kept item), the document is refused at issue time with 422 `zoho_unit_fraction`, before anything is pushed |
| allocations | Zoho Inventory line `batches[]` (shape from the vendored doc when the invoice adapter is built) |
| scheme free line | separate line, rate 0 |
| scheme discount | line `discount` |

The rounding rule is the one place where Zoho's single-unit model leaks; it is a function in `catalogue.lines`
(`to_zoho_line`) with property tests (`Σ zoho line totals == Σ our line totals` for random factors/rates).
