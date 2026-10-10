# 02 — Units of measure & the packaging hierarchy

Industry names for the same thing: *alternative units of measure* (SAP), *UoM conversions* (Oracle/NetSuite),
*case-pack hierarchy*, *packaging hierarchy* (GS1). Here: **`catalogue.item_units`**.

---

## 1. Three layers, three tables

| Layer | Table | Example | Scope |
|---|---|---|---|
| Statutory vocabulary | `catalogue.uqc_codes` | `BTL`, `PCS`, `MLT`, `KGS` | GLOBAL (GSTN list) |
| Unit vocabulary | `catalogue.units` | `pcs`, `btl`, `box`, `ctn`, `g`, `kg`, `ml`, `l`, `cm`, `in` | Organization (Zoho units live here) |
| Per-item structure | `catalogue.item_units` | Paracetamol: CTN = 8 BOX = 96 BTL = 960 PCS | Item |

`units` carries **no conversion between count units** — a "box" has no universal size. It does carry `si_factor`
for **physical** units (mass base g, volume base ml, length base mm), so `500 g` and `0.5 kg` compare, and Zoho's
`weight_unit` strings resolve by code. Zoho lists `l` among *weight* units; it resolves to the volume unit `l` — the
class is ours, the code is Zoho's.

`uqc_code` on a unit is what an invoice line snapshots for GSTR-1's HSN summary and the e-invoice `Unit` field. A unit
without one files as `OTH`.

---

## 2. The hierarchy

```
level   unit  contains            base_factor   flags (example)
CTN     ctn   8  × BOX            960           purchasable, sellable (B2B), GTIN 1890…15, shipper case
BOX     box   12 × BTL            120           sellable, inner box
BTL     btl   10 × PCS            10            sellable, default sales level, GTIN 890…18
PCS     pcs   — (base)            1             stocking unit; not sellable loose (allow_break=false on BTL)
```

* **Chained**: each level names the level it contains (`contents_item_unit_id`, `contents_qty`). Physical structure is
  preserved — needed to open a carton into boxes, to plan picks, and to suggest "1 CTN + 3 BTL + 5 PCS".
* **Cached**: `base_factor = contents_qty × contents.base_factor`, computed by the trigger at insert. Conversions are
  one multiplication; no recursive walk at request time.
* **Immutable structure**: `unit_id`, `contents_*`, `is_base`, `item_id` never change. When a vendor moves from 8 to 10
  boxes per carton, the service **retires** the old CTN level (`valid_to`) and creates a new one. Consequences:
  * the chain is acyclic by construction (a level can only point at a level that already existed);
  * every historic document line still resolves to the factor it was sold at (and snapshots it anyway);
  * a contained level cannot be retired while a current level still contains it (trigger).
* **Exactly one base** per item, equal to `items.base_unit_id` (trigger + partial unique index). An item whose Zoho
  record has no unit has no base level and transacts with factor 1 until someone sets the unit (reported by the data-
  quality endpoint).
* **Branches are allowed** — two levels may contain the same level (a 6-pack and a 12-pack both contain BTL). A line
  names a level, never a path.

Flat ("matrix") models — one factor per level straight to base — were rejected: they cannot express "a carton
physically holds boxes", which pack-breaking and pick suggestions need.

### 2.1 Level flags

| Column | Meaning |
|---|---|
| `is_sellable` / `is_purchasable` | Which documents may use the level. A sales line on a non-sellable level → 422 `unit_not_sellable` |
| `is_default_sales` / `is_default_purchase` | Pre-selected level on a new line (one each per item) |
| `allow_break` | May a sealed pack of this level be opened to sell its contents loose (regulated SKUs sold sealed: false). Selling 3 BTL when the only stock is in sealed CTN with `allow_break=false` → 422 `pack_cannot_be_broken` (checked against handling units once they exist; today a policy flag the line validator reports) |
| `min_order_qty`, `order_multiple` | Per-level order rules ("boxes in multiples of 2") |
| `sales_rate` / `purchase_rate` / `mrp` | Explicit price of one pack (see 03 §2) |
| `derive_price` | **Default false** (rev 2, the guide's rule: an alternate unit is not sellable without a deliberate price). A non-base level then needs a price-list entry or an explicit `sales_rate`; set true to allow `items.sales_rate × base_factor` as the fallback for that level |
| `packaging_type_id`, dimensions, `gross_weight` | Physical facts for load planning (the item's own columns describe ONE base unit) |

---

## 3. Conversions (one implementation, two faces)

* Python: `app/modules/catalogue/units.py` — pure functions over a preloaded hierarchy (no SQL), used by services and
  the line contract:
  * `to_base(qty, level) -> Decimal` — `qty × base_factor`, rounded to the base unit's `decimal_places` with
    `ROUND_HALF_EVEN`; refuses (422 `fractional_base_quantity`) a result with more decimals than the base unit allows
    (0.5 BTL of a 10-PCS bottle is fine; 0.33 is not when PCS has 0 decimals).
  * `convert(qty, from_level, to_level)`.
  * `breakdown(qty_base, levels) -> [(level, count)]` — greedy coarsest-first, current sellable levels only, for
    "1 CTN + 3 BTL + 5 PCS" displays and pick suggestions. Documented as a *logical* breakdown (§7).
* SQL: `catalogue.convert_quantity(qty, from_item_unit, to_item_unit)` for reports.

Quantities: `numeric(18,6)`; factors `numeric(24,6)`. Never floats (Zoho JSON numbers are parsed with
`Decimal(str(x))`, rejecting NaN/Infinity — the mapper's existing guard).

---

## 4. Barcodes per level (GS1)

`catalogue.item_identifiers(item_id, item_unit_id, kind, value)`. Each packaging level may carry its own GTIN; scanning
a carton at goods receipt resolves `(item, CTN)` from one index probe (`uq_item_identifiers_scannable`), so the receiver
never picks a unit by hand. `GET /api/catalogue/lookup?code=…` exposes it.

Zoho has one `upc`/`ean`/`isbn`/`part_number` per item — they land on the **base** level (`item_unit_id NULL`) with
`source='zoho'`; level GTINs are local data.

---

## 5. Rules the services enforce

| Rule | Error |
|---|---|
| Base unit can change only while the item has no stock, no ledger rows and no document lines | 409 `base_unit_locked` |
| A non-base level's unit must be class `count` (a carton is not "500 g") | 422 `pack_unit_must_count` |
| Physical units on weight/dimension columns must be class mass / length | 422 `unit_class_mismatch` |
| `track_mode` cannot leave `batch` while batches with stock exist | 409 `tracking_locked` |
| A level used by an open document, price list item, scheme target or vendor row cannot be retired without `force` + replacement | 409 `item_unit_in_use` |
| Zoho-owned item fields read-only on a linked item (until push) | 409 `zoho_owned_field` |

---

## 6. Re-denominating is not a stock movement

Because stock is held in base units only (D-5), "opening a carton into 8 boxes" changes nothing in the ledger: 960
pieces were there before and after. There is deliberately **no `repack` movement**. What *does* change the item —
assembling a kit, de-kitting, relabelling — is `assembly` / `disassembly` (04 §5).

---

## 7. When scalar stock is not enough: handling units

Base-unit balances answer "how much"; they cannot answer "is the carton on A-02 sealed or half-empty?". That needs
**handling units** (license plates, SSCC): a row per physical pack instance with its own level, parent pack, location,
remaining base quantity and seal state. Deferred until there is real pain (partial-pack pick accuracy, scanning the
carton's own label at putaway). The model is ready for it: a handling unit references `(item_id, item_unit_id)` and
`batch_id` with the same composite FKs, and the ledger gains a nullable `handling_unit_id`.

---

## 8. Zoho's single unit (rev 2)

Zoho has exactly one unit per item; this hierarchy has many. `items.zoho_item_unit_id` names the level Zoho's unit
stands for (NULL = base). Usually THPL keeps Zoho in the base unit and nothing converts. When Zoho is kept in a pack
(the item is "1 BOX" in Zoho but stocked in PCS here), the adapter divides Zoho's `rate` by that level's
`base_factor` on pull, and documents pushed to Zoho express quantity and rate in that level (07 §5). The FK is
composite — the level must belong to the same item.

## 9. Migrating a flat "units per case"

Zoho has no packaging hierarchy (P0 probe P0.9 checks for unit conversions). Your item example's
`metadata_.case_size = 48` and similar flat values become a **two-level** hierarchy (`CTN contains 48 PCS`) by a
one-off, reviewable import (`python -m app.modules.catalogue.tools.import_case_sizes --dry-run`). For deeper items the
flat number is only a **checksum**: the real chain (8 × 12 × 10) must come from the product master or vendor packing
list, and the import refuses to invent intermediate levels.
