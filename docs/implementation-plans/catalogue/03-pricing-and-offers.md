# 03 — Pack-level pricing & offers (schemes)

Three separable concerns, all keyed by the same `(item, pack level)`:

* the **hierarchy** says what a carton *is* (02);
* **pricing** says what it *costs* (this doc §1–§3);
* **schemes** say what is *given away or discounted* on top (§4–§6).

---

## 1. Where prices live

| Source | Table | Per | Owner |
|---|---|---|---|
| Item default rates | `catalogue.items.sales_rate / purchase_rate / mrp` | base unit | Zoho (item `rate`, `purchase_rate`, `label_rate`) or local |
| Explicit pack rates | `catalogue.item_units.sales_rate / purchase_rate / mrp` | one pack of that level | local |
| Price lists | `pricing.price_list_items` (+ `_brackets` for volume) | base unit (Zoho) **or a pack level** (`item_unit_id`, local lists) | Zoho or local |
| Channel listing override | `catalogue.item_sales_channels.price_override` | `price_item_unit_id` (NULL = base) | local |
| Batch rates | `catalogue.batches.sales_rate / mrp` | base unit | Zoho (batch `sales_rate`, `label_rate`) or local |

`pricing.price_list_items` changes (SQL §6.1): `item_id` FK (resolved from `item_zoho_id` through the items
crosswalk), `item_unit_id`, `item_zoho_id` nullable (local lists), and (rev 2) **`valid_from` / `valid_to`**: one rate per
`(price_list, item, level)` on any given day, windows half-open and never overlapping (trigger
`guard_price_list_item_window`; `btree_gist` is not installed, so no EXCLUDE). A carton re-price closes the old window
and opens a new one, so historic quotes stay explainable. Zoho-fed rows carry no window (Zoho has none). Volume brackets
hang under a price-list item and therefore count quantity **in that item's level** ("5–9 CTN at ₹970").

Customer-specific contract prices are **not** a new table: a contract is a price list assigned to the party
(`party.parties.price_list_id`, already synced from Zoho `pricebook_id`).

---

## 2. The quote order

`catalogue.pricing.quote(item, level, qty, context)` where `context = {party, price_list?, sales_channel?, date,
batch?, direction: sales|purchase}` returns `{unit_rate (per level), source, mrp, explain[]}`. First match wins:

1. **Party price list** (`context.price_list` or the party's), entry for the **exact level** whose window contains the
   document date; volume lists pick the
   bracket containing `qty` (in that level's quantity).
2. Same list, entry for the **base level** × `base_factor` — only if the level has `derive_price = true`.
3. **Channel listing** `price_override` for the level (or base × factor under the same rule).
4. **Batch** `sales_rate` when a batch is named (× factor).
5. **Explicit pack rate** `item_units.sales_rate`.
6. **Item default** `items.sales_rate × base_factor` — only if `derive_price = true`.
7. Nothing → 422 `no_price_for_unit` (never silently prorated).

Purchases use the same ladder with purchase rates and purchase-side price lists. `fixed_percentage` price lists apply
their markup/markdown and rounding to the result of steps 3–6 (the existing price-lists quote rules; unimplemented
rounding modes stay 422 as today).

**MRP guard** (Q-7): for an item with an MRP, a sales rate above `mrp × base_factor` (batch MRP when a batch is
allocated, else item/level MRP) is refused: 422 `rate_above_mrp`. MRP is tax-inclusive (`mrp_includes_tax`), so the
check compares the tax-inclusive line rate.

Every step appends to `explain[]` (`{step, source_id, rate, reason}`) — same contract as the resolution engine's trace,
so a support person can answer "why 869?" without reading code. If the generic resolution engine
(`app/modules/resolution/`) fits a numeric facet without contortion, `quote` is implemented as a `PriceFacet`;
otherwise it stays a plain service with the same trace shape. Decide in P5 by spiking the facet; do not bend the
engine.

---

## 3. Batch-aware pricing

Pharma/FMCG lots carry their own printed MRP, and Zoho supports a per-batch `sales_rate`. The line contract (07)
quotes **after** batch allocation when the item is batch-tracked and a batch rate exists, so the invoice rate matches
the pack in hand. Quotes before allocation (estimates) use the item/list price and are re-validated at invoicing.

---

### 3.1 Expired and short-dated stock in quotes (rev 2)
When the allocated lot is expired or below the minimum remaining shelf life, the quote does not change the price;
the **stock policy** decides whether the line may exist at all (04 §1.3). A near-expiry clearance price is a
`fixed_price` scheme targeting the batch (§4), never a silent price rule.

## 4. Schemes — the model

```
pricing.schemes            what kind of offer, when, how it combines (priority, stackable), limits, status
  ├─ scheme_targets        WHAT it applies to: all_items | item | item_unit | product | item_group | brand |
  │                        manufacturer | category | batch   (+ is_excluded carve-outs, threshold_unit_id)
  ├─ scheme_slabs          the ladder: quantity or value bands → ONE reward (percent | amount | fixed price | free goods)
  └─ scheme_eligibility    WHO: party | party_category | price_list | sales_channel | gst_treatment | place_of_supply | hub
                           (no rows = everyone; is_excluded carve-outs)
```

Worked examples:

| Offer | schemes | targets | slabs | eligibility |
|---|---|---|---|---|
| "Buy 10 cartons get 1 free, Sept, Godhra hub" | `free_goods`, 2026-09-01..30 | `item_unit` = Para CTN | `min_quantity 10, free_quantity 1, is_repeating` | `hub` = Godhra |
| "5 % off Dabur oral care over ₹5,000" | `percent_discount` | `brand` Dabur + `item_group` ORAL_CARE … (all must match — see §5.1) | `min_value 5000, discount_percent 5` | — |
| "₹20 off per box of hair oil" | `flat_discount` | `product` Almond Hair Oil, `threshold_unit_id` = box | `min_quantity 1, discount_amount 20, is_repeating` | — |
| "Near-expiry clearance on lot B-2026-01 at ₹15" | `fixed_price` | `batch` = B-2026-01 | `min_quantity 1, fixed_price 15` | `sales_channel` GENERAL_TRADE |
| "Buy 2 shampoo get 1 conditioner" | `free_goods` | `item` shampoo | `min_quantity 2, free_item_id conditioner, free_quantity 1` | — |

Status lifecycle: `draft → active ↔ paused → expired | archived`. Only `draft` schemes are freely editable; an
`active` scheme's targets/slabs change only by pausing it (an applied scheme must stay explainable). `expired` is set
by a daily task when `valid_to` passes. **No approval step** (owner decision, rev 2): anyone holding
`pricing.scheme:update` activates a scheme; activation validates targets, slabs and eligibility and is recorded in
activity.

Usage counters are **not stored on the scheme** (AP2): `max_applications`, `max_per_party` and `budget_amount` are
checked by counting the document modules' recorded applications (07 §4) under an advisory lock per scheme.

---

## 5. The evaluation algorithm

`schemes.engine.evaluate(document_draft) -> Evaluation` — pure function over preloaded data (one query per table for
all lines: targets matching any line's item/level/product/group/brand/manufacturer/categories/batch; slabs; eligibility;
usage counts). Deterministic: same input → same output, so previews and the final invoice agree.

1. **Candidate schemes**: `status='active'`, date in window, organization matches, eligibility passes for the party
   (no eligibility rows = everyone; any matching exclusion removes it).
2. **Line matching**: a scheme matches a line when some non-excluded target covers it and no excluded target does.
   * `item_unit` targets match only lines **in that level** (10+1 on CTN does not fire for loose BTL).
   * Wider targets match any level; quantities are counted in `threshold_unit_id` (lines without that level are not
     counted) or in base units.
3. **Aggregation**: `applies_on='line'` evaluates each line alone; `'document'` aggregates all matching lines (mixed
   SKUs of one brand toward one value band).
4. **Slab selection**: the highest slab whose `min_*` ≤ measure ≤ `max_*`. `is_repeating` multiplies the reward by
   `floor(measure / min_quantity)`.
5. **Conflict resolution** per line: sort candidates by `priority` (lower first), then by reward value (best for
   the customer), then by code (determinism). Take the first non-stackable; add all stackable ones whose `priority` is
   ≥ it. A stackable scheme never stacks on a `fixed_price`.
6. **Rewards**:
   * percent / amount → a **line discount** (never folded into `unit_rate` — the discount must be auditable and
     reversible on a credit note);
   * fixed price → the line's rate becomes the fixed price, with the difference recorded as the scheme discount;
   * free goods → a **separate free line** (`is_free_goods=true`, rate 0, `scheme_id`, quantity and level from the
     slab) so the retailer's invoice visibly shows "1 CTN free". Free lines are allocated stock like any other line.
7. **Limits**: drop a scheme whose usage/budget is exhausted (reported, not silently).
8. Output: per line `{applied: [{scheme_id, slab_id, kind, amount, free_line_ref}], skipped: [{scheme_id, reason}]}`.

### 5.1 Multiple targets
Targets of one scheme are OR-ed (any listed thing). An AND of dimensions ("Dabur AND oral care") is expressed by the
narrower target (the item group, or a product list) — a deliberate simplification; a rule-expression language is not
built.

### 5.2 Tax interplay (verify with counsel)
* Discounts on the invoice reduce the taxable value (pre-tax, shown on the invoice — CGST Act s.15(3)(a)).
* Free goods under a "buy N get M" scheme are generally treated as part of one supply for the total consideration
  (CBIC circular 92/11/2019-GST); the free line carries rate 0 and the same HSN/GST rate, taxable value 0. Confirm the
  treatment with the tax advisor before go-live, including ITC reversal questions on the purchase side.
* Cash discount (`cash_discount`) offered after the invoice is a **credit note** concern, not an invoice line
  reduction; the engine reports it, the credit-note module issues it.

### 5.3 Orphans
`scheme_targets.target_id` / `scheme_eligibility.ref_id` are polymorphic by `*_type`. The service validates the target
exists in the organization on write; `schemes.find_orphan_targets()` (same pattern as `comments.find_orphan_comments`)
reports targets whose entity was deleted.

---

## 6. Zoho and schemes

Zoho has no scheme object. When documents are pushed (P7/P8), an applied scheme is expressed in Zoho's own vocabulary:
discounts as the line `discount` (amount or %), fixed price as the line `rate`, free goods as a separate line with
`rate 0` and a description `"<scheme code> — free"`. Schemes themselves never leave Postgres.
