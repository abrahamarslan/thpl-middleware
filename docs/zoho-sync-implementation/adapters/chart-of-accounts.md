# Adapter: `chart_of_accounts` — Zoho Books `/chartofaccounts` → `accounting.accounts`

**Package:** `app/modules/accounting/zoho/` · **Migration:** `20261008_0700_e4c737170f12`
**Design:** [`docs/implementation-plan/accounts-module.md`](../../implementation-plan/accounts-module.md)
**Vendored API doc:** `docs/zoho-docs-md/chart-of-accounts.md` · **Tenant sample:**
`docs/zoho-docs-md/samples/accounts/account-types.json`

## Contract

| | |
|---|---|
| Endpoint | `GET /chartofaccounts` (paginated, `page_context`), detail `GET /chartofaccounts/{account_id}` |
| Identity | crosswalk `sync.sync_records` (module `chart_of_accounts`, `external_id` = `account_id`) + engine-maintained `zoho_id` echo |
| Strategy | **FULL** (default). `modified_since_param="last_modified_time"` is declared and trusted: INCREMENTAL is a control-plane override `{"strategy": "incremental", "weekly_full_enabled": true}` — no deploy |
| Detail | **off by default** (list-only). The documented list example is thin, but the LIVE list row carries `currency_id`, `currency_code`, `description`, `placeholder`, `show_on_dashboard`, `is_user_created`, `parent_account_id` (verified 2026-10-08). Detail costs one request per account against Zoho's documented 100/min and 1 000–10 000/day limits; enable it only as a control-plane override `{"detail_required": true, "index_then_detail": true, "wait_between_calls": 1.0}` |
| Direction | INBOUND. Linked accounts' Zoho-fed fields (+ parent, currency, status) are read-only through the API (`422 zoho_owned_field`); a Zoho-connected organization refuses local creation (`422 zoho_mastered_chart`) until the outbox exists. `service.to_zoho_payload` is the outbound seam |
| Matching | `match_on=("zoho_id",)` — re-adoption only. Never by name: Zoho repeats child names across branches |
| References | `currency_id` → `currencies` (`ReferenceRule`, DEFER: NULL = base currency until linked) |
| Organization | the connection's (`ZOHO_ORGANIZATION_ID` → THPL), else `DEFAULT_TENANT_CODE` / `DEFAULT_ORGANIZATION_CODE` |

## Field map (`fields.py`)

| Zoho | → | Dir | Note |
|---|---|---|---|
| `account_name` | `account_name` | BOTH | required on create |
| `account_code` | `account_code` | BOTH | `""` → NULL (a CHECK refuses blank) |
| `account_type` | `account_type` | BOTH | FK to `accounting.account_types.code`; an unknown type fails that one record |
| `description` | `description` | BOTH | in the live list row |
| `is_active` | `status` | IN | `account_status` codec: `active` / `inactive` (string `"true"` tolerated) |
| `is_system_account`, `is_user_created` | same | IN | |
| `can_show_in_ze` | `is_expense_claim_enabled` | BOTH | |
| `show_on_dashboard` | same | BOTH | |
| `placeholder` | same | IN | Zoho's slug of the account NAME (`gl_laptop`) — not a system-role marker |
| `is_register_supported_account` | `is_register_supported` | IN | in every live list row (228/231 true on THPL) |
| `is_standalone_account` | `is_standalone` | IN | in every live list row (35/231 true on THPL) |
| `parent_account_id` | `parent_id` | hook | resolved through the crosswalk after the page flush; unresolved → `sync.pending_references` |
| `account_type_int` | `account_types.zoho_id` | hook | set-once when a tenant reports a type we never saw an id for |
| `is_retained_earnings`, `is_accounts_receivable`, `is_accounts_payable`, `gain_or_loss_account` | organization assignments | hook | undocumented flags; fill an EMPTY organization slot only |

**Never stored, never hashed** (`VOLATILE_KEYS`): `current_balance`, `closing_balance`,
`is_involved_in_transaction`, `child_count`, `is_child_present`, `depth`,
`parent_account_name`, `has_attachment`, `documents`, `*_formatted`, and from the detail document
`isdebit` (the side of the CURRENT balance — not the normal side; verified live) and `transactions`. `showbalance=true` is
never requested — a balance moving is not a change to the account.

## Live (THPL, 2026-10-08)

First sync, list-only: 2 calls, 231 accounts, all with a currency, 74 children linked, no chart-rule violations,
no duplicate codes. An earlier detail-on attempt hit an undocumented HTTP 429 `code: 43` (see the plan's
*As built* — an observation, not a documented limit).

## Cross-module links

* **Taxes → accounts.** `taxes/zoho/hooks.link_tax_accounts` turns a tax's `tax_account_id` /
  `purchase_tax_account_id` / `tds_payable_account_id` into `accounting.account_assignments`
  (purposes `output_tax` / `input_tax` / `tds_payable`) for the organization in context. A tax
  synced before the chart leaves a pending assignment; the reconcile lane links it. **Observed on
  THPL (not documented):** GST legs leave `purchase_tax_account_id` empty and carry the INPUT-tax
  account in `tds_payable_account_id`, so for a GST leg without `purchase_tax_account_id` that id
  is read as `input_tax` (`tax_account_refs`). Taxes synced before this module existed:
  `python -m app.modules.taxes.zoho.backfill` (replays stored documents, zero API calls).
* **Items / contacts (next).** Their adapters call
  `accounting.assignment_service.sync_source_assignments(owner, refs={purpose: zoho_account_id})`.

## Verified

`tests/zoho_core/test_masters_e2e.py` runs it through the real transport: the child listed
before its parent is linked, `""` codes become NULL, the currency resolves, the tax's pending
link is drained, the engine answers "IGST18 posts to Output IGST", and a moving balance is a
no-op on the second pass.
