# The sync architecture — how a Zoho record becomes one of ours

**Status:** implemented (currencies, organizations, taxes) · **Postgres:** 18
**Design rationale:** [`implementation-plan/sync-crosswalk-redesign.md`](implementation-plan/sync-crosswalk-redesign.md)

This is the operator's and implementer's guide: what the pieces are, what a
record's journey looks like end to end, and how to add the next module. The
*why* — the alternatives weighed, the failure modes, the review findings — lives
in the redesign plan.

---

## 1. The shape, in one picture

```
      Zoho ──────────────► connector ──► engine ──► translator ──► our tables
   (or SAP)                (HTTP, auth,   (gate,     (meaning)      (canonical)
                            retries)      batching)                      │
                                              │                          │
                                              ▼                          ▼
                                     sync.sync_records          currency.currencies
                                     (identity + state)         org_management.organizations
                                              │                 tax.tax_components (+5)
                                              ▼
                                     sync.sync_payloads
                                     (history, monthly partitions)
```

Four rules hold everywhere:

1. **One canonical table per concept.** No `zoho_*` mirror tables. A currency is
   a currency, whether Zoho, SAP or an operator produced it.
2. **Identity lives in the crosswalk.** `sync.sync_records` maps
   `(tenant, source, module, external_id)` → a local row. Adding a second source
   is rows in that table, not columns on yours.
3. **Sync state is not business data.** Raw payload, hash, version, tombstone
   and provenance live on the crosswalk row, never on the entity.
4. **Nothing reads a source payload directly.** A translator per module is the
   only place that knows what `currency_format` means.

---

## 2. The tables

### `sync.sync_records` — the crosswalk (hot)

One row per external record. `PARTITION BY LIST (source_system)`.

| column | what it is |
|---|---|
| `source_system`, `module`, `external_id` | who the record is upstream (partition key first) |
| `entity_table`, `entity_id`, `link_state` | which local row it is |
| `source_modified_at`, `raw_hash`, `raw_source` | what the apply gate decides on |
| `raw` | the current richest document (lz4) — replay reads this |
| `remote_deleted_at` | the sync's tombstone; fences resurrection |
| `sync_version`, `synced_at`, `first_seen_at` | bookkeeping |
| `custom_fields`, `comments` | opt-in capture, JSONB |

`uq_sync_records_identity (tenant_id, source_system, module, external_id)` is
the identity constraint and the conflict target of the guarded upsert.

### `sync.sync_payloads` — history (cold)

One row per applied **change** — never per scan. `PARTITION BY RANGE (synced_at)`,
monthly, retention by partition drop. `history_raw=False` on a high-volume module
keeps the hash and changed-field list without the document.

### The canonical masters

| table | module | notes |
|---|---|---|
| `currency.currencies` + `currency.exchange_rates` | `app/modules/currencies` | rates are effective-dated; the column on the currency is a cache |
| `org_management.organizations` | `app/modules/organizations` | Zoho orgs are root nodes of the tenant tree |
| `tax.tax_components` + 5 more `tax.*` tables | `app/modules/taxes` | taxes and tax groups in one table, group members, exemptions, organization grants, defaults, treatment vocabulary — see [`adapters/taxes.md`](zoho-sync-implementation/adapters/taxes.md) |

Currencies and organizations carry a `zoho_id` **echo**: written by the engine
on every apply, never matched on. It exists because `Organization.org_code`
derives from it and "what does Zoho call this row" is a constant question. The
crosswalk stays the identity of record. **The tax tables carry no echo at all**
(§2.3 of the redesign: new modules do not get one) — `service.sources_for` and
`GET /api/taxes/{zoho id}` read the crosswalk instead.

Dropping the echo removed an accidental safety net: its unique index used to
reject a second payload for the same id inside one page. The engine now handles
that itself — a repeat waits for the first flush and is applied as an update
(`_apply_page`, crosswalk modules only).

---

## 3. A record's journey

### 3.1 Index, then detail

Zoho's list endpoints are thin. The engine writes the listed row **first**, then
completes it from the detail document:

```
GET /settings/taxes                     ──► 2 listed rows
  apply(index)   → INSERT tax.tax_components, INSERT sync.sync_records   (created)
GET /settings/taxes/982000000566009     ──► the full document
  apply(detail)  → UPDATE tax.tax_components, UPDATE sync.sync_records   (updated)
```

Why this order: the row exists the moment it is listed, so a detail call that
fails, is rate-limited or is queued no longer leaves a hole where a record
should be — and anything resolving a reference to it finds it immediately.

Enabled with `index_then_detail=True` (requires `detail_required=True`). The
registry refuses the combination without it.

**The exception:** currencies sets `detail_required=False`.
`GET /settings/currencies` already returns every documented attribute, so a
detail call per currency would spend quota to learn nothing. Modules whose list
is genuinely thin (organizations, taxes) use the two-phase flow.

### 3.2 The apply gate

Every payload asks `decide()` first (`app/modules/zoho/sync/apply.py`). It is
pure, so its whole decision table is unit-tested:

| situation | outcome |
|---|---|
| no crosswalk row | `inserted` |
| tombstoned, payload not newer | `stale_ignored` |
| tombstoned, payload newer | `resurrected` |
| payload older than stored version | `stale_ignored` |
| same version, same hash | `unchanged` — no UPDATE, no WAL, no CDC churn |
| same version, thinner payload | `unchanged` |
| **undated and thinner than stored** | `unchanged` |
| otherwise | `updated`; `raw` replaced only if at least as rich |

That last rule is what makes the two-phase flow free in the steady state. A thin
index row carrying no `last_modified_time` never hash-matches the stored detail
document, so without it the row would be rewritten on every scan forever.

### 3.3 Write order

The crosswalk is written **before** the entity. Its guarded upsert is what
fences a stale lane:

```sql
INSERT INTO sync.sync_records (…) VALUES (…)
ON CONFLICT (tenant_id, source_system, module, external_id) DO UPDATE
SET … , sync_version = sync.sync_records.sync_version + 1
WHERE  EXCLUDED.source_modified_at IS NULL
   OR  sync.sync_records.source_modified_at IS NULL
   OR  EXCLUDED.source_modified_at >= sync.sync_records.source_modified_at
RETURNING id, sync_version;
```

No rows returned ⇒ another lane applied something newer ⇒ we count
`stale_ignored` and leave the entity alone. Writing the entity first would let
the loser corrupt business columns before discovering it had lost.

### 3.4 Reference resolution

A payload that carries only a foreign id is resolved through the crosswalk —
one indexed lookup, and one query for a whole page across *every* referenced
module:

```sql
SELECT module, external_id, entity_table, entity_id
FROM   sync.sync_records
WHERE  tenant_id = $1 AND source_system = 'zoho'
  AND  (module, external_id) IN (('currencies','982000000004000'), ('taxes','98…'));
```

Live example: the organization payload carries `currency_id: "982000000004000"`;
`organizations/zoho/hooks.py:link_currency` turns that into
`organizations.currency_id = 2`. A miss is not an error — `zoho_currency_id`
stays on the row and the next run links it.

---

## 4. The translation layer

`app/modules/sync/translation.py`. The anti-corruption boundary, in both
directions.

**The rule everything turns on: the write direction is never the inverted read
direction.** Zoho's own contract forbids it:

| currency field | direction | why |
|---|---|---|
| `currency_code`, `currency_format` | both | required on create |
| `currency_symbol`, `price_precision` | both | optional create/update arguments |
| `currency_name` | **in** | Zoho *computes* it (`"AUD- Australian Dollar"`) |
| `is_base_currency` | **in** | organization settings derive it |
| `exchange_rate`, `effective_date` | **in** | written through `/exchangerates` |

So a `FieldSpec` declares a `direction` (IN / OUT / BOTH) and a `Codec` whose
`decode` and `encode` are written separately.

```python
F(external="tax_percentage", local="tax_percentage", codec="decimal",
  direction=Direction.BOTH, required_on_create=True)
```

* **Shape** (INDEX / DETAIL / NESTED / WEBHOOK) — a key the source did not send
  is *skipped*, never decoded to NULL, so a thin row cannot erase a rich one.
* **Intent** (CREATE / UPDATE) — a create missing a required argument is refused
  here, with the field named, rather than spent as a call Zoho will reject.
* **Failure is asymmetric on purpose** — decoding never raises (a bad field is
  dropped into `Decoded.warnings`; one attribute must not cost the record);
  encoding raises, because we are about to make an outbound call.

Codecs are validated at boot: an unregistered codec name fails the process
rather than silently passing raw values through.

### Outbound

```python
service.to_zoho_payload(currency, create=True)
# {'currency_code': 'SGD', 'currency_symbol': 'S$',
#  'price_precision': 2, 'currency_format': '1,234,567.89'}
```

Read-only attributes are structurally excluded. The HTTP *dispatch* is not built
yet (there is no command outbox); this function is the seam it will call.

---

## 5. Worked example — what actually happened

From `.dev_sync_run.sh` against an empty database. Abridged; run it yourself to
reproduce.

### 5.1 Zoho sends

```jsonc
// GET /settings/currencies  (list — complete, no detail needed)
{ "currency_id": "982000000004012", "currency_code": "AUD",
  "currency_name": "AUD- Australian Dollar", "currency_symbol": "$",
  "price_precision": 2, "currency_format": "1,234,567.89",
  "is_base_currency": false, "exchange_rate": 54.12,
  "effective_date": "2026-09-01" }

// GET /settings/taxes  (list — THIN)
{ "tax_id": "982000000566009", "tax_name": "GST18",
  "tax_percentage": 18, "tax_type": "tax", "tax_specific_type": "igst" }

// GET /settings/taxes/982000000566009  (detail — the rest of the truth)
{ "tax_id": "982000000566009", "tax_name": "GST18", "tax_percentage": 18.0,
  "tax_type": "tax", "tax_specific_type": "igst", "tax_factor": "rate",
  "tds_payable_account_id": "132086000000107337",
  "tax_authority_id": "460000000066001",
  "tax_authority_name": "Illinois Department of Revenue",
  "is_value_added": false, "is_default_tax": true, "is_editable": true,
  "country": "India", "country_code": "IN",
  "tax_account_id": "982000000000388",
  "purchase_tax_account_id": "982000000000390",
  "output_tax_account_name": "Output CGST",
  "purchase_tax_account_name": "Input CGST",
  "purchase_tax_expense_account_id": 982000000000392 }

// GET /organizations/10229182  (detail)
{ "organization_id": "10229182", "name": "Zillium Inc",
  "fiscal_year_start_month": "april",          // documented as 0–11, sent as a name
  "currency_id": "982000000004000",            // a REFERENCE, not a value
  "field_separator": " ",
  "address": { "street_address1": "14 Main St", "city": "Palo Alto",
               "state": "CA", "zip": "94301", "country": "U.S.A" },
  "custom_fields": [ { "api_name": "cf_zone", "value": "West" } ], … }
```

### 5.2 Run reports

```
RUN 1 — first sync (cold)
  currencies     created=2 updated=0 unchanged=0 errors=0
  organizations  created=1 updated=1 unchanged=0 errors=0   ← index, then detail
  taxes          created=2 updated=2 unchanged=0 errors=0   ← index, then detail

RUN 2 — identical payloads
  currencies     created=0 updated=0 unchanged=2 errors=0   ← no writes, no history
  organizations  created=0 updated=0 unchanged=2 errors=0
  taxes          created=0 updated=0 unchanged=4 errors=0

RUN 3 — Zoho changes a rate and a tax percentage
  currencies     created=0 updated=1 unchanged=1 errors=0
  taxes          created=0 updated=1 unchanged=3 errors=0
```

### 5.3 What landed

```
currency.currencies
  id=1  code=AUD  name=AUD- Australian Dollar  zoho_id=982000000004012  rate=58.90
  id=2  code=INR  name=INR- Indian Rupee       zoho_id=982000000004000  base=True

currency.exchange_rates          ← the inline rate became effective-dated history
  currency_id=1  rate=58.900000  date=2026-09-01  source=zoho
  currency_id=2  rate=1.000000   date=2013-09-04  source=zoho

org_management.organizations
  id=2  org_code=ZOHO-10229182  zoho_id=10229182      ← org_code derived from the echo
    address=14 Main St, Palo Alto, CA 94301 (U.S.A)   ← DETAIL-only, dotted paths
    fiscal_year_start_month=3                         ← "april" decoded by month_index
    date_format='dd MMM yyyy'  field_separator=None   ← " " normalised to NULL
    currency_id=2 (resolved)  zoho_currency_id=982000000004000

tax.tax_components                                    (dev-run output from before the tax schema
  id=1  GST18  20.0000  igst  zoho_id=982000000566009   redesign — the row no longer has a zoho_id;
                                                        that lives on the crosswalk line below)
    authority='Illinois Department of Revenue' (460000000066001)  country=India/IN
    accounts: tax=982000000000388  purchase=982000000000390
              tds=132086000000107337  expense=982000000000392   ← DETAIL-only
    flags: value_added=False default=True editable=True factor=rate

sync.sync_records — the crosswalk
  zoho/currencies     982000000004012  -> currency.currencies#1            v2  list:full
  zoho/organizations  10229182         -> org_management.organizations#2   v2  detail_fetch
  zoho/taxes          982000000566009  -> tax.tax_components#1             v3  detail_fetch

sync.sync_payloads — history (10 rows for 3 runs over 5 records)
  currencies     982000000004012  inserted  v1  (12 fields)
  organizations  10229182         inserted  v1  (3 fields)     ← what the index knew
  organizations  10229182         updated   v2  (27 fields)    ← what the detail added
  taxes          982000000566009  inserted  v1  (5 fields)
  taxes          982000000566009  updated   v2  (14 fields)
  taxes          982000000566009  updated   v3  (1 field)      ← the percentage change
```

Note `raw_source=detail_fetch` on the two-phase modules: the richer payload won
provenance, so the stored `raw` is the full document, not the index row.

### 5.4 Field coverage

```
[OK] currencies     zoho keys=9   mapped=8   columns filled=8/8
[OK] organizations  zoho keys=26  mapped=24  columns filled=28/29
[OK] taxes          zoho keys=19  mapped=18  columns filled=18/18
```

Unmapped keys are the module's own id (it lives in the crosswalk), `address`
(flattened through dotted paths) and `custom_fields` (captured whole onto
`sync_records.custom_fields`). The one unfilled organization column is
`field_separator`: Zoho sent `" "`, which normalises to NULL.

---

## 6. Adding a module

1. **Canonical model** — business columns, a `zoho_id` echo, no mirror columns.
   A migration creating the table (see `f84b5c2e60a7` for taxes).
2. **`<module>/zoho/fields.py`** — a `FieldSpec` per attribute with an explicit
   `direction`. Read Zoho's *create* argument table, not just the attribute
   table: that is what distinguishes BOTH from IN.
3. **`<module>/zoho/spec.py`** — `resolve_module_config(...)` with a
   `SyncContract`:

```python
contract=SyncContract(
    source_system="zoho",
    entity_table="tax.tax_components",
    match_on=(),                 # a business key, or () to never merge sources
    crosswalk=True,
    # identity_echo=("zoho_id",) only if a column must be readable without a join
    owned_fields=ZOHO_OWNED_TAX_FIELDS,   # derived from translator.readable
)
```

4. **`<module>/zoho/__init__.py`** — `sync_registry.register(SPEC)`, and add the
   package to `_ADAPTER_PACKAGES`.
5. **Wiring** — `alembic/env.py` (`_OWNED_SCHEMAS`, model import),
   `tests/conftest.py` (`_TEST_TABLES`), `app/router.py`.

The registry validates all of it at **boot**: unknown columns, unknown codecs, a
mis-declared `entity_table`, `index_then_detail` without `detail_required`, a
reference to an unregistered module. A broken spec fails the process, not a
worker at 03:00.

`crosswalk=False` (the default) keeps a module on the legacy in-place mirror —
`locations` and `zoho_users` still are — so conversion is one module per PR.

---

## 7. Operating it

### Rebuilding a development database

```bash
bash .dev_reset_db.sh                 # drop every app schema, replay all migrations
.venv/bin/python scripts/seed.py      # reference data, document types, company tenant
bash .dev_sync_run.sh                 # sync currencies + organizations + taxes
```

**Do not run `scripts/seed.py` against the database pytest uses.** The company
seeder repurposes the migration's `default` tenant (id 1) as the deployment's
own — `THPL`, say. `tests/conftest.py` then deletes "every tenant whose code is
not `DEFAULT_TENANT_CODE`", which is now that tenant, and ~56 tests fail on an
IntegrityError with no tenant to write into. Seeded database and test database
are different databases by contract: the suite wants *migrated*, not *seeded*.

`scripts/seed.py` runs on asyncpg. `requirements.txt` removed psycopg2
deliberately, so the seeders take a sync `Connection` obtained from
`AsyncConnection.run_sync` rather than building a sync engine they cannot
create.

| task | how |
|---|---|
| reset the dev database | `bash .dev_reset_db.sh` — drops every app schema, rebuilds from migration zero |
| see a sync end to end | `bash .dev_sync_run.sh` — real engine, stubbed HTTP, prints the rows |
| retention | nightly `run_maintenance`; both history tables, policy rows in `zoho_retention_policies` |
| "what does Zoho call this row?" | `service.sources_for(db, row)` — reads the crosswalk |
| "why did this change?" | `sync.sync_payloads` for the record, `zoho_sync_events` for the diff |

### Known costs, accepted deliberately

* **One guarded upsert per written record.** It cannot be batched: a rejected
  row returns no `RETURNING` row to map back. Only *writers* pay it; a
  steady-state scan is almost all no-ops. Pinned by
  `test_a_crosswalk_page_preloads_once_and_upserts_per_written_record`.
* **Two page-level crosswalk reads** for `detail_required` modules —
  `_stored_versions` and the gate preload read the same rows. A known dedup
  opportunity, pinned at two so it cannot drift upward.
* **One entity load per writer.** The page preload deliberately fetches gate
  columns plus `deleted_at`, not whole entities, because most payloads in a
  steady-state scan never touch the entity.

### Things that will bite if you forget them

* The crosswalk upsert runs inside `no_autoflush`. Without it, the Core
  statement autoflushes the page's pending entity INSERTs one at a time and
  `insertmanyvalues` silently degrades to N round trips.
* `crosswalk.load_page` needs `include_deleted=True`. The soft-delete criteria
  turns its `LEFT JOIN` into an inner one, a crosswalk row whose entity is
  soft-deleted drops out entirely, and the engine inserts a duplicate.
* `raw_source` belongs inside the `write_raw` branch. Written unconditionally, a
  thin index row stamps `list:index` over a stored detail document and the
  provenance rank stops protecting it.
* A FK pointing at an old mirror table survives a green test suite. `run the
  sync` is what found `fk_organizations_currency` still referencing
  `zoho_currencies`.
