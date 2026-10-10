# Price lists module — Zoho price lists, organization-scoped

**Status:** BUILT 2026-10-08 · **Package:** `app/modules/price_lists/` · **Schema:** `pricing` ·
**Migrations:** `20261008_1400_02b470ed2792` (created), `20261008_1600_7c3e91a05d24` (renamed "pricebooks" →
"price lists") · **Adapter:** [`adapters/price-lists.md`](../zoho-sync-implementation/adapters/price-lists.md)

## 1. Scope

In scope: Zoho Books price lists — the list, its per-item rates, its volume brackets — synced inbound,
organization-scoped (THPL by default through the Zoho connection), read through `/api/price-lists`, and a
quote calculator. **Out of scope (by request): the items module.** Items are referenced by Zoho
`item_id` text until it exists.

**Naming (owner decision 2026-10-08).** The platform says *price list*; Zoho's API says *pricebook*.

| Ours | Zoho's |
|---|---|
| module key `price_lists`, package `app/modules/price_lists/` | endpoint `/pricebooks`, `/pricebooks/{id}` |
| `pricing.price_lists` · `price_list_items` · `price_list_item_brackets` | `pricebook`, `pricebook_items[]`, `price_brackets[]` |
| `price_list_type`, `price_list_id`, `price_list_item_id` | `pricebook_type`, `pricebook_id`, `pricebook_item_id` |
| `rate`, `discount` | `pricebook_rate`, `pricebook_discount` |
| `PriceList`, `PriceListItem`, `PriceListItemBracket`; `/api/price-lists` | — |

Zoho's spelling appears only on the Zoho side of the field map, the hook's payload reads, and the test
wire that imitates Zoho.

## 2. Evidence

* Zoho docs (https://www.zoho.com/books/api/v3/pricelists/): create, list (`filter_by=SalesOrPurchaseType.*`,
  `search_text`), update, delete, mark active / inactive. **No "get one" endpoint is documented** and no
  modified-since filter.
* Live read-only probe of THPL (2026-10-08): 4 price lists covering every kind — per_item/unit (41 items),
  per_item/volume (10 items, 29 brackets), fixed_percentage purchases (active), fixed_percentage sales
  (inactive, `round_to_dollar`, 35.71 %). `GET /pricebooks/{id}` works. Full shapes in the adapter doc.

### Where the live API differs from the proposal / sample / docs

| Claim | Live | Design consequence |
|---|---|---|
| Detail envelope carries UI keys (`price_precision`, `item_rates` …) | Only `code`, `message`, `pricebook` — the sample came from Zoho's web UI | Nothing modelled from UI-only keys |
| Volume item has `sales_rate` / `rate` | Absent; only brackets | No item-level rate for volume items |
| Bracket `pricebook_item_id` = the parent item's id | Unique per bracket (29/29 distinct) | It is the BRACKET's `zoho_id` |
| Volume item has a `pricebook_item_id` | Absent | `price_list_items.zoho_id` nullable; items matched by `item_id` |
| Detail has `last_modified_time` | Absent (list only) | Fence stays the list's timestamp; new engine age gate |
| `rounding_type` = documented enum | Zoho's form offers 16 keys; docs misspell one | Stored as text, no CHECK; quotes refuse unverified keys |

## 3. Design decisions

1. **Three tables, not a JSON blob.** Items and brackets are queried by item and quantity (quotes) and will
   gain an FK to items; JSON would make both a scan.
2. **Children are projected, not crosswalked.** They have no endpoint of their own; their identity lives
   only inside the list's detail. The hook replaces the set: update in place (only changed columns), insert
   new, soft-delete leavers. A list row (no `pricebook_items` key) never touches them.
3. **Soft delete, never hard.** A price that was in force is evidence.
4. **Composite scope FKs** (`tenant_id, organization_id, parent_id`) make a child under another
   organization's list structurally impossible (tested).
5. **Engine change — `detail_max_age_minutes`** (generic, `GlobalSyncDefaults`, runtime knob). The gate
   skipped a detail whenever the listed timestamp had not moved; for price lists that is unsafe (undocumented
   whether item edits bump it). With a max age the gate also requires the stored detail to be younger than
   N minutes (`sync.sync_records.raw_synced_at`); an unchanged re-fetch only stamps `raw_synced_at`. 0 keeps
   the old behaviour for every other module.
6. **Runtime knobs added:** `detail_required`, `index_then_detail`, `detail_max_age_minutes` are now
   control-plane overridable (this also makes the chart-of-accounts doc's "enable detail as an override"
   true — it was not before).
7. **No local writes.** INBOUND only; the API is read-only until an outbox exists.
8. **THPL default.** No seed rows: a Zoho-mastered table seeded locally would be a second truth. Rows land in
   the organization the Zoho connection belongs to (THPL via `ZOHO_ORGANIZATION_ID` /
   `DEFAULT_ORGANIZATION_CODE`), and reads use the request's organization (`X-Organization-Code`, THPL by
   default). Zoho's own `is_default` flag is stored per list (all four THPL lists: false).
9. **The rename is a migration, not a rewrite of history.** `7c3e91a05d24` renames in place, so synced rows
   keep their ids and the crosswalk keeps its identity: tables, columns, every constraint / index / sequence
   named after them (read from the catalog — including PG18's named NOT NULL constraints — so a fresh database
   and a migrated one carry identical names), table/column comments, and every stored module key
   (`sync_records`, `sync_payloads`, `pending_references`, runs, events, cursors, stats, queue logs, state,
   retention, control-plane overrides) plus the soft-delete marker. `setting_audit_logs` keeps its history
   verbatim. Fully reversible (tested up → down → up on seeded old-name rows).

## 4. Quotes (`service.quote`, `GET /api/price-lists/{ref}/price`)

| List | Rate |
|---|---|
| per_item / unit | the item's `rate` |
| per_item / volume | bracket with the highest `start_quantity` ≤ qty; qty above its `end_quantity` (a gap like 19.5) keeps it, flagged `between_brackets` |
| fixed_percentage | `base_rate × (100 ± percentage) / 100`, then rounding |
| item not priced / below the first bracket | caller's `base_rate` (`basis=base_rate_fallback`), else 422 `pricing_unavailable` |

Rounding implemented: `no_rounding`, `round_to_dollar` (nearest, half up), `round_based_on_decimal`. Others →
422 `pricing_rounding_not_supported`. **Assumption to verify:** half-up at .5 — compare against a
Zoho-priced invoice before relying on it.

## 5. Files

`enums.py` · `model.py` · `zoho/{fields,hooks,spec}.py` · `crud.py` · `service.py` · `schema.py` · `api.py` ·
`errors.py`. Wiring: `alembic/env.py` (import + `pricing` owned schema), `app/router.py` (`/price-lists`), Zoho
registry `_ADAPTER_PACKAGES`, `tests/conftest.py` truncate list, `.importlinter` (platform never imports it;
no Zoho transport; independent master).

## 6. Tests

* `tests/test_price_lists.py` — quote arithmetic, rounding refusal, translator (Zoho `pricebook_*` keys →
  our columns, no Zoho name leaks), the age gate, the projection (set replace, in-place update, soft delete,
  list rows untouched), the scope FK, the API (`/api/price-lists`; the old route 404s) and organization isolation.
* `tests/zoho_core/test_masters_e2e.py` — real transport against live-shaped wire data: 1 list + 3 details,
  items/brackets, currency linked or deferred, second pass spends no detail calls, an item edit WITHOUT a
  timestamp bump is invisible until the age refresh, which then lands it and soft-deletes the dropped item.
* `tests/zoho_core/test_planner_tick.py` — its "every module due" cap raised 10 → 20 (price lists made ten
  scheduled modules, crowding out categories' weekly lane in the test only; production runs 2 at a time).

## 7. Open

* Items module: add `price_list_items.item_id` FK, linked through the crosswalk by `item_zoho_id`.
* Outbound (create / update / active / inactive) waits for the outbox.
* Engine: a 429 still rolls back the whole run (pre-existing; affects any detail-heavy module).

## 8. As built — live (THPL, dev, 2026-10-08)

* **First sync** (as "pricebooks"): 5 calls (1 list + 4 details), 5.6 s; 4 lists, 51 items (41 unit, 10
  volume), 29 brackets; every row in THPL; 0 errors.
* **Rename migration on dev:** identical before/after (same row ids; 4 crosswalk rows, 8 history rows, 4 runs,
  8 events, 2 cursors, 1 stats row moved to `price_lists`; 0 objects or keys left with the old name).
* **Sync after the rename:** 1 call, 0 created / 0 updated / 4 unchanged — identity carried over. A forced
  age refresh ran the full path (1 list + 4 details), confirmed all 4 documents and re-stamped them.
* **Population audit against LIVE Zoho** (fresh read-only fetch): **0 problems**. Every non-NULL cell equals
  Zoho's value; every NULL mirrors a blank/absent Zoho value — `currency_id` 2 (base-currency lists),
  `description` 4, `discount` 80 (all 51 items + 29 brackets send `""`), `end_quantity` 10 (each volume
  item's open top bracket), `percentage` 2 / `rate` 2 (per_item lists), `rate` 10 (volume items — their
  brackets carry it), `pricing_scheme` 2 (percentage lists), `zoho_id` 10 (volume items). Every Zoho key is
  stored or deliberately not (`currency_code`, `last_modified_time`, `products`, …). Platform columns: org
  THPL, `created_by_name=system:zoho-sync`, raw source `detail_fetch`, source timestamp = Zoho's.
* **API:** `/api/price-lists` lists all 4 (with currency + item counts), detail serves 10 items / 29
  brackets, a live quote returns the right bracket rate, `/api/pricebooks` → 404.
* **Full Zoho sync, all 11 modules:** 12 calls, every module succeeded, nothing changed.
* `soft_delete_missing` is configured, but dev has `ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING` off, so a list
  deleted in Zoho is not tombstoned there until that setting is enabled (logged as `soft_delete_missing_skipped`).
