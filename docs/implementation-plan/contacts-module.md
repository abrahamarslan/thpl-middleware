# Contacts module — Zoho contacts & contact persons, organization-scoped

> **BUILT 2026-10-09 as the `parties` module.** Sections 1–12 below are the plan as written on 2026-10-08;
> where the build differs, **this box wins**:
>
> | Plan | As built (owner decisions 2026-10-09) |
> |---|---|
> | schema `crm`, `crm.contacts`, package `contacts` | schema **`party`**: `party.parties` (class `Party`, `party_type` customer/vendor), `party.contact_persons`, `party.payment_terms`; package `app/modules/parties/`; crosswalk modules `parties` / `contact_persons`; API `/api/parties`. "Party" = the counterparty of either role; Zoho still says contact |
> | `customer_sub_category` column + `crm.customer_sub_categories` | **categories module** (polymorphic): taxonomy `customer_sub_category` whitelisted for entity type `party` (`allows_multiple=false`), assignments in `core.categorizables`, `HasCategoriesMixin` on `Party`. No column, no table. The seeder comes later |
> | PAN encrypted (+ redaction engine change E2) | PAN stored **in clear** in `tax.tax_registrations.registration_number` (owner decision); no encryption, no redaction |
> | `addresses[]` → shipping | `addresses[]` → link type **`other`** |
> | Customers vs vendors | one table; role-specific columns are NULL for the other role; a 1:1 role-profile table is the extension point when roles diverge (`parties/enums.py`) |
> | (not planned) document mixins | **`HasCustomerMixin` / `HasVendorMixin` / `HasPartyMixin`** (`parties/mixins.py`) for estimates, invoices, payments: `<role>_id` + relationship + composite same-organization FK + the Zoho `ReferenceRule` (module `parties`, DEFER; merged ids resolve to the survivor) |
> | Contact persons | + `HasAddressesMixin` (their location = their places' coordinates), `HasMediaMixin` (avatar: `POST /api/parties/persons/{ref}/avatar`), documents, comments, custom fields; `app_metadata` / `app_version` via `OrgEntityMixin` |
> | Engine E1–E8 | Built: **E1** (rate limit mid-page keeps progress, cursor stays on the page), **E4** (`LinkState.MERGED`, excluded from the tombstone live set) + a guard that ignores payloads of merged ids, **E5** (persons write their own crosswalk rows via `upsert_record`), **E6** (`confirm_missing_by_detail`). Not needed: E3 / E8 (per-page commits + leased slices already bound the first sync), E7 (FULL kept), E2 (no PAN encryption) |
> | Schema SQL §5 | superseded by migration `20261009_0900_934e2e5ea8cb` (names: `party.*`, `party_id`, `merged_into_party_id`, `tax_registrations` without encryption columns) |
>
> Adapter: [`adapters/parties.md`](../zoho-sync-implementation/adapters/parties.md). The first live sync and its audit
> are in §13.

**Status:** BUILT (see box) · **Package:** `app/modules/parties/` · **Schema:** `party`
(+ additions to `tax`, `geo`, `extfields`) · **Zoho:** `GET /contacts`, `GET /contacts/{contact_id}`
(docs/zoho-docs-md/contact.md, contact-persons.md) · **Builds on:** [tenancy](../tenancy/README.md),
[geo](../geo/README.md), [taxes](tax-assignments.md), [accounts](accounts-module.md),
[price lists](price-lists-module.md), custom fields, documents, media, comments, the sync crosswalk.

---

## 0. What was asked, and where each ask lands

| Ask | Answer in this plan |
|---|---|
| Addresses saved properly | Zoho billing / shipping / additional addresses → `geo.places` (the only table with coordinates) + `geo.place_links` (owner `contact`, typed, Zoho `address_id` on the **link**). No address columns on `crm.contacts`. §6.4 |
| Contact organization-scoped | `OrgEntityMixin` on every new table (tenant + organization NOT NULL, composite FKs). Zoho rows land in the connection's organization (THPL). §5 |
| `zoho_id` | On `crm.contacts`, `crm.contact_persons`, `tax.tax_registrations`, `crm.payment_terms`, `geo.place_links` — each the engine/hook-maintained echo of Zoho's own id; the crosswalk stays the identity of record. §5 |
| Media, documents on contacts and persons (and comments, custom fields, taxes, accounts) | Mixins: existing `HasDocumentsMixin`, `HasCommentsMixin`, `HasCustomFieldsMixin`, `HasTaxesMixin`, `HasAccountsMixin`; **new** `HasMediaMixin` (media), `HasAddressesMixin` (geo), `HasCurrencyMixin` (currencies). §4 |
| A currency mixin | `app/modules/currencies/mixins.py::HasCurrencyMixin` — column + composite-FK helper + relationship. §4.1 |
| Custom fields | Zoho `custom_fields[]` / `contactperson_custom_fields[]` → `extfields.field_definitions` / `field_values` (owner types `contact`, `contact_person`); definitions gain `zoho_field_id` + `options`. §6.7 |
| `app_metadata`, `app_version` | Present on every table through `OrgEntityMixin` → `AppMetaMixin` (shown explicitly in the DDL). |
| `customer_sub_category` | Local (not Zoho) column on `crm.contacts`, FK to an org-scoped, editable vocabulary `crm.customer_sub_categories`. §5.3 |

---

## 1. Evidence

### 1.1 Live probe (THPL, 2026-10-08 — read-only GETs, 42 calls, probe data deleted afterwards)

| Fact | Number | Consequence |
|---|---|---|
| Contacts (`filter_by=Status.All`) | **8,212** (42 list pages) | First sync = 8,212 detail calls → must be budgeted over days (§7.4) |
| Customers / vendors (sample of 6,000 rows) | 5,903 / 97 | One table, `contact_type` |
| business / individual | 5,939 / 61 | `customer_sub_type` |
| active / inactive | 5,488 / 512 | The default list hides inactive → `filter_by=Status.All` is mandatory |
| Modified per day (last 7 / 30 days) | ≈ 43 / ≈ 29 (busiest day 86) | Steady state is cheap: ~50–120 detail calls/day |
| List row carries `last_modified_time` | 100 % | The apply gate can skip unchanged details |
| List row carries every `cf_*` value + `custom_fields[]` | yes | Custom fields update even before the detail lands |
| List row carries `pan_no` **in plaintext** | 224 rows (222 also have a GSTIN) | PAN must be redacted **before** the raw document is persisted anywhere (§7.6) |
| `gst_treatment` values | `business_none` 5,356 · `consumer` 419 · `business_gst` 221 · `business_registered_composition` 3 · `overseas` 1 | `business_registered_composition` is **not** in Zoho's documented list → no CHECK on it |
| `payment_terms` codes | `0` 5,535 · `15` 454 · **`-3` 11** ("Due end of next month") | A negative code is a rule, not days → `crm.payment_terms` keeps the code |
| `payment_terms_label` | "Due on Receipt" 4,842 **and** "Due On Receipt" 693 | Labels are not identity; Zoho's `payment_terms_id` is (4 distinct; 2,582 rows carry one) |
| `cf_merged_customer_ids` | 151 rows, each two ids | Zoho-side merges, recorded by THPL in a custom field → crosswalk redirect (§7.8) |
| `cf_location_latitude/longitude` | 95 rows; **7** inside India, 88 valid numbers outside it | Coordinates from custom fields only when plausible; the rest is reported, never written (§6.4.5) |
| HUL distributor fields (`cf_hul_*`) | ~1,216 rows, 24 fields; plus `cf_hul_drug_license_20b/21b(+_expiry)` 5–9 rows | Custom fields, not columns |
| Detail: persons / addresses | 3 of 5 probed contacts have **no** person; vendor had none; every contact has billing AND shipping objects with **distinct `address_id`s even when empty** | Empty addresses create no place; persons are optional |
| Detail-only keys vs list | ~100 (167 with HUL fields) | `index_then_detail` |
| Vendor-only keys | `tds_tax_name`, `tds_tax_percentage`, `vendor_currency_summaries`, `zcrm_vendor_id`; vendor has no `is_taxable` | Absent ≠ false |
| `customer_name`, `vendor_name` | equal `contact_name` on every row | Not stored (duplicates) |
| `pricebook_id` | absent from list rows; present in detail (most customers → "demo") | Price-list link is detail-only |
| Contact persons' `communication_preference` | `{is_email_enabled, is_whatsapp_enabled}` (live) — the docs say `is_sms_enabled`; SMS is `is_sms_enabled_for_cp` | Map the live keys |

### 1.2 What the docs say (and do not)

* Documented: list (`filter_by` incl. `Status.All`, `sort_column` incl. `created_time`, `last_modified_time`),
  get, create, update, delete, active/inactive, addresses (`GET /contacts/{id}/address`), contact persons
  (`GET /contacts/{id}/contactpersons[/{id}]`).
* **Not documented:** a modified-since filter on `GET /contacts` (categories accepts `last_modified_time`
  live; contacts is unverified → probe P0.6, never assumed). `payment_terms_id`, `tax_info_list`,
  `udyam_*`, `msme_type`, `lock_detail`, `is_whatsapp_disabled_by_customer` … are live-only keys.
* Limits (docs/zoho-docs-md/introduction.md): 100 requests/min/org; **1,000–10,000 requests/day by plan**.
  `ZOHO_DAILY_HARD_LIMIT` defaults to **45,000** in `app/core/conf.py` — above every documented plan cap;
  it must be set to the contract's real number before the first contacts sync (§7.4).

---

## 2. Reconciling the proposed schema with the platform

The pasted design is a good target picture; several of its tables already exist here in a generic,
platform-wide form, and building a contact-only copy would create the second truth the platform keeps
removing. Decisions:

| Proposed | Decision | Why |
|---|---|---|
| `customers` | **Adopted as `crm.contacts`** | Zoho's contact is customer **or** vendor (`contact_type`); one table, as Zoho has |
| `customer_persons` | **Adopted as `crm.contact_persons`** | Zoho `contact_persons[]`, own Zoho id, crosswalked |
| `customer_external_refs`, `customer_sync_state` | **Rejected — exists** | `sync.sync_records` (identity, fence, hash, raw, custom fields), `sync.sync_payloads` (history), `sync.pending_references`, `zoho_sync_runs/events/stats` (state machine, retries). A per-entity copy would drift from the engine that writes it |
| `customer_attribute_defs`, `customer_attributes`, `customer_person_attributes` | **Rejected — exists** | `extfields.field_definitions` / `field_values` are exactly this (typed EAV, owner types). Gains `zoho_field_id` + `options` |
| `customer_document_links` | **Rejected — exists** | `documents.document_links` (polymorphic, roles) via `HasDocumentsMixin` |
| Addresses in `geo.postal_addresses` | **Adapted** | This platform merged postal addresses into `geo.places` + `geo.place_links` (docs/geo/README.md §3). Zoho's `address_id` goes on the **link** (§6.4) |
| Tax registrations (GSTIN, encrypted PAN) | **Adopted as `tax.tax_registrations`** (polymorphic owner) | Organizations, contacts and later vendors-of-record share one shape; PAN encrypted with the platform's pgcrypto pattern |
| `payment_terms` (seeded) | **Adapted** — `crm.payment_terms` **learned from Zoho** (`zoho_id`, code, label) | Zoho's terms include rule codes (`-3`) and case-variant labels; seeding `NET_15` etc. would not match Zoho's ids |
| `pricebook_id` FK | **Adopted** → `price_list_id` → `pricing.price_lists` | Already synced (price lists module) |
| `customer_aliases` (merge history) | **Adapted** → crosswalk rows with `link_state='merged'` + `crm.contacts.merged_into_contact_id` | A retired Zoho id must resolve to the survivor wherever the engine resolves references; the crosswalk IS that resolver |
| Balances (15 fields) | **Adopted the rule** — not stored; hash-volatile | A balance moving is not a contact changing (also keeps the gate cheap) |
| `customer_branches` | **Deferred** | `is_associated_to_branch=false` on every probed contact; no branch module |
| `customer_bank_accounts`, `customer_payment_mandates`, cards / checks / VPA | **Deferred** | 0 rows carry them; cards are never stored (PCI) |
| `customer_approval_steps`, approval columns | **Deferred** | All empty; approvals belong to a workflow module |
| `customer_templates` | **Deferred** | 0 non-blank template ids in every probe; raw document keeps them |
| `customer_portal_accounts` | **Adapted** — portal flags on `contact_persons` + `contacts.portal_status` | Portal access is per person in Zoho |
| `customer_status_history` (bitemporal), `customer_reason_codes` | **Deferred** | Zoho has one `status`; history = `sync.sync_payloads` + activity log. Holds/blocks arrive with credit control |
| `code` UNIQUE NOT NULL, `slug` | **Rejected for now** | Zoho's `contact_number` is optional and absent here; no portal routing yet. `contact_number` kept nullable |
| `kind` (lead, prospect, partner …) | **Adapted** → `contact_type` CHECK (`customer`,`vendor`) | Zoho's closed set; leads belong to a CRM pipeline, not the ledger party |
| Locks, `locked_actions` | **Raw only** | Zoho-internal UI locks |
| `owner_user_id` / `assigned_user_id` | **Adapted** → `owner_zoho_user_id` (Zoho owner) | Field-rep assignment belongs to teams / field ops |
| DPDP consent columns | **Adopted** (`consent_agreed`, `consent_at`) | Zoho-fed; `compliance.consent_records` is per platform user and does not fit a counterparty |
| Views `v_customers_active` … | **Rejected** | ORM queries + partial indexes serve; views would be a second contract to migrate |

---

## 3. Module layout

```
app/modules/contacts/
    enums.py           ContactType, CustomerSubType, ContactStatus, PortalStatus, CONTACTS_MODULE …
    model.py           Contact, ContactPerson, CustomerSubCategory, PaymentTerm
    crud.py / service.py / schema.py / api.py / errors.py
    registration.py    migration helpers: entity types + opt-ins (taxes, accounts, comments, custom fields)
    zoho/
        fields.py      FieldSpec map (contact) + VOLATILE_KEYS + REDACTIONS
        codecs.py      contact_status, payment_terms, gst_state …
        hooks.py       after_contact_upsert → persons, addresses, registrations, taxes, accounts,
                       payment term, owner, custom fields, merges, coordinates
        persons.py     project_persons (replace-set + child crosswalk)
        addresses.py   project_addresses (places + links, copy-on-write)
        spec.py        module "contacts"
app/modules/currencies/mixins.py     HasCurrencyMixin                (new)
app/modules/geo/mixins.py            HasAddressesMixin               (new)
app/modules/media/mixins.py          HasMediaMixin                   (new)
app/modules/taxes/registrations.py   TaxRegistration model + service (new)
app/common/security/pii.py           pgcrypto encrypt / hmac / mask  (new, shared)
```

Import direction (`.importlinter`): `contacts` imports `taxes`, `accounting`, `geo`, `currencies`,
`price_lists`, `custom_fields`, `documents`, `media`, `comments`; none of them imports `contacts`
(new forbidden contracts mirror the accounting one).

---

## 4. Mixins

All follow the house pattern (`HasTaxesMixin`): a `viewonly`, `lazy="raise_on_sql"` relationship, the
owner type derived from the class name (`ContactPerson` → `contact_person`) unless overridden, writes only
through the owning service.

### 4.1 `HasCurrencyMixin` (new, `app/modules/currencies/mixins.py`)

```python
class HasCurrencyMixin:
    """currency_id → currency.currencies, same tenant. NULL = the organization's base currency."""

    currency_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="currency.currencies; NULL = the organization's base currency")

    @declared_attr
    def currency(cls):  # noqa: N805
        return relationship("Currency", primaryjoin=lambda: foreign(cls.currency_id) == Currency.id,
                            viewonly=True, lazy="raise")

    @classmethod
    def currency_fk(cls, table: str) -> ForeignKeyConstraint:
        """Put in __table_args__: the composite (tenant_id, currency_id) FK every currency user repeats today."""
        return ForeignKeyConstraint(["tenant_id", "currency_id"],
                                    ["currency.currencies.tenant_id", "currency.currencies.id"],
                                    name=f"fk_{table}_currency", ondelete="RESTRICT")
```

`accounting.accounts` and `pricing.price_lists` declare the same column + FK by hand today; they adopt the
mixin in the same PR (no DDL change — names are identical).

### 4.2 `HasAddressesMixin` (new, `app/modules/geo/mixins.py`)

`addresses` → live `geo.place_links` of this owner (`owner_type = address_owner_type_of(cls)`), ordered
billing → shipping → others, `selectinload(...).joinedload(PlaceLink.place)`. Writes through
`geo.service` (link / unlink / freeze), never the relationship. Requires the owner type in
`geo.model.link.OWNER_TYPES` (+ CHECK migration).

### 4.3 `HasMediaMixin` (new, `app/modules/media/mixins.py`)

`media` → live `media.items` with `model_type = media_owner_type_of(cls)`, `model_id = cls.id`, ordered by
collection, `sort_order`. Writes stay owner-endpoint-only (media doctrine: no generic upload route).
Collections for contacts: `logo`, `storefront` (shop photos from field visits), `documents_scan`; persons:
`photo`. Policies in `media/conversions.py`.

### 4.4 Applied to the models

```python
class Contact(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, VerificationMixin, HasCurrencyMixin,
              HasAddressesMixin, HasTaxesMixin, HasAccountsMixin, HasCustomFieldsMixin,
              HasDocumentsMixin, HasMediaMixin, HasCommentsMixin, SoftDeleteFilteredMixin, Base):
    custom_fields_owner_type = "contact"

class ContactPerson(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasAddressesMixin, HasCustomFieldsMixin,
                    HasDocumentsMixin, HasMediaMixin, HasCommentsMixin, SoftDeleteFilteredMixin, Base):
    custom_fields_owner_type = "contact_person"
```

Registry rows (migration, via the existing helpers): `core.entity_types` `contact` → `crm.contacts`,
`contact_person` → `crm.contact_persons`; `register_taxable_entity_type(code="contact",
allows_multiple=False, allows_exemption=True)`; `register_account_owner_type(code="contact",
purposes={"receivable": True, "payable": True, "sales": False, "purchase": False})`;
`register_commentable_entity_type` for both; `DocumentLinkableType` gains `CONTACT`, `CONTACT_PERSON`
(no DDL — open at DB level). The resolution engine already names the `contact` role
(`taxes/resolution.py` exemption_only / taxes_only steps; `accounting/resolution.py` document_party,
sales_line, purchase_line) — registering the class is what turns those steps on.

---

## 5. Schema (PostgreSQL 18)

Conventions (as built elsewhere): `bigserial` id + `uuid DEFAULT uuidv7()`; the `OrgEntityMixin` column
set; composite `(tenant_id, organization_id, …)` FKs so a child can never cross an organization; partial
unique indexes on live rows; CHECKs only for **Zoho's documented closed sets** (an observed-but-undocumented
value must never fail a sync — `business_registered_composition` proves the point); Zoho-owned columns
are listed in the contract (`owned_fields`) and refused on local PATCH.

The standard block, written out once and then referenced as `/* std */`:

```sql
    -- /* std */ OrgEntityMixin (MultiTenant + Audit + Status + RowVersion + AppMeta + Timestamp) + SoftDelete
    tenant_id        bigint       NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id  bigint       NOT NULL,
    created_by       bigint,                      -- users.id (NULL = system)
    created_by_name  varchar(255),                -- 'system:zoho-sync' for synced rows
    updated_by       bigint,
    updated_by_name  varchar(255),
    status           varchar(20)  NOT NULL DEFAULT 'active',
    is_verified      boolean      NOT NULL DEFAULT false,
    row_version      integer      NOT NULL DEFAULT 1,
    app_version      varchar(32),                 -- app version that last wrote the row
    app_metadata     jsonb        NOT NULL DEFAULT '{}'::jsonb,
    created_at       timestamptz  NOT NULL DEFAULT now(),
    updated_at       timestamptz  NOT NULL DEFAULT now(),
    deleted_at       timestamptz,
    deleted_by       bigint,
    deleted_reason   text,
    -- + mixin indexes: ix_<schema>_<table>_{status,tenant_id,deleted_at}, unique ix_<schema>_<table>_uuid,
    --   ix_<table>_tenant_org (tenant_id, organization_id)
```

### 5.1 Schema

```sql
CREATE SCHEMA IF NOT EXISTS crm;
COMMENT ON SCHEMA crm IS 'Commercial parties: contacts (customers / vendors), their persons and terms.';
```

### 5.2 `crm.payment_terms` — learned from Zoho

```sql
CREATE TABLE crm.payment_terms (
    id               bigserial    PRIMARY KEY,
    uuid             uuid         NOT NULL DEFAULT uuidv7(),
    zoho_id          varchar(50),                         -- Zoho payment_terms_id (NULL = local term)
    payment_terms    integer      NOT NULL,               -- Zoho code: >= 0 = net days; < 0 = a rule (-3 'Due end of next month')
    label            text         NOT NULL,               -- Zoho payment_terms_label, verbatim (case varies: 'Due On Receipt')
    net_days         integer      GENERATED ALWAYS AS (CASE WHEN payment_terms >= 0 THEN payment_terms END) STORED,
    first_seen_at    timestamptz  NOT NULL DEFAULT now(), -- first contact payload that named it
    last_seen_at     timestamptz  NOT NULL DEFAULT now(),
    /* std */
    CONSTRAINT fk_payment_terms_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    CONSTRAINT uq_payment_terms_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT ck_payment_terms_label_not_blank CHECK (btrim(label) <> ''),
    CONSTRAINT ck_payment_terms_status CHECK (status IN ('active', 'inactive'))
);
CREATE UNIQUE INDEX uq_payment_terms_zoho_id ON crm.payment_terms (tenant_id, zoho_id)
    WHERE deleted_at IS NULL AND zoho_id IS NOT NULL;
COMMENT ON TABLE crm.payment_terms IS
    'Payment terms as Zoho names them (learned from contact payloads; Zoho id = identity). Code < 0 = a rule.';
```

No seed. Zoho documents no payment-terms endpoint in our vendored docs; the 4 live ids arrive with the
contacts that use them (`hooks._learn_payment_term`, set-once id, label refreshed).

### 5.3 `crm.customer_sub_categories` — local vocabulary

```sql
CREATE TABLE crm.customer_sub_categories (
    id                bigserial    PRIMARY KEY,
    uuid              uuid         NOT NULL DEFAULT uuidv7(),
    code              varchar(64)  NOT NULL,              -- 'chemist', 'hospital', 'clinic', 'wholesaler' … (owner to supply)
    name              text         NOT NULL,
    customer_sub_type varchar(16),                        -- 'business' | 'individual' | NULL = either
    description       text,
    sort_order        smallint     NOT NULL DEFAULT 0,
    /* std */
    CONSTRAINT fk_customer_sub_categories_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- FK target for crm.contacts.customer_sub_category. Not partial: a retired code stays reserved
    -- (status = 'inactive'), so a contact can never point at a recycled meaning.
    CONSTRAINT uq_customer_sub_categories_org_code UNIQUE (organization_id, code),
    CONSTRAINT ck_customer_sub_categories_code CHECK (code ~ '^[a-z0-9_]{1,64}$'),
    CONSTRAINT ck_customer_sub_categories_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT ck_customer_sub_categories_sub_type
        CHECK (customer_sub_type IS NULL OR customer_sub_type IN ('business', 'individual')),
    CONSTRAINT ck_customer_sub_categories_status CHECK (status IN ('active', 'inactive'))
);
```

### 5.4 `crm.contacts`

```sql
CREATE TABLE crm.contacts (
    id                       bigserial    PRIMARY KEY,
    uuid                     uuid         NOT NULL DEFAULT uuidv7(),

    -- identity (Zoho)
    zoho_id                  varchar(50),            -- echo of Zoho contact_id (crosswalk = identity of record)
    contact_number           text,                   -- Zoho contact_number (optional; absent on THPL)
    source_created_at        timestamptz,            -- Zoho created_time ("customer since")

    -- names (Zoho-owned)
    contact_name             text         NOT NULL,  -- Zoho contact_name (display + search)
    company_name             text,
    legal_name               text,                   -- Zoho legal_name (GST legal name of the primary registration)
    trade_name               text,                   -- Zoho trader_name
    salutation               varchar(25),            -- Zoho contact_salutation  } Zoho's contact-level echo of the
    first_name               varchar(100),           -- Zoho first_name           } primary person; kept because a
    last_name                varchar(100),           -- Zoho last_name            } contact may carry them with no
    designation              varchar(100),           --                           } person row (verified by the audit)
    department               varchar(100),

    -- classification
    contact_type             varchar(16)  NOT NULL,  -- customer | vendor          (Zoho, documented closed set)
    customer_sub_type        varchar(16),            -- business | individual      (Zoho, documented; customers only)
    customer_sub_category    varchar(64),            -- LOCAL: crm.customer_sub_categories.code
    source                   varchar(32),            -- Zoho source: api | csv | user (no CHECK: observed set)
    language_code            varchar(10),            -- '' → NULL

    -- commercial (Zoho-owned)
    currency_id              bigint,                 -- HasCurrencyMixin → currency.currencies (ReferenceRule)
    is_base_currency_only    boolean,                -- Zoho is_bcy_only_contact
    price_list_id            bigint,                 -- Zoho pricebook_id → pricing.price_lists (ReferenceRule, DEFER)
    payment_term_id          bigint,                 -- Zoho payment_terms_id → crm.payment_terms (hook; NULL when Zoho sends '')
    payment_terms            integer,                -- Zoho code, always carried (rows without an id still have it)
    payment_terms_label      text,
    credit_limit             numeric(18, 2),         -- Zoho credit_limit (customers)
    is_taxable               boolean,                -- absent on vendors → NULL, not false
    place_of_supply          varchar(4),             -- Zoho place_of_contact (GST state code 'GJ')
    gst_treatment            varchar(40),            -- tax.gst_treatment_types.value (validated softly; Zoho trusted)
    contact_category         varchar(40),            -- Zoho contact_category

    -- communication (Zoho-owned; contact-level, usually the primary person's)
    email                    varchar(255),
    phone                    varchar(50),
    mobile                   varchar(50),
    website                  text,
    facebook                 varchar(100),
    twitter                  varchar(100),
    is_sms_enabled           boolean,
    payment_reminder_enabled boolean,
    portal_status            varchar(16),            -- Zoho portal_status: disabled | invited | …

    -- relations
    primary_contact_person_id bigint,                -- Zoho primary_contact_id → crm.contact_persons (hook)
    owner_zoho_user_id       bigint,                 -- Zoho owner_id → public.zoho_users (hook; NULL if unknown)
    merged_into_contact_id   bigint,                 -- survivor after a Zoho merge (cf_merged_customer_ids)

    -- compliance / flags (Zoho-owned)
    consent_agreed           boolean,                -- Zoho is_consent_agreed (DPDP)
    consent_at               timestamptz,            -- Zoho consent_date
    has_transaction          boolean,
    is_associated_to_branch  boolean,
    notes                    text,                   -- Zoho notes (internal discussion = comments module)

    -- VerificationMixin (KYC of the counterparty; ours, never Zoho's)
    verification_status      varchar(20)  NOT NULL DEFAULT 'unverified',
    verification_method      varchar(50),
    verification_data        jsonb,
    verified_by              bigint,
    verified_at              timestamptz,

    /* std */  -- status = Zoho status (active | inactive)

    CONSTRAINT fk_contacts_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    CONSTRAINT uq_contacts_scope_id UNIQUE (tenant_id, organization_id, id),      -- target of children's FKs
    CONSTRAINT fk_contacts_currency FOREIGN KEY (tenant_id, currency_id)
        REFERENCES currency.currencies (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_contacts_price_list FOREIGN KEY (tenant_id, organization_id, price_list_id)
        REFERENCES pricing.price_lists (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_contacts_payment_term FOREIGN KEY (tenant_id, organization_id, payment_term_id)
        REFERENCES crm.payment_terms (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_contacts_sub_category FOREIGN KEY (organization_id, customer_sub_category)
        REFERENCES crm.customer_sub_categories (organization_id, code) ON DELETE RESTRICT,
    CONSTRAINT fk_contacts_merged_into FOREIGN KEY (tenant_id, organization_id, merged_into_contact_id)
        REFERENCES crm.contacts (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_contacts_owner_zoho_user FOREIGN KEY (owner_zoho_user_id)
        REFERENCES public.zoho_users (id) ON DELETE SET NULL,
    -- fk_contacts_primary_person added after crm.contact_persons exists (§5.5)

    CONSTRAINT ck_contacts_name_not_blank   CHECK (btrim(contact_name) <> ''),
    CONSTRAINT ck_contacts_type             CHECK (contact_type IN ('customer', 'vendor')),
    CONSTRAINT ck_contacts_sub_type         CHECK (customer_sub_type IS NULL OR customer_sub_type IN ('business', 'individual')),
    CONSTRAINT ck_contacts_status           CHECK (status IN ('active', 'inactive')),
    CONSTRAINT ck_contacts_credit_limit     CHECK (credit_limit IS NULL OR credit_limit >= 0),
    CONSTRAINT ck_contacts_not_merged_into_self CHECK (merged_into_contact_id IS NULL OR merged_into_contact_id <> id),
    CONSTRAINT ck_contacts_verification_status
        CHECK (verification_status IN ('unverified', 'geocoded_only', 'field_verified', 'disputed'))
);

CREATE UNIQUE INDEX uq_contacts_zoho_id ON crm.contacts (tenant_id, zoho_id)
    WHERE deleted_at IS NULL AND zoho_id IS NOT NULL;
CREATE INDEX ix_contacts_org_type_status ON crm.contacts (organization_id, contact_type, status)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_contacts_name_trgm    ON crm.contacts USING gin (contact_name gin_trgm_ops) WHERE deleted_at IS NULL;
CREATE INDEX ix_contacts_company_trgm ON crm.contacts USING gin (company_name gin_trgm_ops)
    WHERE deleted_at IS NULL AND company_name IS NOT NULL;
-- Phone search the way people type it: the last 10 digits, whatever the formatting ('+91 93282 89726').
CREATE INDEX ix_contacts_mobile_last10 ON crm.contacts
    (organization_id, right(regexp_replace(mobile, '\D', '', 'g'), 10))
    WHERE deleted_at IS NULL AND mobile IS NOT NULL;
CREATE INDEX ix_contacts_email_lower ON crm.contacts (organization_id, lower(email))
    WHERE deleted_at IS NULL AND email IS NOT NULL;
CREATE INDEX ix_contacts_price_list   ON crm.contacts (price_list_id)   WHERE deleted_at IS NULL AND price_list_id IS NOT NULL;
CREATE INDEX ix_contacts_sub_category ON crm.contacts (organization_id, customer_sub_category)
    WHERE deleted_at IS NULL AND customer_sub_category IS NOT NULL;
CREATE INDEX ix_contacts_merged_into  ON crm.contacts (merged_into_contact_id) WHERE merged_into_contact_id IS NOT NULL;

COMMENT ON TABLE crm.contacts IS
    'Commercial parties (Zoho contacts: customers and vendors) of one organization; Zoho crosswalk module contacts.';
```

### 5.5 `crm.contact_persons`

```sql
CREATE TABLE crm.contact_persons (
    id                          bigserial    PRIMARY KEY,
    uuid                        uuid         NOT NULL DEFAULT uuidv7(),
    contact_id                  bigint       NOT NULL,
    zoho_id                     varchar(50),            -- Zoho contact_person_id
    user_id                     bigint,                 -- LOCAL: platform user, when this person gets an account (portal / app)

    salutation                  varchar(25),
    first_name                  varchar(100),
    last_name                   varchar(100),
    display_name                text GENERATED ALWAYS AS   -- concat_ws is not IMMUTABLE; || is
        (NULLIF(btrim(coalesce(btrim(first_name), '') || ' ' || coalesce(btrim(last_name), '')), '')) STORED,
    designation                 varchar(100),
    department                  varchar(100),
    email                       varchar(255),
    phone                       varchar(50),
    mobile                      varchar(50),
    mobile_country_code         varchar(8),
    fax                         varchar(50),
    skype                       varchar(100),

    is_primary                  boolean      NOT NULL DEFAULT false,   -- Zoho is_primary_contact
    is_email_enabled            boolean,     -- Zoho communication_preference.is_email_enabled
    is_whatsapp_enabled         boolean,     -- Zoho communication_preference.is_whatsapp_enabled
    is_sms_enabled              boolean,     -- Zoho is_sms_enabled_for_cp
    is_whatsapp_disabled_by_customer boolean,
    can_invite                  boolean,
    is_added_in_portal          boolean,
    is_portal_invitation_accepted boolean,
    is_portal_mfa_enabled       boolean,
    portal_enabled_via          varchar(16),
    position                    smallint     NOT NULL DEFAULT 0,       -- Zoho array order

    /* std */

    CONSTRAINT fk_contact_persons_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    CONSTRAINT uq_contact_persons_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_contact_persons_contact FOREIGN KEY (tenant_id, organization_id, contact_id)
        REFERENCES crm.contacts (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_contact_persons_user FOREIGN KEY (user_id) REFERENCES public.users (id) ON DELETE SET NULL,
    CONSTRAINT ck_contact_persons_status CHECK (status IN ('active', 'inactive'))
);

CREATE UNIQUE INDEX uq_contact_persons_zoho_id ON crm.contact_persons (tenant_id, zoho_id)
    WHERE deleted_at IS NULL AND zoho_id IS NOT NULL;
-- Exactly one live primary per contact (Zoho has at most one).
CREATE UNIQUE INDEX uq_contact_persons_one_primary ON crm.contact_persons (contact_id)
    WHERE is_primary AND deleted_at IS NULL;
CREATE INDEX ix_contact_persons_contact ON crm.contact_persons (contact_id, position) WHERE deleted_at IS NULL;
CREATE INDEX ix_contact_persons_mobile_last10 ON crm.contact_persons
    (organization_id, right(regexp_replace(mobile, '\D', '', 'g'), 10))
    WHERE deleted_at IS NULL AND mobile IS NOT NULL;
CREATE INDEX ix_contact_persons_email_lower ON crm.contact_persons (organization_id, lower(email))
    WHERE deleted_at IS NULL AND email IS NOT NULL;
CREATE INDEX ix_contact_persons_user ON crm.contact_persons (user_id) WHERE user_id IS NOT NULL;

-- The contact → primary person pointer closes the cycle once both tables exist.
ALTER TABLE crm.contacts ADD CONSTRAINT fk_contacts_primary_person
    FOREIGN KEY (tenant_id, organization_id, primary_contact_person_id)
    REFERENCES crm.contact_persons (tenant_id, organization_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

COMMENT ON TABLE crm.contact_persons IS
    'People who speak for a contact (Zoho contact_persons[]); Zoho crosswalk module contact_persons.';
```

`DEFERRABLE INITIALLY DEFERRED`: the hook inserts persons and sets the pointer in one flush; the check
runs at commit. A person leaving the contact soft-deletes the row and clears the pointer first.

Not promoted from Zoho: `date_of_birth`, `gender` (no business use; DPDP data minimisation — they remain
only in the redacted raw document, §7.6), `photo_url` (a gravatar placeholder on every probed person),
`photo_document_*`, `zcrm_contact_id`, `mobile_code_formatted`.

### 5.6 `tax.tax_registrations` — GSTIN, PAN, Udyam … of any party

```sql
CREATE TABLE tax.tax_registrations (
    id                  bigserial    PRIMARY KEY,
    uuid                uuid         NOT NULL DEFAULT uuidv7(),
    owner_type_code     varchar(64)  NOT NULL REFERENCES core.entity_types (code) ON DELETE RESTRICT,
    owner_id            bigint       NOT NULL,
    registration_type   varchar(20)  NOT NULL,     -- gstin | pan | udyam | vat | tax_reg_no
    registration_number text,                      -- PUBLIC identifiers only (gstin, udyam, vat, tax_reg_no)
    number_encrypted    bytea,                     -- pgp_sym_encrypt(number, PII_ENCRYPTION_KEY) — confidential types (pan)
    number_masked       varchar(20),               -- 'ABCDE****F' (pan) — what lists and logs show
    number_hmac         bytea        NOT NULL,     -- hmac(normalized number, PII_HMAC_KEY, 'sha256'): exact lookup + dedupe, every type
    legal_name          text,
    trade_name          text,
    place_of_supply     varchar(4),                -- GST state code of this registration ('GJ')
    is_primary          boolean      NOT NULL DEFAULT false,
    valid_from          date,
    valid_to            date,
    details             jsonb        NOT NULL DEFAULT '{}'::jsonb,   -- udyam: {msme_type, is_valid, validated_at}
    zoho_id             varchar(50),               -- Zoho tax_info_id (GSTIN rows from tax_info_list)
    source_system       varchar(16),               -- 'zoho' | NULL (local)
    -- VerificationMixin
    verification_status varchar(20)  NOT NULL DEFAULT 'unverified',
    verification_method varchar(50),               -- 'gst_portal', 'traces', 'manual' …
    verification_data   jsonb,
    verified_by         bigint,
    verified_at         timestamptz,
    /* std */

    CONSTRAINT fk_tax_registrations_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_tax_registrations_type
        CHECK (registration_type IN ('gstin', 'pan', 'udyam', 'vat', 'tax_reg_no')),
    -- A PAN is never stored in clear; a public number is never "encrypted" (it would only hide it from search).
    CONSTRAINT ck_tax_registrations_pan_encrypted
        CHECK ((registration_type = 'pan') = (number_encrypted IS NOT NULL)),
    CONSTRAINT ck_tax_registrations_pan_no_clear
        CHECK (registration_type <> 'pan' OR registration_number IS NULL),
    CONSTRAINT ck_tax_registrations_has_number
        CHECK (registration_number IS NOT NULL OR number_encrypted IS NOT NULL),
    CONSTRAINT ck_tax_registrations_validity CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CONSTRAINT ck_tax_registrations_owner_id CHECK (owner_id > 0)
);
CREATE UNIQUE INDEX uq_tax_registrations_number ON tax.tax_registrations
    (tenant_id, owner_type_code, owner_id, registration_type, number_hmac) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_tax_registrations_one_primary ON tax.tax_registrations
    (tenant_id, owner_type_code, owner_id, registration_type) WHERE is_primary AND deleted_at IS NULL;
CREATE UNIQUE INDEX uq_tax_registrations_zoho_id ON tax.tax_registrations (tenant_id, zoho_id)
    WHERE deleted_at IS NULL AND zoho_id IS NOT NULL;
-- "Who holds GSTIN X / PAN Y?" — duplicate-party detection across contacts.
CREATE INDEX ix_tax_registrations_lookup ON tax.tax_registrations (tenant_id, registration_type, number_hmac)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_tax_registrations_owner ON tax.tax_registrations (tenant_id, owner_type_code, owner_id)
    WHERE deleted_at IS NULL;
-- Owner scope, exactly as tax.tax_assignments does it (ctrg_tax_assignments_integrity): a deferred constraint
-- trigger calling core.assert_owner_scope(type, id, tenant, org) — the owner row must exist in this tenant AND
-- organization (an organization owns itself). Deferred, so a contact and its registrations can land in one flush.
CREATE FUNCTION tax.check_tax_registration_integrity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.deleted_at IS NULL THEN
        PERFORM core.assert_owner_scope(NEW.owner_type_code, NEW.owner_id, NEW.tenant_id, NEW.organization_id);
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER ctrg_tax_registrations_integrity
    AFTER INSERT OR UPDATE OF owner_type_code, owner_id, tenant_id, organization_id, deleted_at
    ON tax.tax_registrations DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION tax.check_tax_registration_integrity();
```

Format checks (GSTIN `^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$`, PAN `^[A-Z]{5}\d{4}[A-Z]$`, Udyam
`^UDYAM-[A-Z]{2}-\d{2}-\d{7}$`) run in the **service for local writes**; Zoho rows are trusted and a
malformed one is reported, not refused (the accounts rule).

### 5.7 Changes to existing schemas

```sql
-- geo: contacts own addresses; Zoho's address_id identifies the LINK (one Zoho address of one contact),
-- never the place (a place is shared by owners — Design Rule Zero).
ALTER TABLE geo.place_links DROP CONSTRAINT chk_place_link_owner_type;
ALTER TABLE geo.place_links ADD CONSTRAINT chk_place_link_owner_type CHECK (owner_type IN
    ('user','organization','department','team','customer','contact','contact_person','vendor','warehouse',
     'zoho_location','invoice','estimate','sales_order','purchase_order','shipment'));
ALTER TABLE geo.place_links ADD COLUMN zoho_id varchar(50);   -- Zoho address_id; NULL = a local address
COMMENT ON COLUMN geo.place_links.zoho_id IS
    'Zoho address_id of this owner''s address (billing / shipping / additional); NULL = local. Zoho-owned when set';
CREATE UNIQUE INDEX uq_place_links_zoho_id ON geo.place_links (tenant_id, zoho_id)
    WHERE deleted_at IS NULL AND zoho_id IS NOT NULL;

-- extfields: Zoho's immutable custom-field id and the dropdown options seen so far.
ALTER TABLE extfields.field_definitions
    ADD COLUMN zoho_field_id varchar(50),            -- Zoho field_id / customfield_id
    ADD COLUMN options jsonb;                         -- [{"id": selected_option_id, "value": …, "color_code": …}] learned from values
CREATE UNIQUE INDEX uq_field_definitions_zoho_field ON extfields.field_definitions
    (tenant_id, organization_id, owner_type_code, zoho_field_id)
    WHERE deleted_at IS NULL AND zoho_field_id IS NOT NULL;

-- sync: no DDL — link_state is unconstrained text; the code gains LinkState.MERGED = 'merged' (§7.8).
```

Registry / permission data (in the same migration, through the existing helpers):

```sql
-- core.entity_types
INSERT INTO core.entity_types (code, name, target_schema, target_table, created_by_name) VALUES
    ('contact',        'Contact',        'crm', 'contacts',        'system:migration'),
    ('contact_person', 'Contact person', 'crm', 'contact_persons', 'system:migration')
ON CONFLICT (code) DO NOTHING;
-- + register_taxable_entity_type('contact', allows_multiple=false, allows_exemption=true)
-- + register_account_owner_type('contact', purposes = receivable, payable (fallback to organization), sales, purchase)
-- + register_commentable_entity_type('contact'), ('contact_person')
-- + seed_permissions(): crm.contact:read|update|manage, crm.contact_person:read|update,
--   crm.sub_category:create|update|delete, tax.registration:read|reveal (reveal = decrypt PAN; audited)
```

---

## 6. Zoho → platform mapping (every key the probe saw)

Disposition legend: **col** column · **fk** resolved reference · **child** projected table · **geo** /
**tax** / **acct** / **cf** another hub · **xw** crosswalk · **vol** volatile (never hashed, never stored
as a column) · **raw** kept only in the (redacted) raw document, with the reason.

### 6.1 Contact

| Zoho key | → | Disposition |
|---|---|---|
| `contact_id` | crosswalk `external_id` + `zoho_id` | xw |
| `contact_name`, `company_name`, `contact_number` | same | col |
| `customer_name`, `vendor_name` | — | raw (= `contact_name` on 100 % of rows) |
| `contact_salutation`, `first_name`, `last_name`, `designation`, `department` | `salutation`, `first_name` … | col (contact-level echo) |
| `legal_name`, `trader_name` | `legal_name`, `trade_name` | col |
| `contact_type`, `customer_sub_type` | same | col (CHECK) |
| `contact_type_formatted`, all `*_formatted` | — | vol |
| `status` | `status` | col |
| `source`, `language_code`, `notes`, `website`, `facebook`, `twitter` | same | col (`''` → NULL) |
| `email`, `phone`, `mobile` | same | col |
| `currency_id` | `currency_id` | fk (ReferenceRule `currencies`, DEFER) |
| `currency_code`, `currency_symbol`, `price_precision`, `exchange_rate` | — | raw (derived from the currency) |
| `is_bcy_only_contact` | `is_base_currency_only` | col |
| `pricebook_id` | `price_list_id` | fk (ReferenceRule `price_lists`, DEFER) |
| `pricebook_name` | — | raw (derived) |
| `payment_terms_id` | `payment_term_id` | fk (hook learns `crm.payment_terms`) |
| `payment_terms`, `payment_terms_label` | same | col |
| `credit_limit` | same | col |
| `is_taxable` | same | col (absent on vendors → untouched) |
| `place_of_contact` | `place_of_supply` | col |
| `gst_treatment`, `contact_category` | same | col (no CHECK) |
| `tax_treatment` | — | raw (= `gst_treatment` on every probed row; non-India editions) |
| `tax_id` | `tax.tax_assignments` (owner contact, Zoho source) | tax — the contact's default tax (`taxes_only` step) |
| `tax_exemption_id` | `tax.tax_assignments.tax_exemption_id` | tax — `exemption_only` step |
| `tax_name`, `tax_percentage`, `contact_tax_information{}`, `tax_specification` | — | raw (derived from the tax) |
| `tds_tax_id`, `tds_tax_name`, `tds_tax_percentage` | — | raw — **deferred by owner decision** (accounts plan) |
| `gst_no` + `tax_info_list[]` | `tax.tax_registrations` (`gstin`, `zoho_id` = `tax_info_id`, place / legal / trade name, primary) | tax |
| `pan_no` | `tax.tax_registrations` (`pan`, encrypted + masked + hmac) | tax — **redacted in raw** |
| `udyam_reg_no`, `msme_type`, `is_valid_udyam_no`, `udyam_validated_time` | `tax.tax_registrations` (`udyam`, `details`) | tax |
| `vat_reg_no`, `tax_reg_no`, `tax_reg_label`, `country_code` | `tax.tax_registrations` (`vat` / `tax_reg_no`) when non-blank | tax |
| `account_id` | `accounting.account_assignments` purpose `receivable` (customer) / `payable` (vendor) | acct — blank on every probed row; **semantics to verify** on the first non-blank one |
| `account_name` | — | raw |
| `owner_id` | `owner_zoho_user_id` | fk (hook, `zoho_users.zoho_id`) |
| `owner_name` | — | raw |
| `primary_contact_id` | `primary_contact_person_id` | fk (hook, after persons) |
| `contact_persons[]` | `crm.contact_persons` | child (§6.2) |
| `billing_address`, `shipping_address`, `addresses[]` | `geo.places` + `geo.place_links` | geo (§6.4) |
| `entity_address_id` | — | raw (meaning undocumented) |
| `custom_fields[]`, `cf_*`, `custom_field_hash` | `extfields` (owner `contact`) | cf (§6.7) |
| `cf_merged_customer_ids` | crosswalk merge redirect | xw (§7.8), also kept as a cf value |
| `cf_location_latitude`, `cf_location_longitude` | place coordinates (plausible only) | geo (§6.4.5), also cf values |
| `is_consent_agreed`, `consent_date` | `consent_agreed`, `consent_at` | col |
| `has_transaction`, `is_associated_to_branch`, `payment_reminder_enabled`, `is_sms_enabled`, `portal_status` | same | col |
| `created_time` | `source_created_at` | col |
| `last_modified_time` | crosswalk `source_modified_at` (the fence) | xw |
| `created_date`, `created_by_name`, `created_by_id`, `last_modified_by_id` | — | raw (Zoho audit; history in `sync_payloads`) |
| `outstanding_*`, `unused_*`, `opening_balance_amount*`, `credit_limit_exceeded_amount`, `customer_currency_summaries`, `vendor_currency_summaries`, `unused_retainer_payments`, `opening_balances[]`, `portal_receipt_count` | — | **vol** (balance isolation) |
| `default_templates{}` | — | raw — deferred (0 non-blank) |
| `cards`, `checks`, `upi_mandates`, `bank_accounts`, `vpa_list`, `ach_supported`, `associated_with_square` | — | raw — deferred (0 rows; cards never) |
| approval keys (`approvers_list`, `submitted_*`, `approver_id`, `approval_*`, `note_to_approver`, `is_multi_match_approval`) | — | raw — deferred |
| `lock_details`, `lock_detail`, `locked_actions`, `contact_blocks` | — | raw (Zoho UI locks) |
| `zcrm_*`, `crm_owner_id`, `is_crm_customer`, `is_linked_with_zohocrm`, `zohopeople_client_id`, `integration_references`, `additional_information`, `registration_details`, `can_show_*`, `is_credit_limit_migration_completed`, `invited_by`, `is_client_review_*`, `contact_relation_type`, `documents[]`, `photo_url`, `tags[]`, `has_attachment` | — | raw (no integration / no data / placeholder) |

### 6.2 Contact person (`contact_persons[]`, detail only)

| Zoho key | → |
|---|---|
| `contact_person_id` | `zoho_id` + crosswalk (module `contact_persons`) |
| `salutation`, `first_name`, `last_name`, `email`, `phone`, `mobile`, `mobile_country_code`, `designation`, `department`, `skype`, `fax` | same columns |
| `is_primary_contact` | `is_primary` |
| `communication_preference.is_email_enabled` / `.is_whatsapp_enabled` | `is_email_enabled` / `is_whatsapp_enabled` |
| `is_sms_enabled_for_cp`, `is_whatsapp_disabled_by_customer` | `is_sms_enabled`, same |
| `can_invite`, `is_added_in_portal`, `is_portal_invitation_accepted`, `is_portal_mfa_enabled`, `portal_enabled_via` | same |
| `contactperson_custom_fields[]` | `extfields` (owner `contact_person`) |
| `date_of_birth`, `gender` | raw only (DPDP minimisation) |
| `photo_url`, `photo_document_url/name`, `zcrm_contact_id`, `mobile_code_formatted` | raw |

Projection (`zoho/persons.py`, the price-list items pattern): a replace-set keyed by `contact_person_id`;
matched rows updated in place (changed columns only), new ones inserted, leavers soft-deleted
(`deleted_reason='zoho:removed_from_contact'`). Each person also gets **its own crosswalk row**
(`module='contact_persons'`, `entity_table='crm.contact_persons'`), written with `upsert_record` and
tombstoned (`remote_deleted_at`) when it leaves — invoices and sales orders name contact persons by id
later, and the engine resolves references through the crosswalk only. A payload **without** the
`contact_persons` key (every list row) changes nothing.

### 6.3 Primary person

After the persons projection: `primary_contact_person_id` ← the person whose `contact_person_id =
primary_contact_id`; `''` → NULL. Exactly one `is_primary` (partial unique index). Zoho flips the
primary by updating both persons in one document; the projection clears the old flag before setting the new
one inside the flush, so the unique index never sees two.

### 6.4 Addresses → the location hub

#### 6.4.1 Shape

| Zoho | geo |
|---|---|
| `billing_address` | `place_links(owner_type='contact', link_type='billing', is_primary=true)` |
| `shipping_address` | `place_links(link_type='shipping', is_primary=true)` |
| `addresses[]` (additional) | `place_links(link_type='shipping', is_primary=false)` — Zoho's "additional address" is a delivery address in practice; `label` keeps "Additional address n" |
| `address_id` | `place_links.zoho_id` (the identity of the projection) |
| `attention` | `place_links.attention` (per owner) |
| `phone` | `place_links.contact_phone` (per owner) |
| `fax` | `places.fax` |
| `address`, `street2`, `city`, `state`, `state_code`, `zip`, `country`, `country_code`, `county` | `places.street`, `street2`, `city`, `state`, `state_code`, `postal_code`, `country`, `country_code`, `district` |
| `latitude`, `longitude` | `places.coordinates` (when both parse and are plausible), `provider='zoho'` |
| formatted | `places.formatted_address` built from the parts (trimmed: live data has `"Gujarat "`) |

#### 6.4.2 Rules

1. **Postal-empty → no place.** Every contact carries both objects with distinct ids even when empty
   (`newest` probe: shipping had only `phone`). An address whose postal parts (address, street2, city,
   state, zip, country) are all blank creates nothing; an existing link for that `address_id` is closed
   (`valid_to = now`, it is history, not deleted). Phone-only addresses are reported in the audit.
2. **Reuse within the contact only.** Billing and shipping with identical normalized text (the `gst` probe;
   your first sample) point at **one** place through two links. Places are **not** matched across contacts:
   Zoho owns this text, and an edit Zoho makes to contact A's address must never move contact B's shop.
   Cross-contact dedupe is an operator action later (verified places, geohash probe).
3. **Copy-on-write on change.** When Zoho changes an address: if the place is linked by anything other
   than this link (the sibling billing/shipping link, a visit, an invoice snapshot …), a new place is created
   and this link repointed; otherwise the place is updated in place. Verified places
   (`field_verified`) are never mutated by sync — the link is repointed to a new place and the verified one
   stays for the field team to review (`addresses.verified_place_superseded` event).
4. **Removal** (an `address_id` no longer in the document): the link is closed (`valid_to`), never deleted.
5. **Zoho-owned links:** a link with `zoho_id` refuses local PATCH / DELETE (the geo service learns the
   `zoho_owned` rule the places already have). Local links (field-verified GPS address, a second delivery
   point the rep found) are normal links with `zoho_id IS NULL`.
6. **Country:** `country_code` blank but state is Indian (sample 2) → `country='India'`, `country_code='IN'`
   when `place_of_supply` is a valid GST state code; otherwise as sent.

#### 6.4.3 Contact persons

Zoho persons carry no address; `contact_person` is already an owner type, so field teams can add one.

#### 6.4.4 Absence semantics

Only a payload that HAS `billing_address` / `shipping_address` / `addresses` touches links (the detail);
list rows carry none.

#### 6.4.5 Coordinates from custom fields

`cf_location_latitude/longitude` (95 contacts) are applied to the contact's billing (else shipping) place
**only if** both parse, lie within the organization's country bounding box (India: 6–37 N, 68–98 E) and the
place has no coordinates from a better source (geocoder, field verification). They land as
`provider='zoho_custom_field'`, `verification_status='unverified'` — never `is_verified`. Live: 7 qualify,
88 do not (valid numbers outside India) → listed by the data-quality report, never written.

### 6.5 Tax

* **Registrations** (§5.6): from the detail — `tax_info_list[]` is authoritative for GSTINs (one row per
  `tax_info_id`, `is_primary`, `place_of_supply`, legal/trade names); `gst_no` without a list entry → one
  primary `gstin` row without `zoho_id`. `pan_no` → one `pan` row (encrypted, masked, hmac). Udyam / VAT /
  tax_reg_no when non-blank. Replace-set per `(owner, registration_type)`; leavers soft-deleted.
* **Assignments:** `tax_id` → `taxes.assignment_service.replace_assignments(owner=('contact', id), source_system='zoho')`
  with the Zoho id resolved through the crosswalk (modules `taxes`, `tax_groups`) or left **pending** on
  `sync.pending_references` — exactly the categories pattern. `tax_exemption_id` → an exemption assignment.
  `tax_specification` (`intra`/`inter`) is derived per document from `place_of_supply`, not stored.

### 6.6 Accounts

`account_id` (blank on all probed rows) → `accounting.assignment_service.sync_source_assignments(
('contact', id), refs={'receivable' if customer else 'payable': account_id})`. A blank removes a previously
synced row. **To verify** on the first non-blank occurrence: whether Zoho's contact `account_id` is the
control account or a default income/expense account (the audit flags the first one with the account's type).

### 6.7 Custom fields

* **Definitions** are upserted from each payload's `custom_fields[]` metadata (they come with values):
  `zoho_field_id` (identity), `api_name`, `label`, `data_type` (→ `extfields.data_types`), `index` →
  `sort_order`, `show_in_portal`, `show_on_pdf`, `show_in_all_pdf`, `edit_on_portal`, `edit_on_store`,
  `is_active`, `is_dependent_field`; dropdown options are **learned** into `options`
  (`selected_option_id`, value, `color_code`) — Zoho sends only the selected option, so the catalogue grows
  as values are seen.
* **Values** via `custom_fields.service.sync_values(owner=('contact', id), source_system='zoho')`: typed by
  the definition's storage column (`value_text`, `value_numeric`, `value_date`, `value_boolean`,
  `value_json`). A field present with `''` clears the value; a field absent from the array is removed
  (Zoho omits empty fields — the 26 HUL fields appear only on HUL records).
* **Both shapes:** list rows carry `custom_fields[]` too (5,392 of 6,000), so values stay current even
  for contacts whose detail is still in the backlog.
* Persons: `contactperson_custom_fields[]` (empty on every probed person) → owner `contact_person`.
* The crosswalk's own flattened `custom_fields` (hstore) keeps working unchanged (`capture_custom_fields`).
* Drug-licence fields (`cf_hul_drug_license_20b/21b` + expiry, 5–9 rows) are candidates for promotion to
  `tax.tax_registrations`-like statutory licences later; they stay custom fields now.

---

## 7. Sync design

### 7.1 Contract

```python
CONTACTS_CONFIG = resolve_module_config(
    module="contacts", endpoint="/contacts", zoho_id_attr="contact_id", api="books", paginated=True,
    list_params={"filter_by": "Status.All",          # default hides 512+ inactive contacts
                 "sort_column": "created_time", "sort_order": "A"},   # stable paging, see 7.3
    strategy=SyncStrategyName.FULL,                  # INCREMENTAL only if P0.6 proves the filter
    direction=SyncDirection.INBOUND,
    detail_required=True, index_then_detail=True, detail_dispatch="inline",
    detail_max_age_minutes=0,                        # the list timestamp covers persons/addresses — P4 sampling verifies
    max_details_per_run=250,                         # E3
    modified_since_param=None, sort_column=None,
    soft_delete_missing=True,                        # + E6 confirm-by-detail before tombstoning
    sync_interval_minutes=30, weekly_full_enabled=False,
    wait_between_calls=2.0,                          # ≤ 30/min: the observed code-43 block came at ~54/min
    hash_volatile_keys=VOLATILE_KEYS,                # *_formatted, balances, summaries, portal_receipt_count …
    field_map=FIELDS,
    contract=SyncContract(
        source_system="zoho", entity_table="crm.contacts", crosswalk=True,
        match_on=("zoho_id",), identity_echo=("zoho_id",),
        history_raw=True, capture_custom_fields=True,
        redactions=REDACTIONS,                        # E2: pan_no → {masked, hmac}
        owned_fields=ZOHO_OWNED_CONTACT_FIELDS,
        references=(
            ReferenceRule(attr="currency_id", module="currencies", fk="currency_id", on_missing=OnMissing.DEFER),
            ReferenceRule(attr="pricebook_id", module="price_lists", fk="price_list_id", on_missing=OnMissing.DEFER),
        ),
    ),
)
```

### 7.2 One record, in order (`hooks.after_contact_upsert`)

Every step is a no-op unless its key is in the payload (absence ≠ emptiness), runs inside the record's
savepoint, and is idempotent:

1. `payment_terms_id` / `payment_terms` / label → learn `crm.payment_terms`, set `payment_term_id` (list + detail)
2. `owner_id` → `owner_zoho_user_id` (list + detail)
3. `custom_fields[]` → definitions + values (list + detail)
4. `contact_persons[]` → persons + child crosswalk; then `primary_contact_id` (detail)
5. addresses → places + links (detail)
6. `cf_location_*` → coordinates of the billing/shipping place (after 5)
7. `tax_info_list` / `gst_no` / `pan_no` / udyam → `tax.tax_registrations` (detail)
8. `tax_id` / `tax_exemption_id` → tax assignments (detail)
9. `account_id` → account assignment (detail)
10. `cf_merged_customer_ids` → merge redirect (§7.8)

### 7.3 Why `created_time` ascending

A full scan pages through 8,212 rows over ~42 calls. Sorted by `contact_name` (the default) or
`last_modified_time`, an edit made mid-scan moves a row to another page — it is listed twice or **not at
all**, and `soft_delete_missing` would tombstone a live contact (whose next listing is then fenced as
"older than tombstone"). `created_time` ascending is stable under edits; new contacts append at the end.
Deletions can still shift rows up → E6.

### 7.4 Budget — first sync and steady state

| Phase | Calls | Notes |
|---|---|---|
| First list scan (index) | 42 | All 8,212 contacts exist after this with names, phones, GST state, payment terms, owner, custom fields, PAN (redacted) — searchable at once |
| First detail completion | 8,212 | persons, addresses, registrations, tax, price list. At 250/run × every 30 min ≈ 12,000/day theoretical — **bounded by the daily budget** |
| Steady state | ≈ 42 per full scan + ≈ 50–120 details/day | full scan every 6 h = 168 calls/day; INCREMENTAL (if P0.6 passes) ≈ 1 call per run |

**Daily budget:** set `ZOHO_DAILY_HARD_LIMIT` to the plan's real cap minus headroom for the other modules
and Zoho's own UI traffic (the per-org limit counts both). With a 5,000/day plan and a 2,000/day contacts
allowance the first completion takes ~4–5 days; contacts are usable from hour one (index phase) and the
detail lane prioritises (E3) **active customers by most recent change**, so the ones people work with
complete first.

### 7.5 Engine prerequisites (P0)

| # | Change | Why contacts need it |
|---|---|---|
| E1 | **Progress-preserving rate limits.** On a 429 the run commits what it applied, records `stop_reason='rate_limited'`, honours `Retry-After`, and yields — instead of rolling the whole run back | Today one 429 discards an entire run (observed 2026-10-08); at 8,212 details the first sync would never converge |
| E2 | **Contract redactions.** `SyncContract.redactions`: per key path, replace the value **before** hashing and before it reaches `sync_records.raw`, `sync_payloads.raw`, event diffs and logs — `pan_no` → `{"masked": "ABCDE****F", "hmac": "…"}` (deterministic, so a PAN change still changes the hash). The hook reads the clear value from the in-memory payload only | Otherwise encrypting the column is theatre: two raw-JSON tables and the logs would hold every PAN in clear |
| E3 | **Detail completion lane.** Crosswalk rows still holding a list-shaped raw (`raw_source LIKE 'list:%'`) or stale beyond `detail_max_age_minutes`, ordered by priority (active first, `source_modified_at` desc), up to `max_details_per_run` per run, independent of the list page | Per-page detail backlogs make 42 pages × 200 details one indivisible job; the lane makes completion budgeted, resumable and prioritised. Items / invoices will need the same |
| E4 | **`LinkState.MERGED`.** A crosswalk row may point a retired external id at the survivor (`link_state='merged'`); `resolve_many` resolves it like `linked`; `crosswalk_live_ids` (the tombstone set) **excludes** it | Without the exclusion, a merged id missing from the list would tombstone the **survivor** |
| E5 | **Child crosswalk helper.** `crosswalk.upsert_child(module, external_id, entity)` / `tombstone_child(...)` for hook-projected children with their own Zoho ids | Contact persons today; line items later |
| E6 | **Confirm before tombstoning.** For modules that opt in, each id missing from a complete scan is confirmed with a detail GET (`404` / Zoho "does not exist" → tombstone; found → it was a paging artefact, re-apply it). Deletions are rare (~0–5 per scan), so this costs little | Paging under concurrent deletes (7.3) |
| E7 | **Incremental, only if proven.** P0.6 probes whether `GET /contacts?last_modified_time=…` filters (read-only). If yes → INCREMENTAL like categories (with its `+0000` quirk). If not → keep FULL every 6 h (168 calls/day — affordable) | Docs do not document the filter; never assume |
| E8 | `max_details_per_run`, `daily_detail_budget` knobs (control plane, no deploy) | Tunable first sync |

Plus `app/common/security/pii.py`: SQL expressions `encrypt(value)`, `hmac(value)`, `mask_pan(value)` on
pgcrypto (`pgp_sym_encrypt`, `hmac(…, 'sha256')`) — the platform's existing pattern for the Zoho refresh
token — with `PII_ENCRYPTION_KEY` and `PII_HMAC_KEY` (separate keys; rotation = re-encrypt job keyed by a
`key_version` in `verification_data`/`details`). `kyc.pan_verifications.pan_number_encrypted` and
`hr.bank_accounts.account_number_encrypted` (declared, never written today) adopt the same helper.

### 7.6 PII handling summary

| Data | Where | How |
|---|---|---|
| PAN | `tax.tax_registrations` | encrypted + masked + hmac; never in raw / history / events / logs (E2); reveal = `tax.registration:reveal`, audited |
| GSTIN | `tax.tax_registrations.registration_number` | clear — a public identifier (note: it embeds the PAN for 222 of 224 PAN holders; the PAN column policy still holds for the 2 that differ and for individuals) |
| Mobile, email, phone | `crm.contacts`, `crm.contact_persons` | clear — operational (calls, WhatsApp); in scope of DPDP export/erasure requests via `compliance` later |
| DOB, gender | raw only | not promoted (no use) — candidates for redaction too if the owner prefers |
| Consent | `crm.contacts.consent_agreed/consent_at` | Zoho-fed |

### 7.7 Deletion and inactivity

* Inactive in Zoho → `status='inactive'` (listed with `Status.All`; never tombstoned).
* Deleted in Zoho → missing from a complete scan → confirmed by E6 → `remote_deleted_at` on the crosswalk +
  `deleted_at` on the contact; persons, registrations and assignments stay as they were (unreachable
  through a deleted contact), addresses' links closed. Guards: `ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING`, mass-delete
  ceiling.

### 7.8 Merges

THPL records Zoho merges as `cf_merged_customer_ids = "<id>,<id>"` on the survivor (151 contacts). For each
retired id:

* crosswalk row exists (we synced it before the merge) → its contact gets `merged_into_contact_id =
  survivor`, is soft-deleted (`deleted_reason='zoho:merged'`), its crosswalk row is repointed to the
  survivor with `link_state='merged'`;
* no crosswalk row (merged before our first sync) → insert one (`module='contacts'`, `external_id` = retired
  id, `entity_id` = survivor, `link_state='merged'`).

Any later document naming a retired contact id (an old invoice re-synced) resolves to the survivor. The
convention is THPL's, so the custom field's api name is configuration (`contacts.merge_alias_field`), not
code.

### 7.9 Local edits

INBOUND: Zoho-owned columns (every translator-readable field + `currency_id`, `price_list_id`,
`payment_term_id`, `primary_contact_person_id`, `owner_zoho_user_id`, `merged_into_contact_id`) refuse local
PATCH with `422 zoho_owned_field`. Ours to edit: `customer_sub_category`, verification, media, documents,
comments, local addresses, local custom fields (definitions without `zoho_field_id`), `contact_persons.user_id`.
`service.to_zoho_payload` is the seam the outbox will use (create/update contact, persons, addresses).

---

## 8. API (mounted at `/api/contacts`)

| Endpoint | Who | What |
|---|---|---|
| `GET /` | `crm.contact:read` | Slim list: `type`, `status`, `sub_type`, `sub_category`, `price_list`, `payment_term`, `place_of_supply`, `has_gstin`, `q` (name / company trigram, last-10-digit phone, exact GSTIN via hmac), cursor pagination |
| `GET /{ref}` | read | Fat: persons, addresses (with places), registrations (**masked**), payment term, price list, currency, owner, custom fields, tax/account assignments, media/document counts |
| `PATCH /{ref}` | `crm.contact:update` | Local fields only (`row_version` required → 409) |
| `POST /{ref}/verify` | `crm.contact:manage` | Counterparty verification (VerificationMixin) |
| `GET /{ref}/persons` · `GET /persons/{ref}` · `PATCH /persons/{ref}` | read / `crm.contact_person:update` | Local fields only (`user_id`) |
| `POST|DELETE /{ref}/media/{collection}` · same for persons | update | Owner endpoints (media doctrine) |
| `GET|POST|PATCH|DELETE /sub-categories` | `crm.sub_category:*` | The vocabulary |
| `GET /payment-terms` | read | Learned terms |
| `GET /data-quality` | manage | Postal-empty addresses, phone-only addresses, implausible coordinates, malformed GSTIN/PAN from Zoho, contacts without persons, unresolved pending references |
| `POST /tax/registrations/{ref}/reveal` | `tax.registration:reveal` | Decrypts one PAN; writes an audit event |

Addresses (`/api/addresses?owner_type=contact&owner_id=`), documents, comments and custom-field values use
their existing APIs — the registrations in §4.4 are what open them to contacts.

---

## 9. Tests

* **Hermetic:** translator on the three live shapes (list row, customer detail, vendor detail) — no Zoho
  name leaks, `''` → NULL, absent ≠ NULL; redaction (PAN never in the persisted raw, hash still changes on a
  PAN change); payment-term learning incl. `-3` and label variants; address normalization (trim, empty
  detection, India inference); coordinate plausibility; merge-id parsing.
* **Database:** composite scope FKs (a person under another organization's contact is impossible), one
  primary person, deferred primary pointer, PAN CHECKs (clear PAN refused, encrypted GSTIN refused),
  registration owner-scope trigger, copy-on-write addresses (sibling link keeps its place; verified place
  never mutated), replace-sets (persons, registrations, links) with soft delete, custom-field definition +
  option learning.
* **End to end** (`tests/zoho_core/test_masters_e2e.py` wire, live-shaped fixtures with anonymised data):
  list → index rows → detail lane completes them; persons + child crosswalk; addresses; tax assignment
  pending until taxes sync then linked by reconcile; price list DEFER; merge redirect (an invoice-like
  reference to a retired id resolves to the survivor; the survivor is NOT tombstoned); E1 (429 mid-run keeps
  progress); E6 (a row missing from one scan but present on detail is not tombstoned).
* **Planner** tests' concurrency caps stay ≥ registered modules (the price-lists trap).

---

## 10. Phases

| Phase | Content | Exit criterion |
|---|---|---|
| **P0** | E1–E8, `pii.py`, P0.6 read-only probe of the `last_modified_time` filter on `/contacts`, `ZOHO_DAILY_HARD_LIMIT` set to the plan's cap | Engine tests green; probe result recorded |
| **P1** | Mixins (§4), schema + migration (§5), registrations, RBAC, models; accounts / price lists adopt `HasCurrencyMixin` | up → down → up on a seeded scratch DB; zero drift |
| **P2** | Adapter: fields, redactions, hooks (§7.2), persons, addresses, registrations, custom fields, merges | Hermetic + DB + e2e tests green |
| **P3** | API + search + data-quality report | API tests incl. organization isolation |
| **P4** | Live on dev: index scan (42 calls) → detail lane under budget → population audit against live Zoho (the price-lists method: every cell equal or a NULL that mirrors a blank; every key stored or on the not-stored list) on a 200-contact random sample (200 calls) → drift sampling: re-fetch 100 contacts whose timestamp has not moved and diff persons/addresses (decides `detail_max_age_minutes`) | 0 problems; drift decision recorded |
| **P5** | Deferred items as data appears: templates, bank accounts / mandates, approvals, branches, Zoho tags, attachments import, outbound | — |

---

## 11. Decisions I need from you

1. **Zoho plan / daily cap.** Which Zoho Books plan is THPL on (daily API limit)? It sets
   `ZOHO_DAILY_HARD_LIMIT` (now 45,000 — above every documented cap) and the first-sync pace.
2. **`customer_sub_category` vocabulary.** Which values (e.g. chemist, hospital, clinic, nursing home,
   wholesaler, stockist, modern trade …)? Should they be seeded from `cf_hul_channel` / `cf_hul_category`
   where present?
3. **PII policy.** OK to store PAN encrypted (+ reveal permission) and to keep date of birth / gender out of
   columns (raw only, or redact them from raw too)?
4. **Merge field.** Confirm `cf_merged_customer_ids` is "ids merged INTO this contact" (two ids per row).
5. **Additional addresses.** Treat Zoho's `addresses[]` as additional *shipping* addresses (proposed) or a
   neutral `other`?

## 12. Risks

| Risk | Mitigation |
|---|---|
| Rate-limit blocks during the first completion (observed code 43 at ~54/min) | 2 s pacing, E1, E3 budget, daily cap |
| Child edits that do not move the contact timestamp | P4 drift sampling decides `detail_max_age_minutes` |
| Zoho address edits shared by two owners | Reuse within one contact only + copy-on-write |
| PAN exposure through raw JSON / logs | E2 redaction before persistence; CHECKs forbid a clear PAN column value |
| Mis-tombstoning under paging | `created_time` sort + E6 confirm-by-detail |
| Merge chains (A→B, B→C) | Redirect resolves transitively at write time (`merged_into` of the survivor is followed) |

---

## 13. As built — first live sync (THPL, dev)

_Filled in when the first full sync completes._
