# Adapter: `parties` — Zoho Books `/contacts` → `party.*` (+ geo, tax, extfields, accounting)

**Package:** `app/modules/parties/zoho/` · **Migration:** `20261009_0900_934e2e5ea8cb`
**Design:** [`docs/implementation-plan/contacts-module.md`](../../implementation-plan/contacts-module.md)
**Vendored API docs:** `docs/zoho-docs-md/contact.md`, `contact-persons.md`

**Naming.** Zoho says *contact* (customer or vendor); the platform says **party** (`party.parties`, crosswalk module
`parties`, `/api/parties`). People stay *contact persons* (`party.contact_persons`, crosswalk module
`contact_persons`).

## Contract

| | |
|---|---|
| Endpoint | `GET /contacts?filter_by=Status.All&sort_column=created_time&sort_order=A` (paginated); detail `GET /contacts/{contact_id}` |
| Identity | crosswalk (module `parties`, `external_id` = `contact_id`) + engine-maintained `zoho_id` echo; persons: crosswalk module `contact_persons` written by the hook |
| Strategy | **FULL**. No modified-since filter is documented for `/contacts`; the apply gate skips the detail of every contact whose listed `last_modified_time` has not moved |
| Order | `created_time` ascending — stable under edits made mid-scan (a name or modified-time sort moves rows between pages) |
| Detail | `index_then_detail`: every contact exists after the list scan; the detail adds persons, addresses, GSTINs, taxes, price list. `wait_between_calls=1.5` |
| Rate limits | A 429 / open circuit in the detail phase **keeps the page's progress** (list rows + the details already applied), leaves the cursor on the page, and re-raises at the page boundary. The next run re-lists the page; the gate skips every detail already stored |
| Deletion | `soft_delete_missing` + **`confirm_missing_by_detail`**: a contact absent from a complete scan is tombstoned only if `GET /contacts/{id}` says it does not exist; one Zoho still returns is re-applied |
| Merges | `cf_merged_customer_ids` (THPL's record of merged duplicates) → crosswalk rows `link_state='merged'` pointing the retired id at the survivor. Merged ids are never part of the "missing" set, and a payload for a merged id is ignored (`stale_ignored`, `merged_redirect`) — it can never overwrite the survivor |
| Direction | INBOUND; Zoho-owned columns refuse local edits |
| References | `currency_id` → currencies, `pricebook_id` → price_lists (DEFER) |
| Organization | the connection's (`ZOHO_ORGANIZATION_ID` → THPL) |

## Where each part of a contact goes

| Zoho | Platform |
|---|---|
| scalar fields (`fields.py`) | `party.parties` columns (`contact_name`→`name`, `contact_type`→`party_type`, `place_of_contact`→`place_of_supply`, `trader_name`→`trade_name`, `is_bcy_only_contact`→`is_base_currency_only`, `is_consent_agreed`→`consent_agreed` …) |
| `contact_persons[]` | `party.contact_persons` (replace-set by `contact_person_id`; exactly one primary — demote, flush, promote) + crosswalk `contact_persons` |
| `primary_contact_id` | `parties.primary_contact_person_id` (deferred FK) |
| `billing_address` / `shipping_address` / `addresses[]` | `geo.place_links` (owner `party`, `zoho_id` = `address_id`, link types billing / shipping / **other**) → `geo.places` (postal text, coordinates). Empty blocks create nothing; reuse within one party only; copy-on-write when a place is shared or field-verified |
| `cf_location_latitude/longitude` | the billing (else shipping) place's coordinates — only inside the country's bounding box, never over a better source |
| `tax_info_list[]`, `gst_no`, `pan_no`, `udyam_*`, `vat_reg_no`, `tax_reg_no` | `tax.tax_registrations` (owner `party`; numbers normalized, in clear) |
| `tax_id` / `tax_exemption_id` | `tax.tax_assignments` (owner `party`; pending until the tax syncs) |
| `account_id` | `accounting.account_assignments` (`receivable` for customers, `payable` for vendors) |
| `custom_fields[]` | `extfields.field_definitions` (learned: `zoho_field_id`, data type, options) + `field_values` |
| `payment_terms_id` + code + label | `party.payment_terms` (learned; Zoho id = identity; negative codes are rules) |
| `owner_id` | `parties.owner_zoho_user_id` → `zoho_users` |
| balances, summaries, `*_formatted`, `portal_receipt_count` | hash-volatile; never columns |

Each structured step runs only when its key is in the payload — list rows never touch persons, addresses,
registrations or taxes.

## Live (THPL)

See the plan's *As built* section for the first full sync and the population audit.
