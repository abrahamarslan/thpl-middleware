# Accounts module: Chart of Accounts, account assignments, and the path to a ledger

**Status:** proposed, not built yet · **Owner:** backend / platform data
**Schema:** `accounting` · **Package:** `app/modules/accounting/` · **Postgres:** 18
**Inputs reconciled:** the v1 `accounts_module.sql`, the v2 audit (`accounts_module_v2.sql`,
`accounts_module_validation.sql` and their report), Zoho Books `/chartofaccounts`
(vendored: `docs/zoho-docs-md/chart-of-accounts.md`), and the codebase as it stands today.
**Related:** [`sync-crosswalk-redesign.md`](sync-crosswalk-redesign.md) ·
[`sync-crosswalk-delta-v3.md`](sync-crosswalk-delta-v3.md) ·
[`tax-assignments.md`](tax-assignments.md) (the pattern this module copies) ·
`docs/tenancy/README.md` · `docs/architecture-prompts/master-prompt.md`

---

## 0. Summary

1. **The v2 schema is a good ledger design, but it was written for a database we do not
   have.** It rebuilds about a third of the platform under new names: tenancy
   (`public.organizations` + a tenant-fill trigger), audit columns, a polymorphic
   registry, currencies and exchange rates, Zoho identity (`account_external_identities`),
   row versioning and an audit log. Each of those already exists here and is enforced by
   conformance tests. **We keep v2's accounting rules and replace its infrastructure with
   ours** (§2).
2. **Build it in phases, starting with what has consumers today.** Phase 1 builds:
   - the **Chart of Accounts** (`accounting.account_types` and `accounting.accounts`);
   - **account assignments**, so any entity can say "use this account for this purpose"
     (`accounting.account_assignments` + `HasAccountsMixin`);
   - the **Zoho sync** of `/chartofaccounts`.

   The general ledger (journal entries, periods, posting rules, balances) comes in Phases 2
   and 3. Nothing writes ledger entries yet (no invoices, bills or payments module), and a
   balance trigger with no writer is speculative surface area (master prompt, directive 7).
3. **"Customers and Items can have accounts" means assignments, not more accounts.**
   - An item's sales, purchase and inventory accounts (Zoho: `account_id`,
     `purchase_account_id`, `inventory_account_id`) are three assignment rows.
   - A customer's receivable account is an optional override of the organization's AR
     control account.
   - There is **never one GL account per retailer.** At thousands of retailers that is the
     classic chart-of-accounts explosion; the counterparty belongs on the ledger line
     (v2 R15-10, agreed).
4. **One mechanism replaces three of v2's.** Organization-level defaults (v2's
   `account_roles` + `account_role_assignments`, the five account columns on
   `organization_inventory_preferences`, and the `is_retained_earnings` /
   `is_accounts_receivable` / … singleton flags) become **assignments whose owner is the
   organization.** "Which account applies here?" then has one resolver with one fallback
   chain: owner → organization (§7).
5. **Organization-scoped throughout** (`OrgEntityMixin`: `tenant_id` and `organization_id`
   NOT NULL, composite FK to the organization). Zoho account ids belong to a Zoho
   organization, and so do our rows.
6. **Findings that change the design** (§2.3):
   - v2's account-type seed and Zoho's documented vocabulary disagree; the type table must
     be their union.
   - v2's overlap trigger for fiscal periods is race-prone. `btree_gist` is *already
     installed* (the geo migration installed it), so we use a real `EXCLUDE` constraint.
   - v2's immutability guard contradicts its own erasure rule.
   - v2's `balance_cache` on the account row would rewrite the row on every sync.
   - The organization row already carries the base currency and the fiscal-year start month.

---

## 1. Understanding

**Asked:** implement Chart of Accounts, income/purchase/inventory accounts, etc., as an
organization-scoped module that Customers and Items (and later other entities) can carry
accounts from, integrated with the existing mixins and the sync crosswalk.

**Read for this plan:**

- `app/database/mixins.py`: the table classes ENTITY / LEDGER / GLOBAL, and
  `OrgEntityMixin`, `VerificationMixin`, `HashGuardMixin`.
- The four "Has…Mixin" precedents: `tags`, `comments`, `documents`, and
  `taxes/mixins.py` + `taxes/assignment.py` + `taxes/registration.py`.
- `zoho/sync/mixins.py`: deprecated for new modules; the crosswalk replaces it.
- The sync contract (`sync/contract.py`) and the categories/taxes adapters.
- `core.entity_types` and `core.assert_entity_exists()`.
- `currency.currencies`, and `org_management.organizations` (which has `currency_id` and
  `fiscal_year_start_month`).
- The tenancy conformance test (`tests/test_tenancy.py`), `_OWNED_SCHEMAS` in
  `alembic/env.py`, and the RBAC catalogue.

**Not in the repo, needed before Phase 1 is coded.** The six JSON samples the v2 report was
built from (`account-types.json`, `accounts-list.json`, `account-single.json`,
`accounts-single-2.json`, the purchase/income/inventory lists) are not vendored. They show
fields the documented API does not have, such as `account_type_int`, `placeholder`,
`is_user_created`, the role flags and `price_precision`. Per the guardrails, a payload shape
we only have second-hand is not one to build on, so **vendor them under
`docs/zoho-docs-md/samples/accounts/` first** (§13, decision 1). The mapping in §6 marks
every field as *documented* or *sample-only*.

---

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

## 3. Phases

| # | Phase | Delivers | Unblocks |
|---|---|---|---|
| **1** | **Chart of Accounts** | `account_types`, `accounts`, `account_purposes`, `account_purpose_policies`, `account_assignments`; `HasAccountsMixin`; registration helper; resolver; `/chartofaccounts` sync (INBOUND); API; organization defaults + tax-component accounts wired | Items and Customers modules can declare accounts on day one |
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
unique index (the same reason given in `tax.taxable_entity_types`). A type is retired with
`is_enabled = false`. It is listed in `GLOBAL_TABLES` with the reason "Zoho/IFRS account-type
vocabulary, identical for every tenant — reference data like countries".

| Column | Type | Null | Notes |
|---|---|---|---|
| `code` | `String(64)` | NO | **UNIQUE (non-partial)**, the FK target. Zoho's `account_type` string (`cost_of_goods_sold`) |
| `name` | `Text` | NO | `Cost Of Goods Sold` |
| `account_group` | `String(16)` | NO | CHECK `asset / liability / equity / income / expense` |
| `default_normal_balance_is_debit` | `Boolean` | NO | asset/expense → true; liability/equity/income → false. Stored, not inferred, so an odd type can override its group |
| `is_sub_account_allowed` | `Boolean` | NO | default true; `bank`, `credit_card`, `payment_clearing`, … false |
| `can_show_opening_balance` | `Boolean` | NO | |
| `is_sales_eligible` / `is_purchase_eligible` / `is_inventory_eligible` | `Boolean` | NO | which pickers list it (§7.4). Replaces v1's per-account `is_sales_account` / … flags |
| `asset_type` | `String(32)` | YES | `fixed_asset`, `cwip`, `iaud` (sample-only vocabulary) |
| `zoho_type_int` | `SmallInteger` | YES | `account_type_int` (`'1'..'112'`) from samples; a vendor-wide constant, partial unique |
| `is_documented` | `Boolean` | NO | true = in Zoho's documented list; false = observed only in samples. Tells an operator which rows are evidence-backed |
| `is_enabled` | `Boolean` | NO | default true |
| `sort_order` | `SmallInteger` | YES | |
| `description` | `Text` | YES | |

**Seed:** the union of the 38 documented codes and the 8 sample-only codes (§2.3 #1), each
with its group and normal side.
- Groups for the documented-only codes are by name (`*_asset` → asset, `*_liability` →
  liability, `*_income` → income, `*_expense` → expense).
- `contingent_asset` / `contingent_liability` are off-balance-sheet in most frameworks; they
  are seeded with their nominal group and **flagged for accountant review** (§13, decision 5).

**Unknown code from Zoho:** `accounts.account_type` is an FK to `code`, so the record's
insert fails with an FK violation. The engine records it per record (`zoho_sync_events`,
one record only, never the page), the account is missing from the replica, and an operator
adds the seed row. This is deliberate: a guessed group would derive a wrong normal balance
and corrupt every report built on it.

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
| `zoho_id` | `String(50)` | YES | **engine-maintained echo** of `account_id` (`identity_echo`), never written by hand |

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
`tax.tax_assignments` with accounts in place of taxes.

| Column | Notes |
|---|---|
| `owner_type_code` `String(64)` NOT NULL | |
| `owner_id` `BigInteger` NOT NULL | no FK (polymorphic); proved at COMMIT |
| `purpose_code` `String(48)` NOT NULL | |
| composite FK `(owner_type_code, purpose_code)` → `account_purpose_policies (entity_type_code, purpose_code)` | the class is registered **and** opted in to this purpose, in the database |
| `account_id` `BigInteger` NULL | composite FK `(tenant_id, organization_id, account_id)` → `accounts`: same organization, structurally |
| `currency_id` `BigInteger` NULL | composite tenant FK → `currency.currencies`; NULL = any / base. Only meaningful when `purpose.per_currency` |
| `external_ref` `Text` NULL, `source_system` `String(32)` NULL | **pending** link: a source named an account we have not synced yet (an item synced before the chart). The reconcile lane links it |
| CHECK `account_id IS NOT NULL OR (external_ref IS NOT NULL AND source_system IS NOT NULL)` | |
| `uq_account_assignments_slot` on `(owner_type_code, owner_id, purpose_code, currency_id)` **NULLS NOT DISTINCT**, live | one account per slot. This replaces v2's singleton indexes: "one retained-earnings account" is the slot `(organization, X, retained_earnings, NULL)` |
| `ix_account_assignments_owner` on `(owner_type_code, owner_id)`, live | the read path |
| `ix_account_assignments_account` on `(account_id)`, live and not null | impact analysis ("who uses this account?") + the delete guard |

**`accounting.check_account_assignment_integrity()`** is a deferred constraint trigger, the
same shape as `tax.check_tax_assignment_integrity()`. It checks that:
1. the owner exists: `core.assert_entity_exists(owner_type_code, owner_id)`;
2. the owner is in the **same tenant and organization** as the row;
3. the policy row is enabled;
4. the account's group ∈ `purpose.allowed_groups` (and its type ∈ `allowed_types` when set);
5. `currency_id` is NULL unless `purpose.per_currency`.

`accounting.find_orphan_account_assignments()` is the scheduled safety net, run in the
reconcile lane.

**`source_system`:**
- `NULL` = maintained locally.
- `'zoho'` = fed by a sync (an item's accounts). Read-only through the API, exactly like
  `tax_assignments`.

---

## 6. Zoho sync: `chart_of_accounts`

### 6.1 Module config

```python
CHART_OF_ACCOUNTS_CONFIG = resolve_module_config(
    module="chart_of_accounts",
    endpoint="/chartofaccounts",
    zoho_id_attr="account_id",
    strategy=SyncStrategyName.INCREMENTAL,     # list documents a last_modified_time filter
    modified_since_param="last_modified_time",
    sort_column=None,                          # only account_name / account_type are sortable; neither is time-ordered
    direction=SyncDirection.INBOUND,           # Zoho masters the chart (Phase 6 adds outbound)
    detail_required=True,
    detail_dispatch="inline",
    index_then_detail=True,
    sync_interval_minutes=1440,
    weekly_full_enabled=True,                  # the only lane that can see a delete
    field_map=CHART_OF_ACCOUNTS_FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table="accounting.accounts",
        crosswalk=True,
        identity_echo=("zoho_id",),
        match_on=("zoho_id",),                 # re-adoption only (categories precedent), never a business-key merge
        history_raw=True,                      # a master: keep every document
        capture_custom_fields=True,
        owned_fields=ZOHO_OWNED_ACCOUNT_FIELDS, # = frozenset(TRANSLATOR.readable)
        references=(
            ReferenceRule(attr="currency_id", module="currencies", fk="currency_id",
                          on_missing=OnMissing.DEFER),
        ),
    ),
)
```

Why each choice:

- **INCREMENTAL, unsorted.**
  - The list takes `last_modified_time`, and each row carries one.
  - Zoho can only sort by `account_name` or `account_type`, so the engine must not advance a
    page-by-page watermark. This is the categories reasoning, which also left `sort_column`
    as `None`.
  - Confirm the filter's semantics on the live tenant before trusting it (decision 2).
    Until confirmed, run FULL; the apply gate makes an unchanged chart nearly free.
- **`index_then_detail` + inline detail.**
  - The list row lacks `currency_id`, `description`, `custom_fields` and
    `include_in_vat_return`.
  - Writing the index row first means an item referencing the account resolves the moment
    the account is listed.
  - First sync: one detail call per account. A few hundred calls at ~90/min is a few minutes,
    once. After that the gate spends calls only on changed accounts.
- **Never `showbalance=true`.**
  - `current_balance` changes without the account changing. In the raw hash it would make
    every scan a write.
  - It is also listed in the translator's volatile keys, in case Zoho ever returns it
    unasked.
- **`match_on=("zoho_id",)`, never `account_name`.**
  - Zoho allows identical names in different branches of the tree
    (`Cash Ledger : Interest`).
  - A name match would merge two ledgers, and that is unrecoverable once lines post to them.
- **Parent: a hook, not a `ReferenceRule`.**
  - A child usually arrives in the same page as its parent. A page-level rule resolves
    before the page is written, so it would defer every such child.
  - `post_upsert` resolves `parent_account_id` through `crosswalk.resolve_many` and queues
    what it cannot resolve on `sync.pending_references` (`waiting_table =
    "accounting.accounts"`, `waiting_column = "parent_id"`).
  - The reconcile lane links it with a bare UPDATE. The §5.3 triggers then recompute
    `depth` and `row_version` for the moved subtree.
  - This is the categories pattern, copied, not re-invented.
- **Currency: `DEFER`.** An account whose currency is not synced keeps `currency_id = NULL`
  (base currency) until the reconcile lane links it. It is never a stub currency.
- **Organization.** The connection's organization (delta-v3 §2.1). Every row lands in the
  organization whose node carries `ZOHO_ORGANIZATION_ID`.
- **Planner ordering.** `chart_of_accounts` depends on `organizations` and `currencies`.
  Until delta-v3 §6.2 (the `depends_on` DAG) is built, the reconcile lane makes either
  order converge. Register `depends_on` the day the planner supports it.

### 6.2 Field map

Legend: **D** = documented, **S** = sample-only (applied only when present: a key the source
did not send is skipped, never decoded to NULL).

| Zoho | → local | Dir | Codec / note | |
|---|---|---|---|---|
| `account_id` | crosswalk `external_id` + `zoho_id` echo | IN | string, never numeric (18-digit ids exceed 2^53) | D |
| `account_name` | `account_name` | BOTH | | D |
| `account_code` | `account_code` | BOTH | `blank_to_null` | D |
| `account_type` | `account_type` | BOTH | identity on the code. Unknown → FK failure per record (§5.1) | D |
| `account_type_int` | — | IN | **not on the account**; it is a type constant. Cross-checked against `account_types.zoho_type_int` and a warning logged on mismatch | S |
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
  field on a Zoho-linked row (`zoho_id IS NOT NULL`) gets **422
  `zoho_owned_field`**, the `categories/service._guard_zoho_owned` precedent. The next sync
  would revert the edit anyway.
- Local-only accounts are allowed (`zoho_id IS NULL`), but they are **not pushable** until
  Phase 6. **Decision 4 (§13):** for a Zoho-connected organization, either refuse local
  creation outright, or allow it with a "local-only" badge. The recommendation is to refuse:
  an item that references a local-only account cannot be pushed to Zoho, and that failure
  would surface far from its cause.
- `to_zoho_payload()` (create/update) is written in Phase 1 as the seam the outbox will call.
  - Required-on-create rules are checked locally, with the field named, before an API call
    is spent.
  - Zoho marks every create argument "Optional", but `account_name` and `account_type` are
    plainly required, so the translator's CREATE intent requires them.

---

## 7. Assignments and resolution: "which account applies here?"

### 7.1 Read

`HasAccountsMixin` gives `Model.account_assignments`: viewonly, `lazy="raise_on_sql"`, read
with `selectinload(Model.account_assignments).joinedload(AccountAssignment.account)`. That is
one extra query per result set, never N+1.

### 7.2 Write

`PUT /api/accounting/assignments/{owner_type}/{owner_uuid}` with
`[{purpose, account_uuid, currency_code?}]`:
- It replaces the owner's locally-maintained assignments in one transaction (soft-deletes
  dropped slots).
- It refuses to touch `source_system='zoho'` rows.
- It pre-flights every rule the trigger enforces, so the user gets a named 422 instead of a
  constraint error at COMMIT.

### 7.3 Resolve

`assignment_service.resolve_accounts(db, refs, purposes, currency_id=None)` is **batched**:
an invoice page resolving 200 lines × 3 purposes is one query.

For each `(owner, purpose)` it returns `ResolvedAccount(account, source)` and tries, in
order:

| Step | Looks for | `source` |
|---|---|---|
| 1 | the owner's assignment in the exact currency | `owner` |
| 2 | the owner's assignment with `currency_id NULL` | `owner` |
| 3 | if the policy `falls_back_to_organization`: the organization's assignment, same two steps | `organization` |
| 4 | nothing found | `None` |

On step 4 the caller decides: an invoice raises 422 `account_unresolved` naming the owner and
purpose, while a report shows "unassigned". The resolver never invents an account by type or
name.

It is one SQL statement. The candidates are a `VALUES` list unioned with the organization
rows, ranked with `row_number()` over (owner, purpose) ordered by step. It is the tax
resolver's shape, with the step order as data.

### 7.4 Pickers: "income accounts", "purchase accounts", "inventory accounts"

These are **views, not tables**:

`GET /api/accounting/accounts?usage=sales|purchase|inventory` lists live, active accounts
whose type has `is_sales_eligible` / `is_purchase_eligible` / `is_inventory_eligible`. The
eligibility flags are seeded from Zoho's item-form lists (the purchase/income/inventory list
samples). Until those are vendored, the flags follow `purpose.allowed_groups` (§13,
decision 1).

---

## 8. Integration: making an entity carry accounts

### 8.1 The recipe (Items and Customers follow it, unchanged)

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

### 8.2 Customers specifically

Zoho's documented contact API carries **no account fields**. Customer accounts are therefore
local data:
- an optional `receivable` override (a key account with a dedicated AR sub-ledger);
- `customer_advance`;
- an optional `sales` default for that customer's invoices.

Everything else falls back to the organization. With thousands of retailers, the normal
customer has **zero** assignments and uses the AR control account. Their statement comes from
`counterparty_type='customer', counterparty_id=…` on the ledger lines (Phase 3).

### 8.3 Wired in Phase 1 (so the mechanism is proved before Items exist)

- **`organization`**: every org-default purpose (`falls_back_to_organization = false`, since
  it is the end of the chain). `register_account_owner_type(code="organization",
  target_schema="org_management", target_table="organizations", …)`.
- **`tax_component`**: `output_tax`, `input_tax`, `tds_payable`.
  - `taxes/zoho/hooks.py` already has the account ids. They are opaque echoes today
    (`tax_account_id`, `purchase_tax_account_id`, `tds_payable_account_id`).
  - They become Zoho-sourced assignments, which gives tax components real account links.
  - The echo columns stay until a release has shown the assignments filled. Then they are
    dropped in a follow-up (§11).

---

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
| POST | `/api/accounting/resolve` | batch: `[{owner_type, owner_uuid, purpose, currency_code?}]` → resolved accounts with `source` |

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

- `alembic/env.py` imports `app.modules.accounting.model` / `.assignment`.
- `tests/test_tenancy.py` → `GLOBAL_TABLES` += `accounting.account_types`,
  `accounting.account_purposes`, `accounting.account_purpose_policies`, each with its reason.
- `tests/conftest.py` → `_TEST_TABLES` += `accounting.account_assignments`,
  `accounting.accounts` (FK-safe order). GLOBAL seeds are not truncated.
- `.importlinter` adds the `accounting` layer (§4).
- The Zoho registry's `_ENTITY_PACKAGES` gains `app.modules.accounting.zoho`.
- `config/logging/modules/accounting.yaml` declares namespace `app.accounting`.

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

**N+1:** query count on `GET /accounts` (constant) and on a 50-owner
`resolve_accounts` (one statement).

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

| # | Decision | Recommendation |
|---|---|---|
| 1 | Vendor the six JSON samples (`docs/zoho-docs-md/samples/accounts/`) | **Required before coding §6.** Sample-only fields and the picker eligibility flags rest on them |
| 2 | Trust `last_modified_time` on `/chartofaccounts` for INCREMENTAL | Probe once on the live tenant (edit one account, list with the filter); until then FULL daily |
| 3 | `account_code` unique per organization | Check THPL's chart (`GROUP BY account_code HAVING count(*) > 1`) before shipping `uq_accounts_code`; if Zoho tolerates duplicates, drop the index, never the data |
| 4 | Local account creation in a Zoho-connected organization before Phase 6 | Refuse (422 `zoho_mastered_chart`); allow for organizations without a Zoho connection |
| 5 | Purpose → allowed groups/types seed; the group of `contingent_*` and other documented-only types | Accountant sign-off on both tables before release |
| 6 | Customer-level account overrides at all, or organization control accounts only | Allow the override (cheap, opt-in); default every customer to the control account |
| 7 | Ledger audit trail obligation (Companies (Accounts) Rules, audit-trail amendment) and whether the chart of accounts is in its scope | Ask the auditor before Phase 3; the design supports either answer |
| 8 | Drop `tax_components.*_account_id` echoes once assignments are proven | Yes, one release after the live acceptance shows them populated |
| 9 | `document_sequences` here or `core.number_series` | Here for Phase 3; move it the day a second module needs numbering |

---

## Appendix A: where every v1/v2 table went

| v1/v2 table | Outcome |
|---|---|
| `accounting.account_types` | **kept**, GLOBAL, vocabulary corrected (§5.1); `zoho_id` → `zoho_type_int`; + eligibility flags, `is_documented`, `is_enabled` |
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
    (§7.4);
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
