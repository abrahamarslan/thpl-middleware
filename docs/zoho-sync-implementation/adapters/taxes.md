# Adapter — taxes (O1 master)

**Status:** ✅ live (pull) · **Code:** `app/modules/taxes/` ·
**Migration:** `91e970e99176` (`zoho_taxes`) · **Tests:** `tests/zoho_core/test_masters.py`,
`test_batch_apply.py` · **Source:** `docs/zoho-docs-md/taxes.md`

| Aspect | Value | Why |
|---|---|---|
| Endpoint | `GET /settings/taxes` (Books) — simple and compound taxes | — |
| Pagination | yes (documented `page_context`), 200 per page | — |
| Id attribute | `tax_id` | — |
| Strategy | `full`, every 1440 min; no weekly lane | no `last_modified_time`; cost = 1 call per 200 taxes |
| Detail call | none | list rows carry every mirrored attribute |
| Direction | inbound only | managed in Zoho |
| Mixins | Identity + Mirror | read-only master |

| Column | Zoho attribute | Notes |
|---|---|---|
| `tax_name` | `tax_name` | indexed |
| `tax_percentage` | `tax_percentage` | `numeric(9,4)` |
| `tax_type` | `tax_type` | `tax` · `compound_tax` |
| `tax_specific_type` | `tax_specific_type` | India: `igst` · `cgst` · `sgst` · `nil` · `cess` |
| `tax_factor`, `tax_authority_id`, `tax_authority_name` | same | edition-specific |
| `is_value_added`, `is_default_tax`, `is_editable` | same | bool |
| `country`, `country_code` | same | UK/EU/GCC editions |
| `tax_account_id`, `purchase_tax_account_id`, `output_tax_account_name`, `purchase_tax_account_name` | same | ledger links |

HTTP (read-only, authenticated): `GET /api/zoho/taxes?specific_type=igst` ·
`GET /api/zoho/taxes/{ref}` (local id or Zoho id).

Open: tax groups (`/settings/taxgroups`) as their own module with a child
collection of member taxes; tax exemptions; wiring item/line-item `tax_id`s
(Phase 6/7).
