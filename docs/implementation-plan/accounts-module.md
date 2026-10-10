# Accounts module: Chart of Accounts, account assignments, and the path to a ledger

**Status:** Phase 1 **BUILT** (2026-10-08, migration `e4c737170f12`) — see *As built* below; Phases 2–6 proposed · **Owner:** backend / platform data
**Schema:** `accounting` · **Package:** `app/modules/accounting/` · **Postgres:** 18
**Inputs reconciled:** the v1 `accounts_module.sql`, the v2 audit (`accounts_module_v2.sql`,
`accounts_module_validation.sql` and their report), Zoho Books `/chartofaccounts`
(vendored: `docs/zoho-docs-md/chart-of-accounts.md`), and the codebase as it stands today.
**Related:** [`sync-crosswalk-redesign.md`](sync-crosswalk-redesign.md) ·
[`sync-crosswalk-delta-v3.md`](sync-crosswalk-delta-v3.md) ·
[`tax-assignments.md`](tax-assignments.md) (the pattern this module copies) ·
`docs/tenancy/README.md` · `docs/architecture-prompts/master-prompt.md`

---

## As built — Phase 1 (2026-10-08)

Everything in §5–§8 and §11–§12 for Phase 1 is in the code, with these deliberate differences
from the text below (the text is kept as the design record):

| Plan said | Built | Why |
|---|---|---|
| owners addressed by UUID in the API | owners addressed by `(owner_type, owner_id)` — the `/api/taxes/assignments` convention | one convention for both assignment APIs; accounts themselves are addressed by id **or** uuid |
| `Account` with tags / documents / custom fields | `HasCommentsMixin` only (`account` registered commentable); Zoho custom fields stay on the crosswalk | no consumer yet; each is one mixin + one registration later |
| `tax.assert_owner_scope` reused | promoted to **`core.assert_owner_scope`** (an organization owns itself); `tax.*` delegates to it; `entities.crud.owner_info` likewise shared | one owner-scope rule for every polymorphic-assignment module |
| type and group rules on every assignment | judged for **local** rows (service + deferred trigger); a **source's** rows are trusted and misfits logged (`accounting.assignment.source_misfit`) | Zoho masters its own tax ↔ account links; refusing them would also fail the reconcile lane's whole batch |
| policies configurable "per tenant / organization" (§7.5) | `core.resolution_policies` (+ `/api/resolution/policies/{facet}/{subject}?scope=organization\|tenant`); effective = organization → tenant → code. A tenant-wide row is inserted with Core: the ORM insert hook would stamp the request's organization onto it | accountant-approved defaults stay in code; overrides are validated against the registry before they are stored |
| `ModuleSyncConfig.strategy` default → FULL | done; `tests/test_accounting.py` asserts every adapter declares its strategy | the default never decides a real module |

| `index_then_detail` + inline detail (§6.1) | **list-only by default** (`detail_required=False`); detail is a control-plane override | documented limits: 100 requests/min per organization and 1 000–10 000 requests/DAY by plan (`docs/zoho-docs-md/introduction.md`) — one detail call per account would spend 231 calls per full scan on THPL. And the LIVE list row already carries `currency_id`, `description`, `placeholder`, `show_on_dashboard` (the documented list example does not) |
| `tds_payable_account_id` → purpose `tds_payable` | for a **GST leg** (cgst/sgst/igst/utgst/cess) with no `purchase_tax_account_id`, it is read as **`input_tax`** (`taxes/zoho/hooks.tax_account_refs`) | observed on all THPL GST taxes: Zoho leaves `purchase_tax_account_id` empty and puts "Input CGST/IGST/SGST" in `tds_payable_account_id`. Not documented by Zoho; one tenant's data — a real TDS tax keeps the literal mapping |
| — | **engine fix** (`zoho/sync/engine.py`): a single-record apply (the detail phase, retries) now writes its DEFER waiters | they were dropped by the next page's reset, leaving a detail-only reference NULL forever and invisible to reconcile. Mutation-checked |
| — | `accounting/model.py` imports the currency and registry models | any process importing only accounts (a seeder, a task) failed with `NoReferencedTableError` |

**Live (dev stack, real Zoho, 2026-10-08).**
- Migration `e4c737170f12` applied.
- First list-only sync: **2 calls, 231 accounts, 0 errors**. All 231 have a currency, 74 children are linked (max depth 1), no account sits under a parent of another group or of a type that disallows sub-accounts, and no account code is duplicated (decision 3 settled).
- 16 account types are used. The most common is `other_expense` (61 accounts), one of the 5 types missing from the owner's 41-code list.
- Tax backfill: all 10 stored tax documents were replayed, giving 12 tax → account links (Output/Input per GST leg).
- Seed step `accounting.defaults` assigned `receivable` and `payable`. `inventory_asset` was left unassigned on purpose: there are 3 stock accounts, so it is ambiguous.
- Resolver through the API: CGST20 posts output to Output CGST and input to Input CGST; with no contact, receivable resolves to the organization's Accounts Receivable.

**Synced vs live Zoho — field-by-field audit (2026-10-08, migration `487a10ab6c4e`).**
- **Match:** 231 = 231 accounts (none missing on either side), with **zero mismatches** across name, code, type,
  status, system / user-created flags, expense-claim flag, dashboard flag, placeholder, description, parent,
  currency and depth. All 231 crosswalk rows are linked, dated and in THPL's organization; nothing is pending.
- **Second scan:** 231 unchanged, 0 writes, no new history, 2 calls.
- **Not synced before, synced now:** `is_register_supported_account` (228 true) and `is_standalone_account`
  (35 true) are in every live list row. They now land in `accounts.is_register_supported` / `is_standalone`,
  filled from the stored documents (zero API calls).
- **Zoho-fed assignments keep their Zoho account id:** `external_ref` is now filled on every Zoho-fed row,
  not only while pending.
- **Zoho's `isdebit` is NOT the normal side.** It is the side of the *current balance*:
  - every zero-balance account reports `false` whatever its type;
  - "Discount" (income) reports `true`, because it carries a debit balance;
  - "IDBI Bank" reports `false`, because it is in credit (likely a cash-credit / overdraft account).
  - The v2 design's mapping `isdebit` → `normal_balance_is_debit` would have been wrong for 9 of 20 sampled
    accounts. Ours stays derived from the type; `isdebit` is in the no-op-hash volatile keys.
  - "Discount" and "Purchase Discounts" behave as contra accounts: `is_contra` is ours to set (PATCH); not
    changed automatically.
- **The detail document has no `currency_id`** (contradicting the docs example). It adds `custom_fields`
  (empty on every sampled account), `isdebit`, the balance and an embedded `transactions` list — so
  list-only stays the default.
- **`placeholder` is Zoho's slug of the account NAME** (`gl_laptop`, `gl_racks` …), not a system-role
  marker as §5.2 assumed. The comment is corrected; nothing keys on it.
- **Personal data in the chart:** several THPL account names carry employees' names (salary ledgers). That
  is P2 data in `account_name` (and in Zoho itself) — a DPDP note for the owner, not changed here.
- **Why no `zoho_id` on purposes, policies or assignments:** purposes and policies are our own vocabulary,
  with no Zoho counterpart, so the column would be permanently NULL (the categories review's "fourteen
  NULL columns" mistake). An assignment is a link with no Zoho id of its own; the Zoho id it carries is
  the ACCOUNT's, stored as `external_ref` (source-neutral, the `tax_assignments` convention).
- **Known, not changed:** Zoho deletions do not propagate. `soft_delete_missing` is off: with it on, a full
  scan tombstoning a parent and its children in one statement would trip the delete guard and fail the run.
  To revisit with the tombstone path.

**Observed, not documented — one occurrence each.** With detail ON, the first full sync got HTTP 429 with an undocumented `code: 43` ("blocked for some time … requests per minute"):
- It came after ~190 detail calls in ~3.5 minutes, although this process stayed at ≤ 58 calls/minute by its own log.
- The block took ~15–20 minutes to lift.
- Scheduled lanes retrying during the block appear to have prolonged it.
- Zoho documents a per-ACCOUNT variant (code 44) that counts the connected user's web and other-app traffic; that may explain it, but this is unverified.
- The engine rolls a run back on a 429, so a detail-on first sync of a large chart may never converge — another reason detail stays off.
- `backend/.env` sets `ZOHO_RATE_LIMIT=150`/min, above the documented 100: worth lowering (owner's call).

**Verified:** migration up → down → up on a scratch PG18; autogenerate drift on the owned tables
= 0; `lint-imports` 10/10 contracts kept (two new: accounting never imports a consumer; the
resolution engine imports no feature); `tests/test_accounting.py` + `tests/test_resolution.py`
(31) and the extended `tests/zoho_core/test_masters_e2e.py` green.

## 0. Summary

> **Revision 2 (2026-10-08)**, after review with the owner. Changes:
> - **All 46 account types are seeded.** That is Zoho's documented list plus the tenant's
>   own account-types response, each with its Zoho numeric id as `zoho_id` (§5.1, §2.4).
> - **`zoho_id` echoes** are on `accounts` and `account_types`.
> - **A platform resolution engine** (`app/modules/resolution/`) answers "what applies
>   here?" for taxes, accounts and later facets, for any owner chain (a document line →
>   item → category → contact → organization). It runs in one query per facet (§7).
> - **Contacts carry taxes and accounts**, resolved through the same engine (§8.2).
> - **Zoho tax ids resolve to `app/modules/taxes`**, and tax components' account ids
>   resolve to `accounting` (§8.3).
> - **Sync default is FULL.** `last_modified_time` is trusted, so INCREMENTAL is a runtime
>   override, not a deploy (§6.1).
> - **Tenant and organization default: THPL** (`backend/.env`), with no new setting (§6.4).

1. **Nothing the platform has is rebuilt.** v2's tenancy, audit / soft-delete / row-version
   columns, type registry, currencies and exchange rates, Zoho identity edge and audit log
   all map onto what exists (§2.2): `OrgEntityMixin`, `AuditMixin`,
   `SoftDeleteFilteredMixin`, `RowVersionMixin`, `core.entity_types`, `currency.currencies`
   / `currency.exchange_rates`, `sync.sync_records`, and the activity recorder. What
   remains is the accounting itself.
2. **Phase 1** is:
   - the **Chart of Accounts** (`accounting.account_types` and `accounting.accounts`);
   - **account assignments**, so any entity can say "use this account for this purpose"
     (`accounting.account_assignments` + `HasAccountsMixin`);
   - the **resolution engine**;
   - the **Zoho sync** of `/chartofaccounts`.

   The general ledger comes in Phases 2–3, when invoices and bills exist to write to it.
3. **"Customers and Items can have accounts" means assignments, never more accounts.**
   - An item's sales, purchase and inventory accounts (Zoho `account_id`,
     `purchase_account_id`, `inventory_account_id`) are three assignment rows.
   - A contact's receivable account is an optional override of the organization's AR
     control account.
   - There is never one GL account per retailer. Control accounts plus subledgers are the
     standard design (§2.4); the counterparty belongs on the ledger line.
4. **Organization defaults are assignments whose owner is the organization.** This one
   mechanism replaces v2's `account_roles`, its role assignments, the inventory-preference
   account columns and the `is_retained_earnings`-style singleton flags.
5. **Organization-scoped** (`OrgEntityMixin`). Zoho account ids belong to a Zoho
   organization, and so do our rows.
6. **Corrections to v2 that change the design** (§2.3):
   - The type vocabulary must be the union of three sources. Your 41-code list is also
     missing 5 types the tenant itself reports (§2.4).
   - The fiscal-period overlap trigger races. `btree_gist` is already installed, so we use
     `EXCLUDE`.
   - The immutability guard contradicts the erasure rule.
   - `balance_cache` on the master row rewrites it on every balance change.
   - Base currency and fiscal-year month already live on `organizations`.

## 1. Understanding

**Asked:**
- Chart of Accounts and the income, purchase and inventory account pickers, as an
  organization-scoped module.
- Contacts (customers and vendors) and Items carry accounts *and* taxes, resolved properly
  by an enterprise-grade resolver shared across modules.
- Zoho tax ids resolve into `app/modules/taxes`.
- `zoho_id` wherever a row has a Zoho identity.
- FULL as the default strategy.
- THPL as the default tenant and organization.

**Read for this plan:**

- `app/database/mixins.py`, plus the `tags`, `comments`, `documents`, `custom_fields` and
  `taxes` mixins.
- `taxes/assignment.py`, `assignment_service.py` (`resolve_taxes`, `select_applicable`),
  `registration.py`, `preference.py` (org default taxes), `org_tax.py` (per-organization
  grants), `component.py` (the opaque `*_account_id` echoes) and `zoho/spec.py`.
- `zoho/sync/mixins.py` (deprecated for new modules), `zoho/sync/config.py` (the
  `ModuleSyncConfig` defaults) and `zoho/control/config.py` (runtime per-module overrides).
- `sync/contract.py`, `crosswalk.py`, `references.py`, `reconcile.py`.
- The categories adapter (its same-module parent hook).
- `currencies/model.py` (org-scoped, `uq_currencies_tenant_id`, with `zoho_id` /
  `currency_id` echoes) and `currencies/zoho/spec.py`.
- `entities/model.py` (`core.entity_types`) and `organizations/model.py` (`currency_id`,
  `fiscal_year_start_month`).
- `tests/test_tenancy.py`, `alembic/env.py`, `rbac/catalogue.py`, `backend/.env`.
- The vendored Zoho docs `chart-of-accounts.md`, `contact.md`, `items.md`, `taxes.md`,
  `journals.md`.

**Samples.** The tenant's account-types response (26 types, with Zoho's numeric ids) was
provided in review and is vendored as `docs/zoho-docs-md/samples/accounts/account-types.json`
in Phase 1. The other samples (chart list, single account, the
income/purchase/inventory lists) are still outstanding (§13, decision 1). Only the picker
eligibility flags (§7.11) depend on them.

## 2. The v2 design against the platform

### 2.1 What we keep from v2, unchanged in meaning

| v2 rule | Where it lands |
|---|---|
| Normal balance derived from the type, inverted for contra accounts (v1's `DEFAULT true` was wrong for every liability, equity and income account) | `accounting.derive_account_fields()` trigger (§5.3) |
| Depth derived from the parent, cascaded on re-parent; cycle prevention | the same trigger + `accounting.cascade_account_depth()` |
| Blank-string trap: Zoho sends `"account_code": ""` | codec maps `""` → NULL, plus a CHECK `btrim(account_code) <> ''` |
| One lifecycle signal instead of three (`is_active` / `status` / `deleted_at`) | `status` is the only activity signal (§5.2) |
| Journal header + deferred balance check, `native` vs `external_projection`, immutability once posted (void or reverse), period and lock-date checks, numbering | Phase 3, reconciled (§9) |
| `counterparty_type` + `counterparty_id`, no FK to `users` (B-1) | Phase 3 lines, typed by `core.entity_types` |
| Typed reporting dimensions instead of EAV | Phase 3 |
| One AR control account + counterparty on lines | §7, §8 |
| Bank P3 data in its own 1:1 table | **never put on `accounts` at all** (§10). v2 deferred the split as BREAKING; building the table fresh means there is nothing to break |
| Composite same-organization FKs (a line cannot point at another organization's account) | `(tenant_id, organization_id, x_id)` composite FKs, the `fk_categories_parent_scope` precedent |

### 2.2 What we replace with machinery that already exists

| v2 builds | The platform already has | Consequence |
|---|---|---|
| `public.organizations (id, tenant_id)` anchor + `set_tenant_from_organization()` trigger | `org_management.organizations`; `OrgEntityMixin` composite FK `(tenant_id, organization_id)`; `app/database/tenancy.py` stamps both on insert and filters every query | No tenant-fill trigger; no `UNIQUE (id, tenant_id)` on organizations (it exists as `(tenant_id, id)`) |
| `created_by_id` / `updated_by_id` / `deleted_by_id` FKs to `public.users` | `AuditMixin` (`created_by`, `created_by_name`, `updated_by`, `updated_by_name`, no FK by design) + `SoftDeleteFilteredMixin` (`deleted_at`, `deleted_by`, `deleted_reason`) | The conformance test requires exactly these names |
| `accounting.bump_row_version()` trigger | `RowVersionMixin`: the ORM's `version_id_col` does it | Two mechanisms for one counter. Drop the trigger. Core updates bump it themselves (mixin docstring) |
| `accounting.polymorphic_type_registry` with `can_be_owner/counterparty/source` flags | `core.entity_types` (code → `target_schema.target_table`) + `core.assert_entity_exists()` + a per-feature opt-in table (`tax.taxable_entity_types`, `comments.commentable_entity_types`) | One registry. v2's validator also admits it "does not check tenant/organization of the target"; ours does |
| `accounting.currencies`, `accounting.exchange_rates` (global ISO list) | `currency.currencies` (org-scoped, `uq_currencies_tenant_id`), `currency.exchange_rates`, both synced from Zoho | Accounts reference `currency.currencies` through a composite tenant FK |
| `zoho_id` hot columns + `account_external_identities` + `journal_entry_external_identities` (L3) | `sync.sync_records` (the crosswalk) is the L3 edge for every module, plus an optional engine-maintained `zoho_id` echo (`SyncContract.identity_echo`) | No `*_external_identities` tables. `field_hashes` and verification of a match are crosswalk concerns |
| `external_entity_type_map` (vendor vocabulary → registry, with quarantine) | the translator's codecs (`sync/translation.py`) + a per-record failure in `zoho_sync_events` | Rebuilt in Phase 4 as a codec, when transactions are synced |
| `organization_accounting_settings.base_currency_code`, `.fiscal_year_start_month` | `organizations.currency_id` (FK to the base currency), `organizations.fiscal_year_start_month` (Zoho-synced) | Settings (Phase 2) keep only what organizations lack: lock date, books-start date, accounting basis |
| `accounting.audit_events` (hstore diff trigger on everything) | `activity` recorder (explicit, transactional) + pgaudit | Master data uses the recorder. **Ledger tables are the exception** (§9.4) |
| Per-file self-test `DO $$ … $$` blocks | pytest integration tests on the scratch database | Each self-test assertion becomes a test (§12) |

### 2.3 Defects found in v2 itself

1. **The account-type vocabulary is wrong in both directions.**
   - Zoho's documented `account_type` list has **38** values, including `right_to_use_asset`,
     `financial_asset`, `contingent_asset`, `contract_asset`, `contract_liability`,
     `refund_liability`, `loans_and_borrowing`, `lease_liability`,
     `employee_benefit_liability`, `contingent_liability`, `financial_liability`,
     `finance_income`, `other_comprehensive_income`, `manufacturing_expense`,
     `impairment_expense`, `depreciation_expense`, `employee_benefit_expense`,
     `lease_expense`, `finance_expense` and `tax_expense`. None of these are in v2's 26-row
     seed.
   - v2's seed (from the samples) has `stock`, `payment_clearing`, `overseas_tax_payable`,
     `deferred_tax_asset`, `deferred_tax_liability`, `capital_work_in_progress`,
     `intangible_assets_under_development` and `long_term_asset`, which are **not** in the
     documented list.
   - With v2's seed, the first account of a documented-only type fails the sync. The type
     table is the **union**, and an unknown code must fail one record visibly, not silently
     coerce (§5.1).
2. **The overlap guard races.**
   - `check_range_overlap()` is a deferred constraint trigger that runs `SELECT EXISTS(…)`.
     Two concurrent transactions each insert an overlapping fiscal year, each sees only its
     own snapshot, and both commit.
   - An `EXCLUDE USING gist` constraint is race-free.
   - v2 rejected it because `btree_gist` "requires approval", but the extension is
     **already installed** (`20260920_1100_…_geo_location_hub.py:42`), and
     `user_hub_assignments_no_overlap` already relies on it.
3. **The immutability guard contradicts the erasure rule.**
   - R8 says posted lines may still have `counterparty_name` **and `description`**
     anonymized.
   - `guard_journal_line()`'s allow-list omits `description`, so the DPDP erasure job would
     fail on every posted line that has a narration.
4. **`balance_cache` / `balance_as_of` sit on the account row.**
   - A cache column on a master row rewrites it whenever the balance moves. That means a
     `row_version` bump, an `updated_at` change, a Debezium event and a stale-ORM error for
     whoever holds the row.
   - The same applies to `has_children`, a stored cache v2 itself had to reconcile by query.
   - Balances belong in their own derived table (Phase 3, `account_period_balances`).
   - `has_children` is computed in the query (`EXISTS`) and never stored.
5. **Two sources of truth for system accounts.** v2 keeps the `is_retained_earnings` /
   `is_accounts_payable` / … flags **and** adds `account_role_assignments`, with a singleton
   index on the flags. One fact, two writers. We keep only assignments (§7).
6. **Type rules enforced against the master.** v2 rejects sub-accounts the type disallows,
   and cross-group parents, **in a trigger**. For rows Zoho masters, that trigger refuses
   Zoho's own chart: our replica would then be wrong, not Zoho right.
   - We enforce **structural** invariants in the database: cycles, scope, derived depth and
     normal balance.
   - **Type** rules apply to *local* writes in the service.
   - A validation query reports any Zoho-side violation (§5.3).
   - The categories lesson applies: whatever the reconcile lane writes with a bare
     `UPDATE … SET parent_id` must stay safe in the database. Structural rules give that;
     type rules are not needed for it.
7. **`cascade_account_depth()` changes descendants without bumping `row_version`.** Under
   `RowVersionMixin` a Core update must bump it, or an ORM object loaded before the
   re-parent writes its stale `depth` back. The cascade bumps it (§5.3).
8. **`next_document_number()` serializes all posting of one organization** on one counter
   row. That is correct for gap-free numbering and acceptable at our volumes, but it is a
   property to state rather than discover (§9.3).

---

### 2.4 Research findings (2026-10-08)

**Account types: your list, checked.** There are three sources, and none of them alone is
complete:

| Source | Codes | What it says |
|---|---|---|
| Zoho Books API docs, `account_type` allowed values ([Chart of Accounts API](https://www.zoho.com/books/api/v3/chart-of-accounts)) | 38 | includes IFRS-style types (`right_to_use_asset`, `lease_liability`, `finance_income`, `other_comprehensive_income`, `*_expense` by nature) |
| THPL's own account-types response (provided in review) | 26 | the types this tenant's edition actually offers, **with Zoho's numeric ids** (`"id": "1"` … `"112"`) and per-type rules |
| Your list | 41 | |

**Union: 46 codes, all seeded** (§5.1).

Your 41-code list is **missing 5 types the tenant itself returns**: `intangible_asset` (25),
`long_term_asset` (26, "Non Current Asset"), `capital_work_in_progress` (111),
`intangible_assets_under_development` (112) and `other_expense` (18). Two of these are
Schedule III balance-sheet lines (CWIP and IAUD), and `other_expense` is a type Zoho
explicitly allows sub-accounts under. They have to be in the seed: an account of a missing
type fails its sync (the type is an FK).

**Which types a given organization sees depends on its edition.**
- Zoho's India help page lists the 9 asset, 7 liability, equity, income/other income and
  expense defaults, with no IFRS types
  ([Zoho Books India help: Chart of Accounts](https://www.zoho.com/in/books/help/accountant/chart-of-accounts.html)).
- The tenant response has 26 types and no IFRS ones.
- So the 20 documented-only types belong to other editions. They are seeded with
  `zoho_id = NULL`, because their numeric id has never been observed. The id is filled the
  first time a tenant reports it.

**Sub-account rules disagree between Zoho's own sources.**
- The KB article lists sub-accounts as allowed for: Cash, Cost of Goods Sold, Equity,
  Expense, Fixed Asset, Income, Long Term Liability, Other Asset, Other Current Asset, Other
  Current Liability, Other Expense, Other Income, Other Liability, Stock
  ([Zoho KB](https://www.zoho.com/books/kb/accountant/accounts-supporting-sub-accounts.html)).
- The tenant response also says `true` for `accounts_receivable`, `accounts_payable`,
  `intangible_asset` and `long_term_asset`.
- **The seed follows the tenant response**: it is machine data from the live product, and
  the KB page is prose that lags.
- This is also why type rules are service-level, not triggers (§2.3 #6): Zoho stays the
  final arbiter of its own chart.

**Control accounts and subledgers.**
- Standard practice is a small number of control accounts (AR, AP) that subledgers roll up
  into.
- Customer and vendor detail lives in the subledger or in dimensions, not as one GL account
  each. Over-granular charts clutter reports and multiply reconciliations.
- Control accounts are locked against manual journals except approved corrections
  ([Sage control-account practice](https://cleverence.com/articles/sage-documentation/about-subsidiary-accounts-sage-4831)).
- This confirms §0 point 3, and it gives Phase 3 a rule: native manual journals to an
  account assigned as `receivable` / `payable` need `accounting.journal:post_control`.

**Schedule III.** Zoho Books does not produce a Schedule III balance sheet; the accounts are
mapped to Schedule III lines outside it
([Patron Accounting, Apr 2026](https://www.patronaccounting.com/blog/zoho-books-chart-of-accounts-india-setup)).
That keeps the statutory mapping table in Phase 3+ (§10).

## 3. Phases

| # | Phase | Delivers | Unblocks |
|---|---|---|---|
| **1** | **Chart of Accounts** | `account_types`, `accounts`, `account_purposes`, `account_purpose_policies`, `account_assignments`; `HasAccountsMixin`; registration helper; **resolution engine** (`app/modules/resolution/`, TaxFacet + AccountFacet); 46-type seed; `/chartofaccounts` sync (INBOUND, FULL default); API; organization defaults + tax-component accounts wired | Items and Contacts can declare taxes and accounts on day one; documents resolve both in O(1) queries |
| 2 | Accounting calendar & settings | `organization_accounting_settings` (lock date, books start, basis), `fiscal_years`, `accounting_periods` (EXCLUDE) | posting rules |
| 3 | General ledger | `journal_entries`, `journal_entry_lines`, dimensions, `document_sequences`, `account_period_balances`, ledger audit trail; posting, immutability, reversal | invoices / bills / payments modules |
| 4 | Zoho transactions projection | `/chartofaccounts/transactions` and `/journals` → `external_projection` entries | ledger reports over Zoho history |
| 5 | Banking | `bank_account_details` (P3, 1:1), `/bankaccounts` sync | bank reconciliation |
| 6 | Outbound | `POST/PUT /chartofaccounts`, `/active`, `/inactive` through the command outbox | local creation of Zoho accounts |

**Phase 1 is fully specified below. Phases 2–6 are specified to the level that lets Phase 1
avoid boxing them in.**

---

## 4. Package layout

```
app/modules/accounting/
  __init__.py          doctrine of the module; exports
  enums.py             ACCOUNTING_SCHEMA, AccountGroup, purposes, values()
  model.py             AccountType, Account
  assignment.py        AccountPurpose, AccountPurposePolicy, AccountAssignment
  mixins.py            HasAccountsMixin, account_owner_type_of()
  registration.py      register_account_owner_type(conn, ...)  — the one opt-in call
  schema.py            AccountSlimOut / AccountOut / AccountTreeNode / AccountCreate / AccountUpdate
  assignment_schema.py AssignmentOut / AssignmentPut / ResolvedAccountOut
  crud.py              list_slim (load_only), get_fat, subtree, children_counts
  assignment_crud.py
  service.py           create / update / deactivate / delete guards, owned-field guard
  assignment_service.py put_assignments, resolve_account(s)
  api.py               /api/accounting/account-types, /api/accounting/accounts
  assignment_api.py    /api/accounting/assignments/..., /api/accounting/resolve
  seed_data.py         the 46 account types (§5.1) and the purposes (§5.4) — data, loaded by the migration
  resolution.py        AccountFacet (§7.4) + the account policies this module owns
  zoho/
    fields.py          the field map (§6.2)
    codecs.py          account_type, blank→NULL, tolerant bool, Zoho offset datetimes
    translator.py      CHART_OF_ACCOUNTS_TRANSLATOR
    hooks.py           parent resolution, pending references
    spec.py            CHART_OF_ACCOUNTS_CONFIG + SPEC
```

**Why `accounting`, not `accounts`:** `accounts` collides with the user-account vocabulary
of `users/` and `auth`, and v2's schema is already `accounting`. The user-facing name stays
"Accounts" / "Chart of Accounts".

**Import direction** (`.importlinter`): `accounting` is a lower layer. It may import `entities`,
`currencies`, `organizations`, `sync`, and `zoho.sync` (adapter only). The modules that
*carry* accounts (items, customers, taxes) import `accounting.mixins` / `accounting.registration`,
never the reverse. Add `accounting` to the layered contract below the feature modules.

---

## 5. Data model, Phase 1

Mixins are listed most-specific first; `Base` is always last. Every table goes in schema
`accounting`, which is added to `_OWNED_SCHEMAS` in `alembic/env.py`.

### 5.1 `accounting.account_types`: GLOBAL reference

`BigIntPKWithUUIDv7Mixin, AuditMixin, AppMetaMixin, TimestampMixin, Base`. It is **not**
soft-deletable: it is an FK target by `code`, and PostgreSQL cannot reference a partial
unique index (the reason `tax.taxable_entity_types` gives). A type is retired with
`is_enabled = false`. `GLOBAL_TABLES` reason: "Zoho / IFRS account-type vocabulary,
identical for every tenant — reference data like countries".

| Column | Type | Null | Notes |
|---|---|---|---|
| `code` | `String(64)` | NO | **UNIQUE (non-partial)**, the FK target; Zoho `account_type` |
| `zoho_id` | `String(16)` | YES | Zoho's numeric type id (`"1"`…`"112"`), a vendor-wide constant; partial unique `WHERE zoho_id IS NOT NULL`. NULL = never observed in a tenant response |
| `name` | `Text` | NO | `account_type_formatted` / `text` |
| `account_group` | `String(16)` | NO | CHECK `asset / liability / equity / income / expense` |
| `default_normal_balance_is_debit` | `Boolean` | NO | asset/expense true; liability/equity/income false |
| `is_sub_account_allowed` | `Boolean` | YES | Zoho flag; NULL = not reported (the 20 documented-only types) → the service allows it and Zoho decides on push |
| `can_show_opening_balance` | `Boolean` | YES | Zoho sends the **string** `"true"`; tolerant bool |
| `can_enable_in_ze` | `Boolean` | YES | usable in Zoho Expense |
| `asset_type` | `String(32)` | YES | `fixed_asset`, `cwip`, `iaud` |
| `is_documented` | `Boolean` | NO | in the API docs' allowed values |
| `is_sales_eligible` / `is_purchase_eligible` / `is_inventory_eligible` | `Boolean` | NO | picker eligibility (§7.11) |
| `is_enabled` | `Boolean` | NO | default true |
| `sort_order` | `SmallInteger` | NO | the tenant response's order; documented-only types after their group |
| `description` | `Text` | YES | |

**Seed: all 46 types.** In the table below:
- **Doc** = in the API's allowed values; **Tenant** = in THPL's response.
- **Sub / OB / ZE** = `is_sub_account_allowed`, `can_show_opening_balance`,
  `can_enable_in_ze`.
- **—** = not reported, stored as NULL.
- The normal side follows the group (Dr for asset and expense).

| # | code | zoho_id | name | group | Sub | OB | ZE | asset_type | Doc | Tenant |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `other_asset` | 1 | Other Asset | asset | ✓ | ✓ | ✓ | | ✓ | ✓ |
| 2 | `other_current_asset` | 2 | Other Current Asset | asset | ✓ | ✓ | ✓ | | ✓ | ✓ |
| 3 | `cash` | 3 | Cash | asset | ✓ | ✓ | ✓ | | ✓ | ✓ |
| 4 | `bank` | 4 | Bank | asset | ✗ | ✗ | ✓ | | ✓ | ✓ |
| 5 | `fixed_asset` | 6 | Fixed Asset | asset | ✓ | ✓ | ✓ | `fixed_asset` | ✓ | ✓ |
| 6 | `accounts_receivable` | 5 | Accounts Receivable | asset | ✓ | ✗ | ✗ | | ✓ | ✓ |
| 7 | `stock` | 19 | Stock | asset | ✓ | ✗ | ✗ | | | ✓ |
| 8 | `payment_clearing` | 20 | Payment Clearing Account | asset | ✗ | ✓ | ✗ | | | ✓ |
| 9 | `intangible_asset` | 25 | Intangible Asset | asset | ✓ | ✓ | ✓ | | ✓ | ✓ |
| 10 | `long_term_asset` | 26 | Non Current Asset | asset | ✓ | ✓ | ✗ | | | ✓ |
| 11 | `deferred_tax_asset` | 27 | Deferred Tax Asset | asset | ✗ | ✓ | ✗ | | | ✓ |
| 12 | `capital_work_in_progress` | 111 | Capital Work In Progress | asset | ✗ | ✓ | ✗ | `cwip` | | ✓ |
| 13 | `intangible_assets_under_development` | 112 | Intangible Assets Under Development | asset | ✗ | ✓ | ✗ | `iaud` | | ✓ |
| 14 | `right_to_use_asset` | — | Right To Use Asset | asset | — | — | — | | ✓ | |
| 15 | `financial_asset` | — | Financial Asset | asset | — | — | — | | ✓ | |
| 16 | `contingent_asset` | — | Contingent Asset | asset | — | — | — | | ✓ | |
| 17 | `contract_asset` | — | Contract Asset | asset | — | — | — | | ✓ | |
| 18 | `other_current_liability` | 8 | Other Current Liability | liability | ✓ | ✓ | ✓ | | ✓ | ✓ |
| 19 | `credit_card` | 9 | Credit Card | liability | ✗ | ✗ | ✓ | | ✓ | ✓ |
| 20 | `long_term_liability` | 11 | Non Current Liability | liability | ✓ | ✓ | ✓ | | ✓ | ✓ |
| 21 | `other_liability` | 12 | Other Liability | liability | ✓ | ✓ | ✓ | | ✓ | ✓ |
| 22 | `accounts_payable` | 10 | Accounts Payable | liability | ✓ | ✗ | ✗ | | ✓ | ✓ |
| 23 | `overseas_tax_payable` | 22 | Overseas Tax Payable | liability | ✗ | ✓ | ✗ | | | ✓ |
| 24 | `deferred_tax_liability` | 28 | Deferred Tax Liability | liability | ✗ | ✓ | ✗ | | | ✓ |
| 25 | `contract_liability` | — | Contract Liability | liability | — | — | — | | ✓ | |
| 26 | `refund_liability` | — | Refund Liability | liability | — | — | — | | ✓ | |
| 27 | `loans_and_borrowing` | — | Loans And Borrowing | liability | — | — | — | | ✓ | |
| 28 | `lease_liability` | — | Lease Liability | liability | — | — | — | | ✓ | |
| 29 | `employee_benefit_liability` | — | Employee Benefit Liability | liability | — | — | — | | ✓ | |
| 30 | `contingent_liability` | — | Contingent Liability | liability | — | — | — | | ✓ | |
| 31 | `financial_liability` | — | Financial Liability | liability | — | — | — | | ✓ | |
| 32 | `equity` | 13 | Equity | equity | ✓ | ✓ | ✗ | | ✓ | ✓ |
| 33 | `income` | 14 | Income | income | ✓ | ✓ | ✗ | | ✓ | ✓ |
| 34 | `other_income` | 15 | Other Income | income | ✓ | ✓ | ✗ | | ✓ | ✓ |
| 35 | `finance_income` | — | Finance Income | income | — | — | — | | ✓ | |
| 36 | `other_comprehensive_income` | — | Other Comprehensive Income | income | — | — | — | | ✓ | |
| 37 | `expense` | 16 | Expense | expense | ✓ | ✓ | ✓ | | ✓ | ✓ |
| 38 | `cost_of_goods_sold` | 17 | Cost Of Goods Sold | expense | ✓ | ✓ | ✓ | | ✓ | ✓ |
| 39 | `other_expense` | 18 | Other Expense | expense | ✓ | ✓ | ✓ | | ✓ | ✓ |
| 40 | `manufacturing_expense` | — | Manufacturing Expense | expense | — | — | — | | ✓ | |
| 41 | `impairment_expense` | — | Impairment Expense | expense | — | — | — | | ✓ | |
| 42 | `depreciation_expense` | — | Depreciation Expense | expense | — | — | — | | ✓ | |
| 43 | `employee_benefit_expense` | — | Employee Benefit Expense | expense | — | — | — | | ✓ | |
| 44 | `lease_expense` | — | Lease Expense | expense | — | — | — | | ✓ | |
| 45 | `finance_expense` | — | Finance Expense | expense | — | — | — | | ✓ | |
| 46 | `tax_expense` | — | Tax Expense | expense | — | — | — | | ✓ | |

Accounting notes the accountant signs off (§13, decision 5):
- `contingent_asset` / `contingent_liability` are disclosed, not recognised, under
  Ind AS 37. They are seeded in Zoho's nominal group.
- `other_comprehensive_income` closes to equity (OCI reserve), not to retained earnings.
  This matters for the Phase 3 year-end close, not for Phase 1.

**Where the seed comes from.**
- The seed is data in `accounting/seed_data.py`, loaded by the migration with
  `ON CONFLICT (code) DO UPDATE` of `zoho_id` only when it is NULL. Re-runs never overwrite
  an operator's change.
- The vendored response is the test oracle: `test_account_type_seed_matches_tenant_response`
  asserts each of the 26 observed rows field by field.
- **Unknown code from Zoho:** `accounts.account_type` is an FK, so one record fails visibly
  (`zoho_sync_events`), never the page, and never coerced into a guessed group. A guessed
  group derives a wrong normal balance and corrupts every report built on it.

### 5.2 `accounting.accounts`: the chart, ENTITY

```python
class Account(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, VerificationMixin, HashGuardMixin,
    HasTagsMixin, HasDocumentsMixin, HasCommentsMixin, HasCustomFieldsMixin,
    SoftDeleteFilteredMixin, Base,
):
    __tablename__ = "accounts"
    __commentable_type__ = "account"
    custom_fields_owner_type = "account"
```

`OrgEntityMixin` gives: `tenant_id` and `organization_id` NOT NULL with a composite FK;
`created_by[_name]` / `updated_by[_name]`; `status`; `is_verified`; `row_version`;
`app_version`; `app_metadata`; `created_at`; `updated_at`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `account_type` | `String(64)` | NO | FK → `account_types.code` RESTRICT |
| `parent_id` | `BigInteger` | YES | composite FK `(tenant_id, organization_id, parent_id)` → `accounts (tenant_id, organization_id, id)` |
| `account_code` | `Text` | YES | opaque, leading zeros kept; CHECK `btrim(account_code) <> ''` |
| `account_name` | `Text` | NO | CHECK not blank |
| `display_name` | `Text` | — | `Computed("CASE WHEN account_code IS NULL THEN account_name ELSE account_code \|\| ' - ' \|\| account_name END", persisted=True)` |
| `description` | `Text` | YES | |
| `currency_id` | `BigInteger` | YES | composite FK `(tenant_id, currency_id)` → `currency.currencies (tenant_id, id)`. **NULL = the organization's base currency** (`organizations.currency_id`) |
| `is_contra` | `Boolean` | NO | default false. Accumulated depreciation, sales returns |
| `normal_balance_is_debit` | `Boolean` | NO | **trigger-derived**; never written by the app |
| `depth` | `SmallInteger` | NO | **trigger-derived**; 0 for roots |
| `is_system_account` | `Boolean` | NO | Zoho `is_system_account`; a system account cannot be deleted or re-typed |
| `is_user_created` | `Boolean` | YES | sample-only (`is_user_created`); NULL = not reported |
| `placeholder` | `Text` | YES | sample-only Zoho template slug (`gl_goods_in_transit`). **The robust key for recognising system accounts** across organizations; matching on names is not robust |
| `is_expense_claim_enabled` | `Boolean` | YES | Zoho `can_show_in_ze` |
| `show_on_dashboard` | `Boolean` | YES | create/update argument only (not in the documented response) |
| `zoho_id` | `String(50)` | YES | **engine-maintained echo** of Zoho `account_id` (`SyncContract.identity_echo`), never written by hand, never the identity of record (that is `sync.sync_records`). Partial unique per organization. Answers "is this row Zoho-linked?" without a join, which every local edit asks |

**Lifecycle, one signal.**
- `status` (from `StatusMixin`) is CHECKed to `active` / `inactive`. Zoho's `is_active` maps
  onto it through a codec.
- `Account.is_active` is a `hybrid_property` (`status == 'active'`), so filters still read
  naturally.
- Zoho's `/active` and `/inactive` endpoints are status transitions (Phase 6).
- No `DeactivationMixin`: that would be a third signal, the bug v2 had to fix with a CHECK.
- This deliberately differs from `tax_components`, which keep Zoho's `is_inactive` echo
  *and* a local lifecycle because a tax has a local grant lifecycle of its own. An account
  does not.

**Constraints & indexes**
- `UNIQUE (tenant_id, organization_id, id)`: the target of the composite parent FK and of
  every same-organization FK into accounts.
- `UNIQUE (tenant_id, id)`: the target for tenant-only composite FKs.
- `uq_accounts_code` on `(organization_id, account_code)` WHERE `deleted_at IS NULL AND
  account_code IS NOT NULL`. Zoho enforces unique codes per organization in the UI; to be
  verified on the live chart before the index ships (§13, decision 3).
- `uq_accounts_zoho_id` on `(tenant_id, zoho_id)`, partial (live and not null). This is the
  categories precedent.
- `ix_accounts_org_type` on `(organization_id, account_type)`, live: the picker and the type
  filter.
- `ix_accounts_parent` on `(parent_id)`, live: tree reads and the `has_children` `EXISTS`.
- `ix_accounts_name_trgm` GIN `(account_name gin_trgm_ops)`, live: `q=` search. A few hundred
  rows per organization; **not** a Meilisearch index (§10).
- CHECKs: `parent_id <> id`; `depth >= 0`; `(parent_id IS NULL) = (depth = 0)`; status
  vocabulary; not-blank on name and code.

**Not stored, on purpose:**
- `has_children`, `child_count`, `is_child_present`: computed in the query.
- `is_involved_in_transaction`: an `EXISTS` on assignments today, on ledger lines from
  Phase 3.
- `current_balance`, `closing_balance`: volatile (§2.3 #4).
- `parent_account_name`, `account_name_with_account_code`, `*_formatted`: presentation,
  as `@computed_field`s.
- `documents`, `has_attachment`: the documents module.
- `custom_fields`: captured raw on the crosswalk, typed values via `extfields`.
- Bank columns: §10.

### 5.3 Database-enforced invariants

**`accounting.derive_account_fields()`** runs BEFORE INSERT OR UPDATE OF `parent_id`,
`account_type`, `is_contra`:

1. **Normal balance:** `normal_balance_is_debit := type.default_normal_balance_is_debit <> is_contra`.
2. **Root:** `parent_id IS NULL` → `depth := 0`.
3. **Child:**
   - Read the parent with `FOR SHARE`, so a concurrent re-parent of the parent cannot
     interleave.
   - Set `depth := parent.depth + 1`.
   - Walk the ancestors (bounded at 32) and raise `22000` if `NEW.id` appears.
   - A cross-organization parent is already impossible (composite FK), so the walk only
     looks for cycles.

**`accounting.cascade_account_depth()`** runs AFTER UPDATE OF `parent_id` WHEN the value
changed:
- It is a recursive CTE over the moved subtree that sets `depth` **and
  `row_version = row_version + 1`** (§2.3 #7).
- It is safe for the reconcile lane's bare `UPDATE accounting.accounts SET parent_id = …`.

**`accounting.guard_account_delete()`** runs BEFORE UPDATE OF `deleted_at` (soft delete is
an UPDATE). It refuses to soft-delete:
- an account with live children;
- an account with live assignments;
- (from Phase 3) an account with ledger lines.

It raises `23503` with the reason. The sync's tombstone path is not exempt: Zoho refuses to
delete an account "associated in any transaction/products", so a Zoho delete of a
referenced account means our references are stale. Surfacing that is correct.

**Not in the database, by design (§2.3 #6):** `is_sub_account_allowed` and the same-group
parent rule. `service.py` enforces them on local writes, and
`accounting.find_chart_violations(org_id)` reports Zoho-side violations as rows (type, parent
type, reason). It is run by the Phase 1 acceptance test against the live chart.

### 5.4 `accounting.account_purposes`: GLOBAL vocabulary

**What a purpose is:** *why* an entity points at an account. It is the account-side
analogue of a tax context.

| Column | Notes |
|---|---|
| `code` `String(48)` UNIQUE (non-partial) | FK target |
| `name`, `description` | |
| `allowed_groups` `ARRAY(String)` NOT NULL | the account's group must be in it. Checked by the assignment trigger, so a "receivable" can never point at a liability (v2's `validate_role_assignment`) |
| `allowed_types` `ARRAY(String)` NULL | a narrower rule where one exists (`inventory_asset` → `{stock}`). NULL = any type of the allowed groups |
| `per_currency` `Boolean` | true = one assignment per (owner, purpose, currency); AR/AP control accounts in a multi-currency organization |
| `is_enabled` | |

**Seed (Phase 1):**

| code | groups | from |
|---|---|---|
| `sales` | income | Zoho item `account_id` |
| `purchase` | expense, asset | Zoho item `purchase_account_id` ("COGS account"; asset allowed for capitalised purchases) |
| `inventory_asset` | asset (`stock`) | Zoho item `inventory_account_id` |
| `receivable` | asset (`accounts_receivable`) | per-customer override / org AR control |
| `payable` | liability (`accounts_payable`) | per-vendor override / org AP control |
| `customer_advance`, `vendor_advance` | liability / asset | |
| `output_tax`, `input_tax`, `tds_payable` | liability / asset | `tax.tax_components.tax_account_id`, `purchase_tax_account_id`, `tds_payable_account_id` |
| `retained_earnings`, `opening_balance_offset` | equity | org defaults |
| `fx_gain_loss`, `round_off` | income, expense | |
| `discount_given`, `discount_received` | expense / income | |
| `cost_of_goods_sold`, `inventory_adjustment`, `goods_in_transit`, `price_variance` | expense / asset | v1 `organization_inventory_preferences` columns |
| `undeposited_funds`, `tds_receivable`, `tcs_payable`, `employee_advance`, `prepaid_expenses` | per v2 roles | |

The groups above are the accounting default. **The accountant signs the seed off before it
ships** (§13, decision 5).

### 5.5 `accounting.account_purpose_policies`: GLOBAL policy

**Which entity classes may carry which purposes.** This is `tax.taxable_entity_types`,
extended to one row per (class, purpose).

| Column | Notes |
|---|---|
| `entity_type_code` → `core.entity_types.code` | |
| `purpose_code` → `account_purposes.code` | |
| `falls_back_to_organization` `Boolean` | true = when the owner has no assignment, the resolver uses the organization's |
| `is_enabled` | |
| UNIQUE `(entity_type_code, purpose_code)` (non-partial) | composite FK target of assignments |

Rows are written by the owning module's migration through
`registration.register_account_owner_type()` (§8), never by an API.

### 5.6 `accounting.account_assignments`: ENTITY, polymorphic

`BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base`. This is
`tax.tax_assignments` with accounts in place of taxes. Tax and account assignments are
**separate tables on purpose**: taxes carry contexts, exemptions, ordered groups and frozen
snapshots, and accounts carry a purpose and a currency. One merged table would be a union
of two shapes with half its columns NULL. They are unified where it matters, at read time,
by the resolution engine (§7).

| Column | Notes |
|---|---|
| `owner_type_code` `String(64)` NOT NULL | |
| `owner_id` `BigInteger` NOT NULL | no FK (polymorphic); proved at COMMIT |
| `purpose_code` `String(48)` NOT NULL | |
| composite FK `(owner_type_code, purpose_code)` → `account_purpose_policies (entity_type_code, purpose_code)` | the class is registered **and** opted in to this purpose, in the database |
| `account_id` `BigInteger` NULL | composite FK `(tenant_id, organization_id, account_id)` → `accounts`: the account is in the assignment's organization, structurally |
| `currency_id` `BigInteger` NULL | composite tenant FK → `currency.currencies`; NULL = any / base; only when `purpose.per_currency` |
| `external_ref` `Text` NULL, `source_system` `String(32)` NULL | **pending** link: a source named an account not synced yet. The reconcile lane links it |
| CHECK `account_id IS NOT NULL OR (external_ref IS NOT NULL AND source_system IS NOT NULL)` | |
| `uq_account_assignments_slot` on `(organization_id, owner_type_code, owner_id, purpose_code, currency_id)` **NULLS NOT DISTINCT**, live | one account per slot **per organization** (below) |
| `ix_account_assignments_owner` on `(owner_type_code, owner_id)`, live | read path, and the engine's candidate query |
| `ix_account_assignments_account` on `(account_id)`, live and not null | impact analysis + the delete guard |

**Why `organization_id` is in the slot.** Some owners are **tenant-wide**:
`tax.tax_components` is `TenantEntityMixin` (`organization_id` NULL = shared, granted per
organization via `organization_tax_components`). One CGST component can post to account X in
organization A and account Y in organization B, because charts of accounts are
per-organization. So:
- An assignment always belongs to the organization of its **account**.
- The slot is unique per organization.
- The integrity check accepts an owner that is either in the same organization or
  tenant-wide in the same tenant.

Contacts and items are org-scoped, so for them this degenerates to "same organization".

**`accounting.check_account_assignment_integrity()`** (deferred constraint trigger) checks:
1. the owner exists (`core.assert_entity_exists`);
2. the owner's tenant equals the row's, and the owner's organization is NULL or equals the
   row's;
3. the policy is enabled;
4. the account's group ∈ `purpose.allowed_groups` (and its type ∈ `allowed_types`);
5. `currency_id` is NULL unless `per_currency`.

`accounting.find_orphan_account_assignments()` runs in the reconcile lane.

**`source_system`:**
- `NULL` = maintained locally.
- `'zoho'` = fed by a sync, read-only through the API (the `tax_assignments` rule).

## 6. Zoho sync: `chart_of_accounts`

### 6.1 Module config

```python
CHART_OF_ACCOUNTS_CONFIG = resolve_module_config(
    module="chart_of_accounts",
    endpoint="/chartofaccounts",
    zoho_id_attr="account_id",
    strategy=SyncStrategyName.FULL,            # the default (owner decision); INCREMENTAL is a runtime override
    modified_since_param="last_modified_time", # declared + trusted, so the override needs no deploy
    sort_column=None,                          # only account_name / account_type are sortable; neither is time-ordered
    direction=SyncDirection.INBOUND,           # Zoho masters the chart (Phase 6 adds outbound)
    detail_required=True,
    detail_dispatch="inline",
    index_then_detail=True,
    sync_interval_minutes=1440,
    weekly_full_enabled=False,                 # the scheduled lane already IS full; set True with the INCREMENTAL override
    field_map=CHART_OF_ACCOUNTS_FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table="accounting.accounts",
        crosswalk=True,
        identity_echo=("zoho_id",),
        match_on=("zoho_id",),                 # re-adoption only (categories precedent), never a business-key merge
        history_raw=True,
        capture_custom_fields=True,
        owned_fields=ZOHO_OWNED_ACCOUNT_FIELDS, # = frozenset(TRANSLATOR.readable)
        references=(
            ReferenceRule(attr="currency_id", module="currencies", fk="currency_id",
                          on_missing=OnMissing.DEFER),
        ),
    ),
)
```

**Strategy: FULL by default, INCREMENTAL one switch away.**
- `last_modified_time` is trusted (owner decision), so the module declares
  `modified_since_param` now.
- Switching to INCREMENTAL is a control-plane override
  (`zoho/control/config.py`: `{"strategy": "incremental", "weekly_full_enabled": true}`).
  It is per module, takes effect at runtime, and shows its layer in
  `GET /api/zoho/admin/modules/{name}/config`.
- The weekly full must come with it: an incremental list never shows a delete.
- Under FULL the apply gate makes an unchanged chart nearly free. Every row is hashed, and
  an unchanged one costs no write and no detail call.

**Platform default → FULL.** `ModuleSyncConfig.strategy` (`zoho/sync/config.py:87`)
defaults to `INCREMENTAL` today. Phase 1 changes the default to `FULL`. This is safe
**today**: all nine registered modules declare `strategy=` explicitly (brands, taxes ×3,
locations, zoho_users, categories, currencies, organizations — checked), so none changes
behaviour. Only a future module that forgets to declare a strategy is affected, and FULL is
the safe failure (complete, just slower). INCREMENTAL silently skips rows when a module's
modified filter is wrong.

Why the other choices:
- **`index_then_detail` + inline detail.**
  - The list row lacks `currency_id`, `description`, `custom_fields` and
    `include_in_vat_return`.
  - Writing the index row first means an item or tax naming the account resolves the moment
    it is listed.
  - First sync: one detail call per account. A few hundred calls at the governor's budget is
    minutes, once.
- **Never `showbalance=true`.**
  - `current_balance` changes without the account changing. In the raw hash it would make
    every scan a write.
  - It is also listed in the translator's volatile keys.
- **`match_on=("zoho_id",)`, never `account_name`.** Zoho repeats child names across
  branches (`Cash Ledger : Interest`). A name match merges two ledgers, and that is
  unrecoverable once lines post to them.
- **Parent: a hook, not a `ReferenceRule`** (the categories pattern).
  - `post_upsert` resolves `parent_account_id` through `crosswalk.resolve_many`.
  - It queues the unresolved ones on `sync.pending_references`
    (`accounting.accounts.parent_id`).
  - The reconcile lane's bare UPDATE fires the §5.3 triggers (depth, `row_version`).
- **Currency: `DEFER`.** An unsynced currency leaves `currency_id` NULL (= base) until the
  reconcile lane links it. It is never a stub currency.
- **Planner ordering.** `chart_of_accounts` depends on `organizations` and `currencies`;
  `taxes`, and later `items` and `contacts`, depend on `chart_of_accounts` for their account
  links. Until the `depends_on` DAG exists (delta-v3 §6.2), pending references make any
  order converge.

### 6.2 Field map

Legend: **D** = documented, **S** = sample-only (applied only when present: a key the source
did not send is skipped, never decoded to NULL).

| Zoho | → local | Dir | Codec / note | |
|---|---|---|---|---|
| `account_id` | crosswalk `external_id` + `zoho_id` echo | IN | string, never numeric (18-digit ids exceed 2^53) | D |
| `account_name` | `account_name` | BOTH | | D |
| `account_code` | `account_code` | BOTH | `blank_to_null` | D |
| `account_type` | `account_type` | BOTH | identity on the code. Unknown → FK failure per record (§5.1) | D |
| `account_type_int` | — | IN | **not on the account**; it is a type constant. If `account_types.zoho_id` is NULL for that code the hook fills it (set-once, logged); a mismatch logs `accounting.type_id_mismatch` and changes nothing | S |
| `currency_id` | `currency_id` | BOTH | `ReferenceRule` → `currencies` | D |
| `currency_code` | — | IN | derivable; kept raw | D |
| `description` | `description` | BOTH | | D |
| `is_active` | `status` | IN | `active` / `inactive`. Outbound is the `/active` / `/inactive` endpoints, not the body | D |
| `is_system_account` | `is_system_account` | IN | tolerant bool | D |
| `is_user_created` | `is_user_created` | IN | | S |
| `can_show_in_ze` | `is_expense_claim_enabled` | BOTH | | D |
| `show_on_dashboard` | `show_on_dashboard` | OUT (+IN if present) | | D/S |
| `include_in_vat_return` | — | OUT-capable later | UK-only; raw only | D |
| `parent_account_id` | `parent_id` | BOTH | hook (§6.1); `""` → root | D |
| `placeholder` | `placeholder` | IN | | S |
| `custom_fields` | crosswalk `custom_fields` + `extfields` values | IN | the extfields projection follows the module convention | D |
| `created_time`, `last_modified_time` | crosswalk `source_modified_at` | IN | `+0530` (no colon) offset parser | D |
| `is_involved_in_transaction`, `current_balance`, `closing_balance`, `depth`, `child_count`, `is_child_present`, `parent_account_name`, `has_attachment`, `documents` | — | — | **volatile keys / derived**; excluded from the raw hash where volatile | D |
| `is_retained_earnings`, `is_accounts_receivable`, `is_accounts_payable`, `gain_or_loss_account`, `is_default_purchase_discount`, `is_primary_account`, … | → organization **assignments** (`source_system='zoho'`) via `post_upsert` | IN | projected only when present (sample-only) | S |
| `price_precision`, `ignore_currency`, `allow_multi_currency`, `account_icon`, `account_hint`, `is_standalone_account`, `schedule_balancesheet_category`, `schedule_profit_and_loss_category`, `masked_account_no` | raw only | — | not modelled until a consumer exists (§11 lists each) | S |

**Payload quirks the codecs absorb** (v2 R3, all observed in the samples):
- money as JSON floats → `Decimal` with a scale guard;
- ids parsed as strings;
- `""` → NULL for `account_code`, `parent_account_id` and the count fields;
- `"true"` string booleans;
- `+0530` offsets without a colon;
- `*_formatted` strings never parsed (`₹7,53,101.54`);
- the `{"code":0,"message":"success"}` envelope checked even on HTTP 200 (the transport
  already does this).

### 6.3 Ownership and local edits

- `ZOHO_OWNED_ACCOUNT_FIELDS = frozenset(TRANSLATOR.readable)`. A PATCH touching an owned
  field on a Zoho-linked row (`zoho_id IS NOT NULL`) gets **422 `zoho_owned_field`**, the
  `categories/service._guard_zoho_owned` precedent.
- Local-only accounts are allowed in organizations without a Zoho connection.
  - In a Zoho-connected organization, local creation is refused before Phase 6
    (`422 zoho_mastered_chart`).
  - The reason: an item pointing at a local-only account could never be pushed, and that
    failure would surface far from its cause.
- `to_zoho_payload()` (create/update) is written in Phase 1 as the seam the outbox will
  call.
  - The CREATE intent requires `account_name` and `account_type`, checked locally with the
    field named.
  - Zoho's docs mark every argument "Optional", but neither field is.

### 6.4 Tenant and organization: THPL by default

There is nothing new to configure. The engine places every row through
`zoho/control/tenancy.py::zoho_tenant` (delta-v3 §2.1):
1. the organization node carrying `ZOHO_ORGANIZATION_ID` (`60015628348`), which is THPL
   after the seeder's adoption;
2. otherwise the configured default, `DEFAULT_TENANT_CODE=THPL` /
   `DEFAULT_ORGANIZATION_CODE=THPL` (`backend/.env`);
3. otherwise the tenant's only organization.

Two things must hold:
- `deployment/.env` must carry the same `DEFAULT_*` values, and `docker-compose.yml` must
  pass them. This is delta-v3 gotcha #1, which caused the two-tenant incident.
- The startup check proposed in delta-v3 §6.5 would catch drift.

GLOBAL seeds (types, purposes, policies) have no tenant. THPL's **organization default
assignments** are written by a seed step after the first chart sync (§8.5).

## 7. The resolution engine: "what applies here?", for every facet

### 7.1 Why one engine

The question "which X applies to this line?" is about to be asked by every document module,
for several X:

| Facet | Today | Needed by |
|---|---|---|
| taxes | `taxes.assignment_service.resolve_taxes`: a loop of **one query per owner**, the org default from `org_default_tax_preferences`, the chain hand-built by each caller | items, contacts, invoices, bills, sales orders |
| accounts | — | the same documents, plus ledger posting |
| later: price list, payment terms, salesperson, warehouse, discount account | — | sales & purchase documents |

The cost of not having one engine:
- Every module hand-writes its own precedence, and the precedences drift. A sales order and
  an invoice for the same item to the same customer pick different accounts, and nobody can
  say which is right.
- A loop of per-owner queries is an N+1 at invoice scale: 200 lines × 4 owners × 2 facets
  is 1,600 queries.

The engine fixes both:
- **Precedence becomes data**: a named, versioned policy per (facet, subject kind).
- **Resolution becomes batched**: one query per facet per page, whatever the number of lines.

### 7.2 Concepts

| Concept | What it is |
|---|---|
| `OwnerRef(type_code, id)` | an entity that can *carry* facet values: `item:4`, `contact:12`, `category:2`, `organization:1`. `type_code` is a `core.entity_types.code` |
| **Subject** | the thing being resolved *for*: one invoice line. Holds a role → owner map, e.g. `{"line": OwnerRef("invoice_line", 9), "item": …, "contact": …}`, plus `organization_id` and a context |
| **Facet** | a kind of answer (`tax`, `account`). It owns: how candidates are loaded for many owners at once, how one owner's candidates are narrowed by context, what the organization default is, and what makes a value unusable |
| **Context** | the facet's typed question. Tax: `specification` (inter/intra), `transaction_type`. Account: `purpose`, `currency_id` |
| **Policy** | ordered **steps** for one (facet, subject kind): which role to ask, with an optional candidate filter, and what to do when the answer is unusable |
| **Expander** | turns one owner into the owners it inherits from: an item → its tax-category assignments (`core.categorizables` in the tax taxonomy). Registered by the module that owns the relationship, batched |
| **Resolution** | value(s) + provenance (`via` step, `owner`) + an optional **trace** of every step tried and why it did not answer |

### 7.3 Package and dependency direction

```
app/modules/resolution/          source-neutral, imports NO feature module
  types.py        OwnerRef, Subject, Step, Policy, Resolution, TraceEntry, Unusable
  registry.py     register_facet / register_policy / register_expander; boot validation
  engine.py       resolve_many()  — batched, the only entry point
  api.py          POST /api/resolution/{facet}  (+ ?explain=true)
  schema.py
```

- Features **register into** it, the same inversion as the Zoho registry:
  - `taxes/resolution.py` registers `TaxFacet` and the tax policies;
  - `accounting/resolution.py` registers `AccountFacet` and the account policies;
  - `categories` registers the item → category expander.
- `.importlinter`: `app.modules.resolution` may not import feature modules; feature modules
  may import it.
- Registration happens at import through the same autodiscovery as `_ENTITY_PACKAGES`.
- A policy naming an unknown facet, role or expander **fails the boot**, like a bad sync
  spec.

### 7.4 The facet contract

```python
class Facet(Protocol[Ctx, Candidate, Value]):
    code: str                                    # "tax" | "account"
    context_model: type[Ctx]                     # pydantic; validated at the API edge

    async def load(self, db: AsyncSession, owners: Collection[OwnerRef], ctx: Ctx
                   ) -> Mapping[OwnerRef, Sequence[Candidate]]:
        """ONE query for every owner of the page (pending rows excluded)."""

    def select(self, candidates: Sequence[Candidate], ctx: Ctx) -> Sequence[Candidate]:
        """PURE. Narrow one owner's candidates to what applies in ctx; [] = no answer here."""

    async def organization_default(self, db: AsyncSession, org_ids: Collection[int], ctx: Ctx
                                   ) -> Mapping[int, Sequence[Candidate]]:
        """ONE query. The last step of every policy."""

    def unusable(self, candidate: Candidate) -> str | None:
        """Why an answer cannot be used (inactive / deleted / not granted), else None."""

    def value(self, chosen: Sequence[Candidate]) -> Value: ...
```

| | `TaxFacet` | `AccountFacet` |
|---|---|---|
| `load` | `tax_assignments` for the owners, joined to component / exemption | `account_assignments` for the owners and `ctx.purpose`, joined to the account |
| `select` | **the existing `select_applicable`**, unchanged: most-specific context level wins, then `position` | exact `currency_id` > NULL currency; a single winner |
| `organization_default` | `org_default_tax_preferences` for `ctx.specification` | `account_assignments` where `owner = ("organization", org)` |
| `unusable` | component inactive / not granted to the organization (`organization_tax_components`) | account `inactive` or soft-deleted |
| `value` | ordered components + exemptions (several taxes apply together) | one account |

### 7.5 Policies are data

A policy is a tuple of steps:

```python
Step(role: str, filter: str | None = None, on_unusable: Literal["fail", "skip"] = "fail")
```

The **organization default is always the implicit last step**. Policies are registered by
the module that owns the subject kind (the invoices module registers `sales_line` policies).
The tables below are the **proposed defaults**, signed off with the accountant (§13,
decision 10).

**Sales document line: taxes** (`facet=tax, subject=sales_line`)

| Step | Role | Filter | Why |
|---|---|---|---|
| 1 | `line` | — | an explicit tax typed on the line wins |
| 2 | `contact` | `exemption_only` | an exempt customer (SEZ, overseas, a tax-exempt body) overrides the item's tax. Zoho applies a contact's exemption over the item preference |
| 3 | `item` | — | the item's intra/inter preference (`item_tax_preferences`) |
| 4 | `item_category` (expander) | — | the category's taxes (`category_tax_preferences`, already synced) |
| 5 | `contact` | `taxes_only` | the contact's default tax (`contact.tax_id`) |
| — | organization default | | `org_default_tax_preferences` for the specification |

**Sales document line: income account** (`facet=account, ctx.purpose=sales`)

| Step | Role | Why |
|---|---|---|
| 1 | `line` | explicit |
| 2 | `item` | Zoho item `account_id` |
| 3 | `item_category` | a category-level income account (local, optional) |
| 4 | `contact` | a customer-specific income account (local, rare) |
| — | organization `sales` | |

**Purchase line: expense / COGS account** (`purpose=purchase`): `line → item →
item_category → contact (vendor) → organization`.

**Inventory account** (`purpose=inventory_asset`): `item → item_category → organization`.

**Document header: control account** (`subject=sales_document, purpose=receivable`):
`contact → organization`. **Payable** is the same with `purpose=payable`.

**Tax posting accounts** (`subject=tax_line, purpose=output_tax|input_tax|tds_payable`):
`tax_component → organization`. This is how a resolved tax finds its ledger account.

### 7.6 The algorithm (`engine.resolve_many`)

```
resolve_many(db, facet, policy, subjects, ctx_of)                      # ctx may differ per subject
  1. owners  = ⋃ subject roles named by the policy
  2. owners += expanders(owners)          # one query per expander, batched
  3. cands   = facet.load(db, owners, …)  # ONE query
  4. dflt    = facet.organization_default(db, {s.organization_id}, …)   # ONE query
  5. per subject, per step (pure, in memory):
        rows = filter(cands[owner(step.role)])
        hit  = facet.select(rows, ctx)
        if hit and any(facet.unusable(h)):
            step.on_unusable == "fail"  → Resolution.error(unusable, owner, reason)
            step.on_unusable == "skip"  → trace, continue
        if hit → Resolution(value, via=step.role, owner=…)          # first step that answers wins
     fall through → organization default → else Resolution.none
```

**Cost:** a fixed number of statements for any number of subjects. That is 2 per facet,
plus 1 per expander used, regardless of the line count. The N+1 test asserts exactly that
(§12.3).

**Rules that make it safe:**
- **Fail closed on an unusable assignment** (`on_unusable="fail"` is the default). If an
  item's sales account was deactivated, falling silently to the organization default posts
  revenue to the wrong account. The caller gets `422 assigned_value_unusable` naming the
  owner, facet and reason. `skip` is opt-in per step, for genuinely optional layers.
- **Pending assignments never answer**, and the trace shows them as `pending`. A pending row
  means the source named something we have not synced. Resolving past it would hide that.
- **Determinism:** ties inside a step are broken by the facet's `select` (`position`, then
  `id`). Same inputs, same answer, every time.
- **No guessing:** nothing found anywhere → `Resolution.none`. The caller decides: a draft
  shows "unassigned", issuing a document raises `422 unresolved`. The engine never picks an
  account by type or name.

### 7.7 Context is the caller's, derived once

The engine does not compute context. The document module does, once per document:
- **Inter / intra:** `taxes.context.specification_for(org_state, place_of_supply)` compares
  the organization's GST state with the place of supply (Zoho `place_of_contact` /
  `place_of_supply`).
- **Transaction type:** from the document kind.
- **Currency:** from the document.

Keeping this outside the engine keeps it pure and testable, and it means GST rules evolve in
`taxes`, not in a generic layer.

### 7.8 Freezing and explainability

- **Drafts re-resolve**; **issued documents freeze**.
  - Taxes already have `freeze_owner` (snapshot + immutable row).
  - For accounts, the posted ledger line's `account_id` *is* the freeze.
- `explain=True` returns the trace: every step, its owner, and one of
  `no_candidates` / `filtered` / `pending` / `unusable:<reason>` / `answered`. It feeds
  `POST /api/resolution/{facet}?explain=true` and a "why this tax / account?" panel.
- An issued document may store its trace in `app_metadata` for audit (document module's
  choice).

### 7.9 Moving taxes onto the engine without breaking it

- `resolve_taxes(db, owners, …)` keeps its signature and becomes a thin wrapper.
  - It builds an ad-hoc policy from its `owners` list (one step per owner, in order) and
    calls `resolve_many` for one subject.
  - It maps the result back to `ResolvedTaxes(resolved_from, via, …)`.
- **The existing tax tests run unchanged, as the parity gate.**
- The only observable difference is the query count, which drops from one per owner to a
  constant.
- `categories` (the one current caller) then moves to a named policy at leisure.

### 7.10 What it is not

- **Not a rules engine.** No expressions, no scripting: steps, filters and facets are code
  reviewed in PRs.
- **Not a cache.** Assignments are small and indexed, and one page costs 2–4 indexed
  queries. Caching would add invalidation for no measured gain.
- **Not a writer.** Assignments are written only by each facet's service
  (`taxes.assignment_service.replace_assignments`,
  `accounting.assignment_service.put_assignments` / `sync_source_assignments`).

### 7.11 Pickers: "income accounts", "purchase accounts", "inventory accounts"

These are **views, not tables**: `GET /api/accounting/accounts?usage=sales|purchase|inventory`
lists live, active accounts whose type is `is_sales_eligible` / `is_purchase_eligible` /
`is_inventory_eligible`.
- Until the item-form list samples are vendored (decision 1), eligibility is seeded from the
  purposes: sales ← income group; purchase ← expense group + `fixed_asset` / `other_asset` /
  `other_current_asset`; inventory ← `stock`.

## 8. Integration: making an entity carry accounts

### 8.1 The recipe (Items and Contacts follow it, unchanged)

**1. Migration of the owning module**, after its table exists:

```python
from app.modules.accounting.registration import register_account_owner_type

register_account_owner_type(
    op.get_bind(), code="item", name="Item", target_schema="catalog", target_table="items",
    purposes={"sales": True, "purchase": True, "inventory_asset": True},   # value = falls_back_to_organization
)
```

It is idempotent and never overwrites (`ON CONFLICT DO NOTHING`, Core tables, not ORM). It:
- registers `core.entity_types` if absent;
- writes one `account_purpose_policies` row per purpose.

**2. Model:**

```python
class Item(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasTaxesMixin, HasAccountsMixin, SoftDeleteFilteredMixin, Base):
    __account_owner_type__ = "item"   # optional; default is the snake_case class name
```

**3. Zoho adapter of the owning module.** It declares account references through a hook,
because an assignment is a row, not an FK column on the owner:

```python
# items/zoho/hooks.py — post_upsert
await accounting.assignment_service.sync_source_assignments(
    db, owner=("item", item.id), source_system="zoho",
    refs={"sales": payload.get("account_id"),
          "purchase": payload.get("purchase_account_id"),
          "inventory_asset": payload.get("inventory_account_id")},
)
```

For each ref, `sync_source_assignments`:
- resolves the Zoho account ids through `crosswalk.resolve_many` (one query);
- upserts the Zoho-sourced slots;
- writes **pending** rows (`external_ref`) for ids not yet synced, queued on
  `sync.pending_references`;
- soft-deletes Zoho slots the payload no longer names.

This is the categories → `tax_assignments` path, applied to accounts.

**4. Outbound (Phase 6):** the owner's `to_zoho_payload` reads its Zoho-sourced and local
assignments and emits the three ids. That needs `zoho_id` on each referenced account; an
account without one makes the push refuse with the account named.

### 8.2 Contacts (customers and vendors): taxes **and** accounts

Zoho has one contact entity (`contact_type` customer / vendor), so we register one owner
class, `contact`.

**Registration**, in the contacts module's migration:
- `register_taxable_entity_type(code="contact", allows_exemption=True, …)`;
- `register_account_owner_type(code="contact", purposes={"receivable": True, "payable": True,
  "customer_advance": True, "vendor_advance": True, "sales": True, "purchase": True})`.

**From the Zoho contact payload** (`docs/zoho-docs-md/contact.md`), in the contacts adapter's
`post_upsert`:

| Zoho field | Becomes | Through |
|---|---|---|
| `tax_id` | a Zoho-sourced **tax assignment** on the contact (any context) | `taxes.assignment_service.replace_assignments(source_system="zoho")`; unknown id → **pending** + `sync.pending_references`, linked by the reconcile lane |
| `tax_exemption_id` | a Zoho-sourced **exemption assignment** | same |
| `tds_tax_id` | a tax assignment, `transaction_type="purchase"` | same. Whether Zoho's TDS id is a `tax_components` row or a separate TDS entity is **unverified** (decision 11); until verified it stays in the crosswalk raw only |
| `gst_treatment`, `place_of_contact`, `gst_no`, `tax_treatment`, `is_taxable` | **contact columns**, not assignments | they are *context inputs* (§7.7), not answers |
| `currency_id` | `contacts.currency_id` FK | `ReferenceRule(module="currencies")` |
| (no account fields in Zoho's contact API) | — | accounts on a contact are **local overrides** only |

**Accounts:**
- The normal retailer has **zero** account assignments and resolves `receivable` to the
  organization's AR control account (§7.5).
- Overrides are for exceptions: a key account with its own AR sub-ledger, or a customer
  whose sales post to a separate income account.
- Statements come from `counterparty_type='contact'` on ledger lines (Phase 3), not from
  per-contact GL accounts.

### 8.3 Zoho tax ids resolve to `app/modules/taxes`, Zoho account ids to `accounting`

A Zoho reference is never stored as an opaque id on a business row when its target module
exists. Every reference goes through the crosswalk and becomes a local FK or an assignment:

| Where the id appears | Target | How |
|---|---|---|
| item `tax_id`, `item_tax_preferences[]` | `tax.tax_components` | tax assignments on the item (`source_system="zoho"`), the categories pattern |
| category `category_tax_preferences[]` | `tax.tax_components` | **already built** (`categories/zoho/hooks.py`) |
| contact `tax_id`, `tax_exemption_id` | `tax.tax_components` / `tax.tax_exemptions` | §8.2 |
| item `account_id`, `purchase_account_id`, `inventory_account_id` | `accounting.accounts` | account assignments on the item (§8.1) |
| tax `tax_account_id`, `purchase_tax_account_id`, `tds_payable_account_id` | `accounting.accounts` | account assignments on the `tax_component` (§8.4) |
| any `currency_id` | `currency.currencies` | `ReferenceRule` |

One shared helper does the id → local resolution for all of them:
`sync.crosswalk.resolve_many`, one query per page. One shared lane does the "not synced yet"
case: `sync.pending_references` + `reconcile`. No module grows its own lookup.

### 8.4 Wired in Phase 1 (so the mechanism is proved before Items and Contacts exist)

- **`organization`**: every org-default purpose. `register_account_owner_type(code="organization",
  target_schema="org_management", target_table="organizations", …)`;
  `falls_back_to_organization = false`, because it *is* the end of the chain.
- **`tax_component`**: `output_tax`, `input_tax`, `tds_payable`.
  - `taxes/zoho/hooks.py` already receives `tax_account_id`, `purchase_tax_account_id` and
    `tds_payable_account_id`, stored today as opaque echoes.
  - It calls `accounting.assignment_service.sync_source_assignments` and they become real,
    per-organization account assignments (§5.6).
  - The echo columns are dropped one release after the live acceptance shows the
    assignments filled (§13, decision 8).
  - This is the dependency direction the import linter allows: `taxes` imports
    `accounting.assignment_service`, and `accounting` never imports `taxes`.
  - The `TaxFacet` registration lives in `taxes/resolution.py`.
- **The resolution engine** with `TaxFacet` (parity-wrapped `resolve_taxes`) and
  `AccountFacet`, plus the `tax_line` account policy. That is enough to answer "which
  account does this CGST post to in THPL?" end to end before any document module exists.

### 8.5 THPL organization defaults

After the first chart sync, `scripts/seed.py --only accounting.defaults` assigns THPL's
organization defaults **only where the chart makes them unambiguous**: exactly one live
account of the defining type.

| Purpose | Rule |
|---|---|
| `receivable` | the single live `accounts_receivable` account |
| `payable` | the single live `accounts_payable` account |
| `inventory_asset` | the single live `stock` account, else the account with `placeholder` = Zoho's inventory slug (sample-only, decision 1) |

- Everything else (`sales`, `purchase`, `cost_of_goods_sold`, `retained_earnings`,
  `round_off`, …) is **listed as unassigned** for an admin to set through
  `PUT /api/accounting/assignments/organization/{uuid}`.
- Picking by name ("Sales", "Retained Earnings") is exactly the guess §7.6 forbids.
- If the sample-only Zoho flags (`is_retained_earnings`, `is_accounts_receivable`, …) are
  confirmed in a real response, the sync hook writes those defaults as `source_system="zoho"`
  assignments, and the seed step only fills what is still empty.
- The step is idempotent and never overwrites an existing assignment.

## 9. Phases 2–3: the ledger, reconciled with v2

These phases are specified enough that Phase 1 does not box them in. The details are
settled when invoices and bills exist.

### 9.1 Phase 2: calendar and settings

- **`accounting.organization_accounting_settings`** (OrgEntityMixin, one live row per
  organization):
  - `books_start_date`, `transaction_lock_date`, `accounting_basis` (`accrual` / `cash`).
  - Not base currency or FY start month: those are `organizations.currency_id` and
    `organizations.fiscal_year_start_month` (Zoho-synced).
- **`accounting.fiscal_years`** and **`accounting.accounting_periods`** (OrgEntityMixin):
  - `[start_date, end_date]` is a closed `date` range.
  - `EXCLUDE USING gist (organization_id WITH =, daterange(start_date, end_date, '[]') WITH &&) WHERE (deleted_at IS NULL)`.
    This is race-free and uses `btree_gist`, which is already installed (§2.3 #2).
  - Status `open / soft_closed / closed / locked`.
  - A generator service creates the 12 periods from the FY start month.

### 9.2 Phase 3: journal entries and lines

Kept from v2 in meaning:
- `entry_origin` (`native` / `external_projection`);
- `draft → posted → voided`;
- reversal chain (`reversal_of_id`, one live reversal);
- the deferred balance trigger (native + posted: ≥ 2 lines, Σdebit = Σcredit);
- the posting trigger (period derivation, closed-period and lock-date refusal, `posted_at`,
  number assignment);
- header and line immutability once posted;
- one-sided lines (`debit = 0 OR credit = 0`);
- `counterparty_type` (FK `core.entity_types.code`) + `counterparty_id` (orphan query, no
  trigger: write cost on the hottest table);
- `exchange_rate`; line `description`;
- typed reporting dimensions (`reporting_dimensions`, `_values`,
  `journal_entry_line_dimensions`).

Changed from v2:

| v2 | Phase 3 |
|---|---|
| `tenant_id` filled by trigger; FKs to `public.*` | `OrgEntityMixin`; composite `(tenant_id, organization_id, x_id)` FKs |
| `journal_entry_lines` as an ENTITY with `row_version` | **LEDGER-shaped** (`LedgerMixin` + timestamps + explicit soft-delete columns for drafts only). Lines of a posted entry never change, so optimistic locking guards nothing. Conformance: no `row_version` → no ENTITY_COLUMNS requirement |
| `zoho_id` on lines | gone. Projected entries carry identity on the crosswalk (module `account_transactions`); a line's position is its identity within the entry |
| `external_id` (deprecated duplicate) | not created |
| guard allow-list without `description` | allow-list is exactly the P2 columns (`counterparty_name`, `description`), and only under the erasure GUC (§2.3 #3) |
| `account_period_balances` refreshed by function | same, plus a Celery task per organization after posting batches. Hash-guarded: an unchanged refresh writes nothing |

### 9.3 Numbering

`accounting.document_sequences` (OrgEntityMixin) + `accounting.next_document_number()`
(row lock, gap-free within the transaction, rolls back with the caller).
- **Stated property:** it serializes posting per (organization, key, fiscal year).
- Numbering is a platform concern: invoices, bills and receipts will want it too. If a second
  module needs it before Phase 3 lands, it moves to `core.number_series` with the same
  function, not into a copy.

### 9.4 Ledger audit trail: the one place a trigger audit is justified

- The `activity` recorder is explicit, so a bulk SQL fix or a migration writes no audit entry.
- For master data that is acceptable.
- For the books it is not: the Companies (Accounts) Rules require accounting software to keep
  an edit-log audit trail that cannot be disabled (the 2021 amendment, applicable from FY
  2023-24). **Verify the exact obligation with the auditor** (§13, decision 7).
- Phase 3 therefore keeps v2's trigger-written `accounting.audit_events`:
  - **only** for `journal_entries`, `journal_entry_lines`, `fiscal_years`,
    `accounting_periods`, `organization_accounting_settings` and `account_assignments` with
    `owner_type_code='organization'`;
  - LEDGER-shaped (`LedgerMixin`);
  - append-only by trigger;
  - erasure path behind a transaction-local GUC.
- **This is a deliberate second audit path, flagged as such.** The rule for choosing it: a
  statute requires the log to be complete regardless of the writer.
- `accounting.accounts` changes are recorded by the activity recorder in Phase 1, and move
  under the trigger in Phase 3 only if the auditor says the chart is in scope.

### 9.5 Phase 4: Zoho transactions projection

`/chartofaccounts/transactions` returns **one leg per account** (v2 A-10, confirmed by the
documented response: `account_id`, `debit_or_credit`, `offset_account_name`). It can never
balance per account. The plan:
- Project `/journals` (documented, full lines) as balanced `external_projection` entries.
- Use account transactions for reconciliation and opening history only, under exempt headers.
- `transaction_type` (`invoice`, `customer_payment`, `bills`, …) maps through a codec onto
  `core.entity_types` codes. An unknown type quarantines the record.

---

## 10. Explicitly not in Phase 1, and where each goes

| Item | Decision |
|---|---|
| Bank P3 data (`bank_account_number_ciphertext`, `_bindex`, `bank_ifsc_code`, `bank_name`, `masked_account_no`) | Phase 5: `accounting.bank_account_details`, 1:1 with an account of type `bank` / `credit_card`, own RBAC permission, DPDP erasure. Never on `accounts` |
| Account `owner_type` / `owner_id` (v2 lens 2, "who owns this ledger account") | Not built. Assignments answer "which account does X use". "This account belongs exclusively to X" has no consumer, and the one plausible one (bank accounts) is the 1:1 table. Add `owner_*` with `PolymorphicOwnerMixin` the day a consumer exists; nothing in Phase 1 blocks it |
| `tax_kind` on accounts | Phase 4 tax-reporting work, with the accountant's vocabulary; until then the `output_tax` / `input_tax` assignments carry the meaning |
| Statutory (Schedule III) report mapping | Phase 3+: `statutory_report_lines` + map. `schedule_*_category` stays raw |
| Meilisearch index for accounts | Not needed: a few hundred rows per organization, trigram ILIKE. Revisit only if a cross-organization search appears |
| Debezium / ClickHouse | Not in Phase 1. Ledger lines (Phase 3) are the analytics candidate |
| `account_name` uniqueness | Not enforced (Zoho tolerates repeated child names) |
| Account merge (`superseded_by_id`) | When a merge feature is scheduled |
| RLS policies | Columns are ready platform-wide; RLS is a platform decision, not this module's |

---

## 11. API, schemas, RBAC

**Routes** (`app/router.py` includes `accounting.api` and `accounting.assignment_api`;
`tests/test_health.py` gets every path):

| Method | Path | Notes |
|---|---|---|
| GET | `/api/accounting/account-types` | GLOBAL list; cached in DB0 under `accounting:types` |
| GET | `/api/accounting/accounts` | **Slim**. `load_only(id, uuid, account_code, account_name, display_name, account_type, parent_id, depth, status, zoho_id)`. Filters: `group`, `type`, `usage`, `status`, `parent_uuid`, `q`, `include_deleted` (admin). `tree=true` returns a nested tree, built in Python from one query |
| GET | `/api/accounting/accounts/{uuid}` | **Fat**: type, parent (`joinedload`), currency, `has_children`, assignment count ("used by N"), tags/documents via `selectinload` |
| POST | `/api/accounting/accounts` | local create (decision 4) |
| PATCH | `/api/accounting/accounts/{uuid}` | owned-field guard; type rules (§5.3) |
| POST | `/api/accounting/accounts/{uuid}/activate`, `/deactivate` | |
| DELETE | `/api/accounting/accounts/{uuid}` | soft delete; refused by guard with reason |
| GET/PUT | `/api/accounting/assignments/{owner_type}/{owner_uuid}` | §7.2 |
| POST | `/api/resolution/{facet}` | **generic engine endpoint** (§7): `{policy, subjects: [{roles: {role: {type, uuid}}, context}], explain}` → one `Resolution` per subject, with trace when `explain=true`. `facet` ∈ registered facets (`tax`, `account`) |
| POST | `/api/accounting/resolve` | convenience: one owner chain + purposes → accounts (wraps the engine with the default policy) |

Owners are addressed by **UUID** in the API and translated to `owner_id` by the service
through `core.entity_types`. Internal ids never leave the process.

**Errors:**
- `AppError` subclasses with stable codes: `account_unresolved`, `zoho_owned_field`,
  `account_in_use`, `sub_account_not_allowed`, `parent_group_mismatch`,
  `purpose_not_allowed`, `account_group_not_allowed`.
- Organization resolution goes through `app/database/scope.py` (`422 organization_required`).

**RBAC catalogue** (`rbac/catalogue.py`, master-data block):

```python
*_p("accounting", "account", "create update delete manage", "chart of accounts"),
*_p("accounting", "assignment", "manage", "account assignments (organization defaults included)"),
```

Reads need an authenticated user in the organization, like taxes and categories. Writes are
judged at the target organization (`Target(organization_id=…)`). `templates.py` gives
`accounting.*` to the finance role template only. Organization-default assignments
(`owner_type='organization'`) require `accounting.assignment:manage` **and** `org` admin;
a sales rep must never re-point AR.

---

## 12. Migrations, wiring, tests

### 12.1 Alembic (one revision for Phase 1, `accounting_chart_of_accounts`)

1. Create the `accounting` schema and add it to `_OWNED_SCHEMAS`.
2. Tables in FK order: `account_types` → `accounts` → `account_purposes` →
   `account_purpose_policies` → `account_assignments`.
3. Functions and triggers (§5.3, §5.6). Constraint triggers are `DEFERRABLE INITIALLY DEFERRED`.
4. Seeds: account types (union), purposes.
5. `register_account_owner_type` for `organization` and `tax_component`, and
   `register_commentable_entity_type` + `core.entity_types` for `account` (so accounts take
   comments, tags, documents, custom fields).
6. Review autogenerate against the models: partial indexes' `postgresql_where`, `NULLS NOT
   DISTINCT`, the `Computed` column, composite FKs. Verify with the drift check used for
   fieldops (autogenerate clean on owned tables).
7. Downgrade drops in reverse. The schema is new, so a downgrade loses only this module's
   data, which is stated in the revision docstring.

Greenfield: no backfill. v1/v2 never ran against this database.

### 12.2 Wiring checklist

- `alembic/env.py` imports `app.modules.accounting.model` / `.assignment`, and
  `_OWNED_SCHEMAS += {"accounting"}`.
- `tests/test_tenancy.py` → `GLOBAL_TABLES` += `accounting.account_types`,
  `accounting.account_purposes` and `accounting.account_purpose_policies`, each with its
  reason.
- `tests/conftest.py` → `_TEST_TABLES` += `accounting.account_assignments` and
  `accounting.accounts` (FK-safe order). GLOBAL seeds are not truncated.
- `.importlinter`:
  - `accounting` layer below feature modules;
  - `resolution` imports no feature module;
  - `taxes` → `accounting` allowed, the reverse forbidden.
- Zoho registry `_ENTITY_PACKAGES` += `app.modules.accounting.zoho`. The resolution registry
  autodiscovers `taxes.resolution` and `accounting.resolution`.
- `zoho/sync/config.py`: `ModuleSyncConfig.strategy` default → `FULL` (§6.1).
  `tests/zoho_core` gets a test that every registered spec declares `strategy` explicitly,
  so the default can never again decide a real module's behaviour.
- Vendor `docs/zoho-docs-md/samples/accounts/account-types.json` (the response provided in
  review). It is the seed test's oracle.
- `scripts/seed.py`: new step `accounting.defaults` (§8.5), after `company`. Never run
  against the pytest database (memory: seeding vs test DB).
- `config/logging/modules/accounting.yaml` (`app.accounting`) and `resolution.yaml`
  (`app.resolution`).
- `deployment/.env` and `docker-compose.yml`: confirm `DEFAULT_TENANT_CODE` and
  `DEFAULT_ORGANIZATION_CODE` = THPL reach the containers (§6.4).

### 12.3 Tests

**Pure:**
- the translator: every §6.2 row, including blank → NULL, string booleans, the `+0530`
  offset, volatile keys out of the hash, and sample-only keys skipped when absent;
- the resolver's step order (decision table);
- the type-seed coverage test: every documented code is seeded with a group.

**Database (scratch PG):**
- normal-balance derivation per group and contra;
- depth on insert and the cascade on re-parent, including the `row_version` bump;
- a cycle is rejected;
- a cross-organization parent is impossible (composite FK);
- the blank code CHECK;
- the delete guard (children, assignments);
- assignment integrity: missing owner, owner in another organization, purpose not opted in,
  wrong group, `per_currency` rule;
- the slot uniqueness with a NULL currency;
- pending → linked through the reconcile lane;
- `find_orphan_account_assignments` reports a deleted owner;
- the tenancy conformance test passes.

**Sync** (`FakeZohoClient`):
- list + detail apply;
- a child arriving before its parent → pending → reconcile links → depth correct;
- unchanged rescan writes nothing (no `row_version` bump, no payload row);
- an unknown `account_type` fails one record, not the page;
- a Zoho-owned field PATCH → 422;
- tombstone on a weekly full with the delete guard honoured.

**Resolution engine** (pure + DB):
- every step type: line wins, contact exemption beats item, category expander, contact
  default, organization default;
- `on_unusable` fail vs skip;
- pending never answers;
- deterministic ties;
- trace content;
- a policy naming an unknown role or expander fails registration;
- tax-component accounts resolve per organization (one component, two organizations, two
  accounts).

**Tax parity:** the existing `resolve_taxes` tests pass unchanged on the engine.

**Seed:** all 46 codes present; the 26 tenant-observed rows match the vendored response
field by field; every code has a group and normal side.

**N+1:** constant query count on `GET /accounts`, and on `resolve_many` for 1, 50 and 500
subjects across 2 facets. Exactly 2 statements per facet + 1 per expander, asserted.

**API:** route smoke; RBAC (a branch admin cannot set another organization's defaults);
Slim list uses `load_only` (assert the selected columns).

**Live acceptance (dev stack, real Zoho):**
- full sync of THPL's chart;
- `find_chart_violations` empty or explained;
- tax components show `output_tax` / `input_tax` assignments;
- a re-run reports all-`unchanged`.

### 12.4 Docs updated with the code

`docs/MODULES.md`, `docs/PROJECT_STRUCTURE.md`, `docs/SYNC_ARCHITECTURE.md` (module list),
`docs/zoho-sync-implementation/adapters/chart-of-accounts.md` (new, the categories adapter
doc's shape), `docs/rbac-module.md` (new permissions), this plan's status.

---

## 13. Open decisions

| # | Decision | Status / recommendation |
|---|---|---|
| 1 | Vendor the remaining samples (chart list, single account, income/purchase/inventory lists) | **Open.** The account-types response is in hand (§5.1). The lists only refine picker eligibility (§7.11) and the `placeholder`-based defaults (§8.5) |
| 2 | Trust `last_modified_time` | **Decided: trusted.** Declared; INCREMENTAL is a runtime override, FULL is the default (§6.1) |
| 3 | `account_code` unique per organization | Check THPL's chart before shipping `uq_accounts_code`. If Zoho tolerates duplicates, drop the index, never the data |
| 4 | Local creation in a Zoho-connected organization before Phase 6 | Refuse (`422 zoho_mastered_chart`) (§6.3) |
| 5 | Purpose → allowed groups; contingent types; OCI close | Accountant sign-off |
| 6 | Contact-level account overrides | Allow (opt-in); default every contact to the control account |
| 7 | Ledger audit-trail obligation and the chart's scope | Ask the auditor before Phase 3 |
| 8 | Drop `tax_components.*_account_id` echoes | One release after the assignments are proven live |
| 9 | `document_sequences` here or `core.number_series` | Here for Phase 3; move when a second module needs numbering |
| 10 | The default resolution policies (§7.5), especially "contact exemption beats item tax" and "item beats contact for the income account" | Accountant sign-off. Policies are data, so changing one is a PR, not a redesign |
| 11 | Contact `tds_tax_id`: a `tax_components` row or a separate TDS entity in Zoho | Capture one real contact with TDS before mapping it |
| 12 | Tenant and organization defaults | **Decided: THPL** from `backend/.env`; ensure `deployment/.env` matches (§6.4) |
| 13 | Platform `ModuleSyncConfig.strategy` default → FULL | **Decided** (§6.1); safe because all 9 modules declare their strategy |

## Appendix A: where every v1/v2 table went

| v1/v2 table | Outcome |
|---|---|
| `accounting.account_types` | **kept**, GLOBAL, vocabulary corrected (§5.1); `zoho_id` kept (Zoho numeric type id), all 46 types seeded; + eligibility flags, `is_documented`, `is_enabled` |
| `accounting.inventory_valuation_methods` | **moved to the inventory/items module**: a valuation method is a property of stock costing, not of the chart. The five account columns of `organization_inventory_preferences` become organization assignments (`inventory_asset`, `cost_of_goods_sold`, `inventory_adjustment`, `goods_in_transit`, `price_variance`) |
| `accounting.organization_inventory_preferences` | split as above; the valuation choice goes to the inventory module's settings |
| `accounting.accounts` | **kept**, reconciled (§5.2) |
| `accounting.account_external_identities` | → `sync.sync_records` |
| `accounting.journal_entry_lines` | Phase 3, LEDGER-shaped (§9.2) |
| `polymorphic_type_registry` | → `core.entity_types` + `account_purpose_policies` |
| `account_roles`, `account_role_assignments` | → `account_purposes` + organization `account_assignments` |
| `currencies`, `exchange_rates` | → `currency.currencies`, `currency.exchange_rates` |
| `fiscal_years`, `accounting_periods` | Phase 2, EXCLUDE instead of the overlap trigger |
| `organization_accounting_settings` | Phase 2, minus base currency and FY month (on organizations) |
| `journal_entries`, `reporting_dimensions*`, `journal_entry_line_dimensions` | Phase 3 |
| `journal_entry_external_identities`, `external_entity_type_map` | → crosswalk + codec (Phase 4) |
| `account_period_balances`, `document_sequences` | Phase 3 |
| `audit_events` | Phase 3, ledger tables only (§9.4) |

## Appendix B: where every `accounts` column went

- **Kept as columns:** `id`, `uuid` (uuidv7), `organization_id`, `account_code`,
  `account_name`, `description`, `is_system_account`, `is_custom_account`
  (→ `is_user_created`), `is_expense_claim_enabled`, `show_on_dashboard`, `placeholder`,
  `normal_balance_is_debit` (derived), `depth` (derived), `status`, `row_version`,
  `content_hash`, the verification six (`VerificationMixin`; `verified_by_id` →
  `verified_by`), `tenant_id`, `is_contra_account` (→ `is_contra`), `app_version`,
  `app_metadata`, the audit and soft-delete columns (mixin names).
- **Renamed:**
  - `account_type_id` → `account_type`, an FK by code;
  - `parent_account_id` → `parent_id`;
  - `account_display_name` → `display_name`;
  - `currency_code` → `currency_id`, an FK to `currency.currencies`; NULL = base.
- **Echo:** `zoho_id` (engine-maintained).
- **Derived in queries:** `has_children`, `is_involved_in_transaction`.
- **To assignments:**
  - `is_retained_earnings`, `is_accounts_payable`, `is_accounts_receivable`,
    `is_fx_gain_loss`, `is_default`, `is_default_purchase_discount`, `is_primary_account`:
    organization assignments;
  - `is_purchase_account`, `is_sales_account`, `is_inventory_account`: type eligibility
    (§7.11);
  - `is_tax_account`, `disable_tax`: tax-component assignments / the tax module.
- **Raw only until a consumer exists:** `price_precision`, `ignore_currency`,
  `allow_multi_currency`, `icon`, `account_hint`, `is_standalone`, `balance_sheet_category`,
  `pnl_category`, `is_header_only`, `is_system_reserved`, `supports_check_register`,
  `is_expense_payment_source`, `is_transaction_locked`.
  - `is_header_only` and `is_transaction_locked` return as columns in Phase 3, when the
    posting guard needs them.
  - Adding any of these is a nullable column plus a field-map line, never a redesign.
- **Removed:**
  - `balance_cache`, `balance_as_of` → `account_period_balances` (Phase 3);
  - `custom_fields` JSONB → crosswalk + `extfields`;
  - `owner_type`, `owner_id`, `owner_kind`, `origin`, `tax_kind` → §10;
  - bank columns → Phase 5.
