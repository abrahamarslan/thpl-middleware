# Zoho Architecture Decision Framework

**Normalized columns vs JSONB documents for the two-way Zoho mirror — the
decision, the reasoning, and the patterns that make bidirectional sync
reliable.**

This document answers one question in depth:

> When we ingest Zoho API responses (nested, asymmetric, partially
> undocumented), should we normalize them into relational tables, dump them
> into JSONB, or something else — given that everything we change locally
> must be pushed back to Zoho in the exact shape Zoho expects?

**The decision, stated up front:**

> **Neither pure normalization nor pure JSONB. Use a *typed projection over
> a raw document* — a hybrid where every mirror row stores (a) the full
> untouched Zoho payload in JSONB (`zoho_raw`), (b) a curated set of typed,
> indexed columns extracted per module by a declarative field map, (c)
> child tables only for collections we own or query relationally, and (d)
> hstore for custom fields. Outbound writes are built from Zoho's *write
> contract* (the documented create/update arguments), never by
> reconstructing the read document.**

This is not a compromise; it is the architecture that the requirements
force, and §3 proves it by elimination. The sync engine in
`app/modules/zoho/sync/` already implements ~80% of it (see
[ZOHO_SYNC_ENGINE.md](ZOHO_SYNC_ENGINE.md)); §5 maps decision → existing
code and §12 lists what remains to build.

---

## Table of contents

1. [The problem, precisely stated](#1-the-problem-precisely-stated)
2. [A taxonomy of Zoho response fields](#2-a-taxonomy-of-zoho-response-fields)
3. [The three candidate architectures, evaluated](#3-the-three-candidate-architectures-evaluated)
4. [The decision framework — a per-field decision tree](#4-the-decision-framework)
5. [How this maps onto the existing sync engine](#5-mapping-to-the-existing-engine)
6. [Ownership classes — who is the author of a record?](#6-ownership-classes)
7. [The outbound problem: read model ≠ write model](#7-read-model--write-model)
8. [Worked examples, end to end](#8-worked-examples)
9. [Two-way sync correctness: conflicts, echoes, idempotency](#9-two-way-sync-correctness)
10. [Freshness: seeing Zoho stock changes "instantly"](#10-freshness)
11. [Pattern glossary](#11-pattern-glossary)
12. [Per-module decision table & implementation roadmap](#12-per-module-decisions--roadmap)
13. [Anti-patterns — the never-do list](#13-anti-patterns)

---

## 1. The problem, precisely stated

### 1.1 What a Zoho response actually is

Every Zoho Books/Inventory response is an **envelope** around one of two
shapes:

```
{ "code": 0, "message": "success", "<plural>":  [ …index rows… ], "page_context": {…} }   ← GET /{module}
{ "code": 0, "message": "success", "<singular>": { …full document… } }                     ← GET /{module}/{id}
```

The core client (`zoho/core/client.py`) already strips the envelope and
exposes `ZohoResponse(data, page_context)`. What lands in the sync engine
is the index row or the full document.

### 1.2 The list/detail asymmetry (the N+1 shape)

The same entity has **two different representations depending on which
endpoint returned it**, and neither is a subset of the other in a clean
way:

| | `GET /contacts` (index row) | `GET /contacts/{id}` (document) |
|---|---|---|
| Scalar business fields | subset (`contact_name`, `mobile`, `gst_no`, …) | superset (`pricebook_id`, `branch_name`, `notes`, …) |
| Custom fields | full array **+ promoted `cf_*` keys + `custom_field_hash`** | array + hash (sometimes empty when index had values — different snapshot times) |
| Nested entities | shallow (`tags: []`, `registration_details: {}`) | deep (`contact_tax_information`, `contact_persons`, `billing_address`, `customer_currency_summaries`, `default_templates`, …) |
| Aggregates | `outstanding_receivable_amount` etc. present | present, plus opening-balance variants |

The same asymmetry exists for organizations (your example): the index row
carries `plan_name`, `other_active_services`, `org_joined_app_list`; the
document carries `address`, `date_format`, `tax_settings`, `industry_type`
— **each endpoint has fields the other lacks.**

Two consequences drive the whole design:

1. **A row must be constructible from either shape.** The engine's
   `detail_required` / `detail_dispatch` knobs decide whether to pay the
   N+1 detail fetch; the mapper's *missing-key-is-skipped* rule
   (`mapper.py`: `MISSING` sentinel) guarantees a thin index payload can
   refresh a row without NULLing out columns only the detail payload
   carries. This is why **every business column is nullable by doctrine**.
2. **"The full record" is a moving target.** Zoho adds fields
   continuously, regionally (India-only `item_tax_preferences`,
   Mexico-only `sat_item_key_code`), and inconsistently. Any design that
   requires enumerating all fields up front loses data the day Zoho ships
   a new one.

### 1.3 Zoho's schema is not stable enough to be a relational contract

Concrete evidence **from the two payloads in your own question** — one
module, two endpoints:

| Field | `GET /organizations` | `GET /organizations/{id}` |
|---|---|---|
| `fiscal_year_start_month` | `3` (integer) | `"april"` (string!) |
| `is_org_active` | `true` (bool) — *and* duplicate `isOrgActive` | `"status": "1"` (string) |
| `is_search360_enabled` | `"true"` (**string** boolean) | — |
| `source` | `1` (int) | `"csv"` (string, in contacts) |
| lock info (contacts) | — | **both** `lock_details` *and* `lock_detail`, different shapes |

The same *field name* changes type across endpoints of the same module.
Booleans arrive as strings. Deprecated keys (`isOrgActive`) live alongside
their replacements. Fields like `approvers_list: []`,
`integration_references: []`, `additional_information: {}` are empty in
every payload we have ever seen — **their populated shape is unknown and
undocumented**. A strictly-typed, exhaustively-normalized schema is a
contract Zoho never signed.

This is exactly why the mapper's transforms are lenient (`"true"`/`1`/
`"active"` → `True`; blank-string-normalising `str`), why transform
failures skip a field instead of aborting a record, and why the untouched
payload must be preserved somewhere lossless.

### 1.4 The requirements that constrain the answer

From the business context (FSA/DLP field apps, Postgres as source of truth
for local apps, Zoho as background-synced ERP):

| # | Requirement | What it demands from storage |
|---|---|---|
| R1 | FSA/DLP reads **never** hit Zoho; fast faceted list/search | typed, indexed columns; CDC-friendly rows for Meilisearch |
| R2 | Create estimates/invoices/customers **in the middleware first** | a local relational model that exists *before* any Zoho document does |
| R3 | Bidirectional, eventually consistent | field-level knowledge of what is writable (outbound) vs server-managed |
| R4 | Geolocation & route optimization | PostGIS `geography` columns — impossible inside JSONB |
| R5 | Semantic duplicate detection on customers | pgvector embedding columns over *specific* fields (name, address) |
| R6 | Offline-first, low connectivity | deterministic local IDs, outbox journaling, idempotent replays |
| R7 | "Instantly" see Zoho stock changes | targeted re-fetch + CDC push to clients (see §10) |
| R8 | Zoho rate budget: **100 req/min/org, daily caps, ~10 concurrent** (`introduction.md`) | the mirror absorbs all read traffic; sync spends the budget once |
| R9 | Zoho schema drift must never lose data or break ingestion | a lossless raw store + lenient extraction |
| R10 | Analytics (ClickHouse) & search (Meilisearch) fed by Debezium CDC | flat typed columns serialize cleanly; JSONB blobs push parsing downstream |

R1/R4/R5/R10 pull toward **columns**. R9 (and §1.3) pulls toward
**documents**. R2/R3/R6 pull toward a **locally-owned relational core** for
the entities we author. No single-paradigm answer satisfies all ten — which
is the real reason the answer is a hybrid, not a preference.

---

## 2. A taxonomy of Zoho response fields

Before deciding *how* to store, classify *what* Zoho sends. Every key in
every payload you pasted falls into exactly one of eight classes. This
taxonomy is the heart of the framework — each class has one storage rule.

### Class A — Identity & sync anchors
`organization_id`, `contact_id`, `item_id`, `last_modified_time`,
`created_time`, `status`.

**Rule: always a typed column.** These drive identity matching
(`zoho_id`), incremental cursors, and reconciliation. Non-negotiable.

### Class B — Queryable scalar business fields
`contact_name`, `mobile`, `gst_no`, `rate`, `sku`, `contact_type`,
`outstanding_receivable_amount`, `place_of_supply`, …

**Rule: typed column iff the local apps filter, sort, join, index, or
write it.** Declared per module in the `field_map`. Everything else stays
reachable in `zoho_raw`. Promotion later is cheap (one migration + one
`FieldMapping` + one full sync); premature extraction of 200 columns per
module is not.

### Class C — Denormalized *reference* embeds (master-data snapshots)
Zoho flattens foreign entities into the payload as a convenience:

- Contact carries `currency_id` + `currency_code` + `currency_symbol` +
  `price_precision` (the Currency master, inlined).
- Contact carries `payment_terms` + `payment_terms_id` +
  `payment_terms_label` (Payment Terms, inlined).
- Contact detail carries `contact_tax_information` — the **Tax / Tax
  Group master** (`GST18`, with `tax_groups_details` splitting into
  CGST9/SGST9), inlined.
- Item carries `tax_id`/`tax_name`/`tax_percentage`.
- Contact detail carries `pricebook_id`/`pricebook_name`,
  `branch_id`/`branch_name`.

**Rule: store the FK (`*_zoho_id` column), route the embedded payload to
the owning module via `NestedEntityRule` so the master table stays fresh,
and optionally keep 1–2 denormalized display columns (e.g.
`currency_code`) for zero-join list rendering.** The master module
(taxes, currencies) remains the single place its full structure lives.
The engine already does this: nested children upsert FIRST, then the
child's `id`/`zoho_id` are stamped onto the parent's FK columns.

This is the correct answer to *"tax data is a separate module but arrives
as `contact_tax_information`"*: the embed is a **snapshot of a reference**,
not the reference itself. Treat it as (FK + cache), never as the canonical
copy — the canonical copy is the `zoho_taxes` mirror fed by `/settings/taxes`
*and* opportunistically refreshed by every embed that flows past.

### Class D — Owned child collections (composition, not reference)
Children that have no life outside their parent:

- Contact → `contact_persons[]`, `billing_address`/`shipping_address`/`addresses[]`
- Estimate/Invoice → `line_items[]`
- Item → `locations[]` (per-warehouse stock)
- Contact → `tags[]`, `documents[]`

**Rule: split into a child table when (and only when) at least one of:**
1. the local apps query/filter/aggregate across them (line items by
   `item_id`; addresses by geography);
2. we **author** them locally (estimate line items — R2);
3. they need their own columns of special types (PostGIS point on
   addresses for FSA routing — R4);
4. they need independent identity for two-way patching (Zoho gives
   `address_id`, `contact_person_id`, `line_item_id` — evidence Zoho
   itself treats them as sub-resources with their own update endpoints,
   e.g. `PUT /estimates/{id}/address/billing`).

Otherwise leave them inside `zoho_raw` and expose them read-only through
the API layer. *Example:* `default_templates` (28 keys of template
wiring) fails all four tests → stays in `zoho_raw`. `line_items` passes
all four → child table.

### Class E — Derived / formatted / presentation duplicates
`time_zone_formatted`, `*_formatted` everywhere, `custom_field_hash`,
`cf_risk_score` + `cf_risk_score_unformatted` promoted to top level,
`created_time_formatted`, `value_formatted`, `language_code_formatted`.

**Rule: never store as columns. Never push outbound.** They are
render-cache Zoho computes from base fields + org locale settings. They
remain queryable in `zoho_raw` for debugging, and our own API produces its
own presentation via Pydantic `@computed_field` (the established pattern —
see `files/schema.py`, documents module). Storing them creates
double-truth that drifts the moment we edit the base field locally.

Note the *triple* redundancy in the contacts index payload: the same
custom-field value appears in (1) the `custom_fields` array, (2) promoted
`cf_risk_score` top-level keys, (3) `custom_field_hash`. One canonical
representation locally (Class F), the rest ignored.

### Class F — Custom fields (user-defined schema)
The `custom_fields` array — which itself has **two shapes**: the
placeholder form on organizations (`{index, label, value}` with empty
labels) and the full form on contacts/items (`{customfield_id, api_name,
data_type, value, value_formatted, …}`).

**Rule: flatten to `custom_fields` hstore (`{api_name: str(value)}`),
keep the untouched array in `zoho_raw`.** hstore is GIN-indexable (`WHERE
custom_fields -> 'cf_risk_score' = 'High'`), survives admins adding fields
in Zoho with zero migrations, and the raw array preserves
`customfield_id`/`data_type`/`selected_option_id` needed to *write* custom
fields back (outbound requires `[{customfield_id, value}]` — see
`items.md`, `estimate.md`). `flatten_custom_fields()` in `mapper.py`
already handles both shapes via the `api_name → label → customfield_id`
key fallback.

### Class G — Unknown / opaque / dormant structures
`approvers_list: []`, `integration_references: []`,
`additional_information: {}`, `opening_balances: []`, `vpa_list: []`,
`cards/checks/upi_mandates/bank_accounts` (feature-gated), the
double-keyed `lock_details`/`lock_detail`.

**Rule: `zoho_raw` only. Do nothing else.** You cannot design a schema
for a shape you have never seen populated — and you don't need to: the
day an approval workflow turns on, the populated array lands in
`zoho_raw` losslessly, you inspect real data, and *then* promote it (Class
B or D) with evidence. This "schema-on-read escape hatch" is the whole
point of carrying the raw document.

### Class H — Zoho account/UI metadata
`isOrgNotSupported`, `plan_name`, `zi_zb_edition`, `org_action`,
`AppList`, `can_show_document_tab`, `is_zpayroll_grid`,
`support_email`, `other_active_services[]`.

**Rule: `zoho_raw` only** (or a column if ops genuinely dashboards it —
`plan_name` is a plausible exception). This is Zoho's UI talking to
Zoho's UI; it has no business meaning in the middleware and is
server-managed (never outbound).

---

## 3. The three candidate architectures, evaluated

### Option A — Full normalization (3NF mirror of Zoho's implied model)

Every nested structure becomes a table: `addresses`, `contact_persons`,
`taxes`, `tax_group_components`, `currencies`, `custom_field_definitions`,
`custom_field_values` (EAV), `templates`, … Parents hold FKs; the raw
payload is discarded after decomposition.

| Dimension | Verdict |
|---|---|
| Local queryability (R1, R4, R5) | ✅ Excellent — everything typed and joinable |
| Schema drift (R9) | ❌ **Fatal.** Every new/changed Zoho field = migration + mapper change *before* data stops being dropped. §1.3's type instability (int→string on the same field) breaks strict columns in production. |
| Unknown shapes (Class G) | ❌ Cannot model what you haven't seen; data discarded. |
| Engineering cost | ❌ ~40 modules × dozens of fields × regional variants; the EAV table for custom fields recreates JSONB, badly. |
| Outbound writes (R3) | ⚠️ Workable but you must reassemble documents from many joins. |
| Debugging sync issues | ❌ The evidence (what Zoho actually sent) is destroyed by decomposition. |
| CDC to ClickHouse/Meili (R10) | ✅ Clean typed events. |

### Option B — Pure JSONB document store

One table per module: `(zoho_id PK, payload JSONB, synced_at)`. All reads
via `payload ->> 'field'`; expression/GIN indexes where needed.

| Dimension | Verdict |
|---|---|
| Ingestion robustness (R9) | ✅ Perfect — nothing can break, nothing is lost. |
| Engineering cost (day 1) | ✅ Trivial. |
| Local queryability (R1) | ⚠️ Possible but degrading: every filter is a `->>` cast; GIN `jsonb_path_ops` helps membership, not range/sort; planner statistics on JSONB paths are weak → bad plans at scale. |
| PostGIS / pgvector (R4, R5) | ❌ **Fatal.** `geography` and `vector` are column types. Route optimization and semantic dedup cannot run inside a JSONB blob (expression indexes can't produce a KNN GiST index over a computed geography from two text fields reliably, and embeddings must be stored, not computed). |
| **Local-origin records (R2)** | ❌ **Fatal.** An estimate created in FSA *has no Zoho document yet*. In a payload-shaped table you'd have to fabricate a fake Zoho document to store your own data — the tail wags the dog. Constraints (FK from line item → item, totals arithmetic) are unenforceable. |
| Two-way field control (R3) | ❌ No place to express "this field is server-managed, never push". Outbound = diffing blobs. |
| CDC consumers (R10) | ⚠️ Every consumer (ClickHouse MV, Meilisearch indexer) re-implements extraction; the type instability of §1.3 now lives in *four* codebases instead of one mapper. |
| Relational integrity | ❌ No FK from `invoice.customer_id` → contact row; orphan detection becomes a batch job. |

### Option C — Typed projection over a raw document (the hybrid) ✅

Per module: one mirror table = **strict sync scaffold**
(`ZohoEntityMixin`) **+ curated typed columns** (Classes A/B/C) **+
`custom_fields` hstore** (F) **+ `zoho_raw` JSONB** (D-not-split, E, G, H)
**+ child tables** only where Class D rules demand.

| Dimension | Verdict |
|---|---|
| Ingestion robustness | ✅ `zoho_raw` is lossless; mapper skips/logs bad fields; all columns nullable. |
| Local queryability | ✅ Exactly the fields the apps need are real columns with real indexes (incl. PostGIS/pgvector). |
| Schema drift | ✅ New Zoho field lands in `zoho_raw` immediately; promoted to a column *when a feature needs it*, with historical backfill available locally (`UPDATE … SET col = zoho_raw->>'x'`) — no Zoho re-fetch, no rate budget spent. |
| Local-origin records | ✅ Rows are first-class local entities; `zoho_id` NULL until the outbound create succeeds; `zoho_raw` NULL until the first echo returns. |
| Two-way control | ✅ `FieldMapping(outbound=…)` is the per-field write contract (§7). |
| CDC | ✅ Debezium streams both: typed columns for ClickHouse/Meili, and the full `zoho_raw` for anyone downstream who needs the long tail. |
| Cost | ⚠️ Moderate: each module needs a deliberate field map — but that map is *also* the outbound contract you need anyway for R3, so the work is not incremental overhead. |

**Decision: Option C.** The field map you must write for outbound sync
(R3) *is* the extraction spec for inbound columns — the hybrid's only real
cost is work the bidirectional requirement forces regardless. The industry
names for this composite: **Anti-Corruption Layer** (the mapper translates
Zoho's dialect into our model), **materialized integration mirror** with
**schema-on-write projection + schema-on-read escape hatch**, and
**transactional outbox** on the write side.

### Storage-cost note (the usual objection to keeping `zoho_raw`)

A contact detail document is ~6–8 KB of JSON → ~2–4 KB TOASTed/compressed.
100k contacts ≈ a few hundred MB — irrelevant next to the operational cost
of *not* having the evidence when a sync mis-maps a field or Zoho ships a
surprise. If a module ever grows huge (bank transactions), `zoho_raw` can
be trimmed per module (store only on error/conflict) — a knob, not an
architecture change.

---

## 4. The decision framework

For **every key** in a Zoho payload, run this tree (classes from §2):

```
                     ┌─ Is it the Zoho PK, a timestamp, or status?  ──────────── A: typed column (mandatory)
                     │
                     ├─ Is it *_formatted / *_hash / a promoted cf_* duplicate? ─ E: ignore (lives in zoho_raw)
                     │
                     ├─ Is it the custom_fields array? ────────────────────────── F: hstore + raw array in zoho_raw
                     │
key in payload ──────┼─ Is it an embedded FOREIGN entity (has its own module /
                     │  endpoint: tax, currency, pricebook, payment terms)? ───── C: *_zoho_id FK column
                     │                                                              + NestedEntityRule → master module
                     │                                                              + ≤2 denormalized display columns
                     │
                     ├─ Is it a child COLLECTION owned by this record? ─────────── D: child table IF
                     │     (line_items, addresses, contact_persons, locations)       • locally authored, OR
                     │                                                               • queried/aggregated/joined, OR
                     │                                                               • needs PostGIS/pgvector/FKs, OR
                     │                                                               • two-way patched via its own sub-resource id
                     │                                                             ELSE stays in zoho_raw
                     │
                     ├─ Do FSA/DLP filter/sort/join/WRITE this scalar? ─────────── B: typed column via FieldMapping
                     │                                                               (outbound=True iff in Zoho's write args)
                     │
                     ├─ Empty/unknown/undocumented shape? ─────────────────────── G: zoho_raw only (promote later w/ evidence)
                     │
                     └─ Zoho account/UI/plan metadata? ─────────────────────────── H: zoho_raw only
```

Three operating rules complete the framework:

1. **Promotion is cheap, demotion is not.** Default to *not* extracting.
   `zoho_raw` means a later promotion is one migration + one mapping +
   one local backfill UPDATE — zero Zoho calls. Removing a column that
   clients grew to depend on is a breaking change. Start minimal.
2. **The field map is law.** A field is writable-to-Zoho iff its
   `FieldMapping` says `outbound=True`, and that flag is set from Zoho's
   documented **create/update arguments** (not from what GET returns).
   §7 explains why this dissolves the "rebuild the API request" fear.
3. **One canonical representation per fact.** When Zoho sends a fact
   three ways (array + promoted keys + hash), exactly one local
   representation is authoritative (hstore, from the array); the
   duplicates are never read except for debugging.

---

## 5. Mapping to the existing engine

The framework is not aspirational — most of it is running code. This
table is the audit:

| Framework element | Where it already lives | Status |
|---|---|---|
| Raw document store | `ZohoEntityMixin.zoho_raw` (JSONB), refreshed on every upsert | ✅ |
| Typed projection | `FieldMapping` + `map_inbound()` dotted-path extraction | ✅ |
| Lenient type coercion (§1.3) | `TRANSFORMS` (`"true"`→bool, blank-normalising str, etc.), failure = skip field | ✅ |
| Missing-key ≠ NULL (list/detail asymmetry) | `MISSING` sentinel; partial payloads never erase | ✅ |
| Custom fields → hstore | `flatten_custom_fields()` (handles both array shapes) | ✅ |
| Class C nested routing | `NestedEntityRule` → child module upsert-first → FK stamp-back | ✅ (single-object; `many=True` list embeds don't stamp back-refs — fine for C, see gap G3) |
| N+1 list/detail | `detail_required` + `inline`/`queued` dispatch + `zoho_queue_logs` journal | ✅ |
| Identity & revival | match by `zoho_id` with `include_deleted=True`; partial unique index on live `zoho_id` | ✅ |
| Incremental cursor | `zoho_sync_stats.last_incremental_cursor` on `last_modified_time` | ✅ |
| Reconciliation of upstream deletes | `soft_delete_missing` on FULL runs | ✅ |
| Outbound write contract | `FieldMapping.outbound` + `map_outbound()` (dotted paths → nested objects, None-dropping) | ✅ |
| Transactional outbox | `outbox.py`: journal in-txn → Celery `push_outbound` → create back-fills `zoho_id`, update escalates to create | ✅ |
| Server-managed field fencing | `outbound=False` on `is_default_org`, `currency_id`, … (organizations module) | ✅ |
| Observability | `zoho_sync_stats`, `zoho_queue_logs`, row `sync_status/sync_logs`, admin API | ✅ |

**Gaps this document adds to the design (the roadmap in §12):**

- **G1 — Child tables for owned collections** (Class D): line items,
  contact addresses, contact persons, item locations. The engine handles
  nested *modules*; owned-child *tables* need a small extension (a
  `ChildCollectionRule`: replace-set upsert of children under the parent
  row, diff by `line_item_id`/`address_id`).
- **G2 — Conflict detection & echo suppression** for bidirectional
  modules (§9). `SyncStatus.CONFLICT` exists as a state; the
  detection rule is specified below but not yet enforced in
  `upsert_payload`.
- **G3 — `many=True` back-references.** List embeds currently upsert
  children but don't record the association. Fine for Class C snapshots;
  Class D child tables (G1) subsume the need.
- **G4 — Webhook ingress** for near-real-time freshness (§10).
- **G5 — Outbound payloads for document entities** (estimates/invoices)
  need line-item assembly beyond flat `map_outbound` (§7.2, §8.4).

---

## 6. Ownership classes

"Two-way synced" does not mean every module is symmetric. Every module
gets exactly one ownership class, and the class — not the storage debate —
decides its write topology. Mixing these up is the root cause of most
broken ERP integrations.

### O1 — Zoho-owned masters (inbound-dominant)
*Organizations (settings), Taxes, Currencies, Chart of Accounts, Users,
Payment Terms, Locations/Branches, Templates.*

Zoho is the author; we mirror. Local writes are rare/admin-only.
`direction=INBOUND` or BIDIRECTIONAL with a thin outbound map. These are
the **reference targets** of Class C embeds — every embedded
`contact_tax_information` or currency snapshot flowing past also
refreshes them (free freshness). Sync them **first** (dependency order)
so FK resolution finds its targets.

### O2 — Locally-authored transactionals (outbound-dominant)
*Estimates, Invoices, Sales Orders, Delivery-related records — everything
FSA/DLP creates.*

**We are the author; Zoho is the accounting projection.** The row is born
local (`zoho_id NULL`, `sync_status=pending`), FKs point at local mirror
rows, totals are computed locally, and the outbox pushes a
**write-contract payload** (§7). Zoho then becomes the author of the
*accounting consequences* (numbering if auto-generated, tax math
verification, status transitions like `invoiced`), which flow back on the
inbound echo and land in `zoho_raw` + Class A/B columns.

Inbound sync still runs for these modules — records can be created/edited
in Zoho's UI by accountants — but on conflict, **local wins for fields we
author, Zoho wins for fields it authors** (status, computed totals,
numbers). That per-field split is again the field map: `outbound=True`
fields are ours; `outbound=False` fields are Zoho's.

### O3 — Shared bidirectional (the hard class)
*Contacts/Customers, Items (field-level split: we edit descriptions/custom
fields; Zoho owns stock & accounting links).*

Both sides genuinely author. Requirements: echo suppression, conflict
detection, and a per-field authority map (§9). Do these modules **after**
O1/O2 are proven — they need the machinery of G2.

```
            O1 masters                O3 shared                 O2 transactionals
Zoho ═══════════════▶ PG      Zoho ◀═════════▶ PG        Zoho ◀═══════════════ PG
      (mirror)                 (merge, per-field           (project; echo returns
                                authority)                  accounting results)
```

---

## 7. Read model ≠ write model

Your stated worry — *"if we normalize, we have to rebuild the API request
in the format Zoho expects"* — dissolves once you see that **Zoho's write
API never accepts the read document anyway.** This is the single most
important observation in this document.

### 7.1 The asymmetry is Zoho's, not ours

Compare, from the vendored docs:

- `GET /contacts/{id}` returns **~120 keys** (your example): tax group
  breakdowns, currency summaries, templates, lock state, portal state…
- `POST /contacts` / `PUT /contacts/{id}` accepts **~25 arguments**:
  `contact_name`, `company_name`, `contact_persons[]`, `billing_address`,
  `shipping_address`, `gst_no`, `gst_treatment`, `payment_terms`,
  `custom_fields [{customfield_id|api_name, value}]`, …
- `GET /estimates/{id}` returns totals, tax breakdowns, template info;
  `POST /estimates` (estimate.md) accepts `customer_id`, `line_items[]`
  (item_id, rate, quantity, discount, tax_id…), `discount`, `notes` — and
  **computes** `sub_total`, `tax_total`, `total` itself. You *cannot*
  send totals; Zoho rejects/ignores them.

So the outbound task was never "serialize our row back into the read
shape". It is **"emit the documented write arguments"** — a small,
stable, per-module contract. Echoing read-only fields back is not just
unnecessary, it's how integrations break (Zoho rejects unknown/readonly
keys on some endpoints, silently ignores on others — neither is what you
want).

### 7.2 How the code expresses it

- Scalars: `FieldMapping(outbound=True)` + `map_outbound()` already
  rebuilds dotted paths into nested objects (`address.city` →
  `{"address": {"city": …}}`) and drops Nones (Zoho rejects explicit
  nulls on many endpoints).
- Read-only: `outbound=False` (`is_default_org`, `currency_symbol`,
  every `*_formatted`, every computed total).
- Renames: `outbound_key` when write-key ≠ read-key.
- Custom fields (G5): outbound needs `[{customfield_id, value}]` — built
  by joining the hstore against the definitions preserved in `zoho_raw`
  (or a small `zoho_custom_field_definitions` mirror once the settings
  endpoint is mirrored).
- Documents (G5): an `outbound_builder` hook per O2 module composes
  `line_items[]` from the child table (§8.4). This is the one place flat
  field maps aren't enough — by design, it's a *module-owned* builder,
  not engine magic.

### 7.3 Special write channels

Zoho exposes sub-resource writes we should prefer when touching one
aspect: `PUT /estimates/{id}/address/billing`, `PUT
/item/{id}/customfields`, `POST /items/{id}/active|inactive`, estimate
status transitions (`/status/sent`, `/status/accepted`). The outbox `op`
vocabulary extends naturally (`update_billing_address`,
`mark_active`, `status_sent`) — smaller payloads, fewer conflict
surfaces, clearer intent in `zoho_queue_logs`.

Also note `X-Unique-Identifier-Key` / `X-Upsert` (items, estimates): Zoho
supports **upsert-by-custom-field**. If we stamp every locally-created
record with a `cf_middleware_id` custom field carrying our UUID, outbound
create becomes *idempotent* (a retried create can't duplicate) and
correlation of echoes becomes trivial (§9.3). **Adopt this.**

---

## 8. Worked examples

Every structure from your question, classified and resolved.

### 8.1 `GET /organizations` (index) + `GET /organizations/{id}` (document)

| Payload key | Class | Storage decision |
|---|---|---|
| `organization_id` | A | `zoho_id` |
| `name`, `email`, `phone`, `contact_name`, `website` | B | columns (already mapped) |
| `time_zone`, `date_format`, `language_code`, `fiscal_year_start_month`, `field_separator` | B | columns — locale needed to render dates/amounts like Zoho does. Note §1.3: `fiscal_year_start_month` is int on list, string on detail → lenient transform or accept last-writer; evidence for why transforms never hard-fail. |
| `currency_id/code/symbol/format`, `price_precision` | C | FK-ish columns, `outbound=False` (already mapped) |
| `address.{street_address1…zip}` (detail only) | D-flat | flattened `address_*` columns (already mapped) — a single embedded object with no independent life on orgs; no child table needed (contrast contacts, §8.2) |
| `tax_settings.{is_tax_registered, tax_reg_no}` | B | promote 2 columns (GST reg no is business-relevant) |
| `custom_fields` (placeholder shape `{index,label,value}`) | F | hstore (labels empty → `flatten_custom_fields` returns None → nothing stored; raw array in `zoho_raw`) |
| `custom_field_hash` (detail) | E | ignore |
| `time_zone_formatted`, `account_created_date_formatted`, `version_formatted`, `user_status_formatted` | E | ignore |
| `other_active_services[]`, `org_joined_app_list[]`, `AppList[]` | H | `zoho_raw` |
| `plan_name`, `plan_type`, `plan_period`, `isOrgNotSupported`, `zi_*`, `org_action`, `is_zpayroll_grid`, … | H | `zoho_raw` (`plan_name` promotable if ops wants a dashboard) |
| `is_default_org`, `user_role`, `user_status`, `role_id` | H (per-user server state) | columns exist, `outbound=False` — correct |
| `logo_url`, `portal_name`, `payments_url` | B-lite | `zoho_raw` until a feature renders them |
| `isOrgActive` vs `is_org_active` duplicate | — | map the modern key; the duplicate stays in `zoho_raw` |

### 8.2 `GET /contacts` + `GET /contacts/{id}` — the full treatment

Module config sketch (INCREMENTAL, `detail_required=True`,
`detail_dispatch="queued"` for volume, BIDIRECTIONAL):

| Payload key | Class | Decision |
|---|---|---|
| `contact_id`, `created_time`, `last_modified_time`, `status` | A | columns |
| `contact_name`, `company_name`, `first_name`, `last_name`, `email`, `phone`, `mobile`, `contact_type`, `customer_sub_type`, `gst_no`, `gst_treatment`, `pan_no`, `place_of_contact`, `notes` | B | columns; all `outbound=True` (they're in the write args) |
| `outstanding_receivable_amount` (+bcy, payable, unused credits ×8) | B (Zoho-computed) | promote the 2–3 FSA actually shows (credit screens); `outbound=False`; rest in `zoho_raw` |
| `currency_id` + `currency_code/symbol` | C | `currency_zoho_id` FK + `NestedEntityRule` → currencies module; keep `currency_code` denormalized |
| `payment_terms`, `payment_terms_id`, `payment_terms_label` | C | `payment_terms` + FK column; label ignored (E-ish) |
| `contact_tax_information` (detail) — the inlined **Tax Group** with `tax_groups_details` (CGST9+SGST9) | C | `tax_zoho_id` FK (`tax_id` key also present at top level); `NestedEntityRule(attr="contact_tax_information", module="taxes")` refreshes the `zoho_taxes` mirror. The tax *master* module models the group→component relation (from `taxes.md`), so the CGST/SGST breakdown lives exactly once. |
| `pricebook_id/name`, `branch_id/name`, `location_id/name` | C | FK columns; names denormalized or ignored |
| `billing_address`, `shipping_address`, `addresses[]` (each with `address_id`, `latitude`, `longitude`!) | **D → child table** | `zoho_contact_addresses(id, contact_id FK, zoho_address_id, kind billing|shipping|other, …fields, geog geography(Point,4326) GIST)`. This is R4's landing zone: FSA routing/beat planning runs KNN and route queries on `geog`. Zoho's empty-string lat/lng → NULL geog; FSA fills real coordinates on visit → outbound is *not* pushed to Zoho (Zoho's address write args have no meaningful geo semantics for us) — locally-authored enrichment columns are the mirror-table superpower: **local-only columns live happily beside mirrored ones.** |
| `contact_persons[]` (detail; `contact_person_id`, `is_primary_contact`) | **D → child table** | `zoho_contact_persons` — FSA calls/messages specific persons; own sub-resource in Zoho (`contact-persons.md` module exists); two-way patchable. |
| `customer_currency_summaries[]` (detail) | E (computed aggregate per currency) | `zoho_raw`. It is *not* the currency master (that's C via `currency_id`) — it's a Zoho-computed receivables rollup. Single-currency org ⇒ zero query value. |
| `custom_fields[]` + promoted `cf_*` + `custom_field_hash` | F + E | hstore from the array; promoted keys & hash ignored |
| `contactperson_custom_fields`, `tags[]`, `documents[]` | D-lite | `zoho_raw` now; `tags` can later bridge to the local tags module (a mapping decision, not storage) |
| `default_templates` (28 keys), `lock_details`+`lock_detail`, `portal_status`, `ach_supported`, `photo_url`, `is_linked_with_zohocrm`, `zcrm_*`, `owner_*`, `approvers_list`, `integration_references`, `additional_information`, `registration_details`, `opening_balances`, `cards/checks/upi_mandates/bank_accounts/vpa_list` | E/G/H | `zoho_raw` only |
| **Local-only additions** | — | `name_embedding vector(…)` for semantic dedup (R5 — requires adding the `pgvector` Python package to requirements.txt, per the standing tech-stack note), `dedup_status`, FSA beat/route assignment columns. They coexist with the mirror; `outbound` flags don't exist for them so they can never leak to Zoho. |

### 8.3 Items + stock (`items.md`)

- B columns: `name`, `sku`, `rate`, `purchase_rate`, `status`,
  `product_type`, `item_type`, `hsn_or_sac`, `stock_on_hand`,
  `available_stock`, `actual_available_stock`, `reorder_level`, `unit`.
  Stock columns are `outbound=False` — **stock is authored by inventory
  transactions in Zoho, never by field edits** (adjustments go through
  Zoho Inventory's adjustment endpoints if ever needed).
- C: `tax_id`/`tax_name`/`tax_percentage` → FK + nested rule;
  `account_id`, `purchase_account_id`, `inventory_account_id`,
  `vendor_id` → FK columns.
- D → child table: `locations[]` → `zoho_item_locations(item_id,
  zoho_location_id, location_stock_on_hand, …)` — per-warehouse stock is
  exactly what DLP needs ("is it in the Godhra DC?"), and it changes at a
  different cadence than the item itself.
- F: `custom_fields` → hstore. India-only `item_tax_preferences` → Class
  G (`zoho_raw`) until GST logic needs it.
- Ownership O3 with a narrow local surface: we author descriptions +
  custom fields; Zoho authors stock & accounting.

### 8.4 Estimates & Invoices — the O2 flagship (creating from the middleware)

The flow that motivates the whole architecture:

```
FSA agent (offline-capable) submits estimate
  │ 1. local txn: INSERT zoho_estimates (zoho_id NULL, status='draft',
  │               sync_status='pending', estimate_number NULL — Zoho will number it)
  │               INSERT zoho_estimate_line_items (FK→zoho_items.id, rate/qty/tax FK snapshot)
  │               compute display totals locally (UI needs them NOW; flagged provisional)
  │    2. same txn: queue_outbound("estimates", local_id, "create")   ← outbox journal
  │ COMMIT  → client sees the estimate instantly, from Postgres
  ▼
Celery push_outbound (integrations queue)
  │ 3. module outbound_builder assembles the WRITE CONTRACT (estimate.md):
  │    { customer_id: <contact.zoho_id>, line_items: [{item_id: <item.zoho_id>,
  │      rate, quantity, discount, tax_id}], discount, notes, terms,
  │      custom_fields: [{customfield_id, value}] }        ← never totals, never *_formatted
  │    (any FK whose target has zoho_id NULL ⇒ push its create first, or fail
  │     w/ retry — dependency-ordered outbox)
  │ 4. POST /estimates  → Zoho computes sub_total/tax_total/total, assigns
  │    estimate_number & estimate_id
  │ 5. back-fill zoho_id; upsert echo payload → zoho_raw + authoritative
  │    totals/number replace the provisional ones; sync_status='synced'
  ▼
Accountant later marks it invoiced in Zoho UI
  → inbound incremental sync sees status='invoiced' → row updated → Debezium →
    Kafka → Meilisearch/ClickHouse → Soketi pushes to the agent's device
```

Line items are unavoidably a **child table** (Class D: locally authored,
FK to items, aggregation, own `line_item_id` for PUT updates). Totals are
stored but **Zoho-authoritative** (`outbound=False`; local computation is
a provisional UX value until the echo lands). Status transitions use the
sub-resource channels (§7.3), not document PUTs.

### 8.5 Custom modules (`custom-modules.md`)

Records are *entirely* `cf_*` fields + `record_name`. The hybrid
degenerates gracefully: A columns + `record_name` + hstore + `zoho_raw`,
generic `/{module_api_name}` endpoint config. No new machinery — the
strongest evidence the framework generalizes.

---

## 9. Two-way sync correctness

Storage was the easy half. Bidirectional consistency is where ERP
integrations die; these four mechanisms (G2 on the roadmap) keep ours
alive.

### 9.1 Conflict detection (per-record, cheap)

Persist `zoho_last_modified_time` (Class A column) on every inbound
upsert. Track `local_dirty_at` — set whenever a local write touches any
`outbound=True` field. On inbound upsert of a row with a **pending
outbound entry** (`sync_status in (pending, queued, syncing)`):

- Fields that are `outbound=False` (Zoho-authored): apply inbound freely.
- Fields that are `outbound=True` and locally dirty: **do not overwrite**;
  if the inbound value differs from the last-synced value →
  `sync_status='conflict'`, journal both values in `sync_logs`, surface in
  the admin API. Resolution policy per ownership class: O2 → local wins
  (re-push); O3 → configurable, default last-writer-wins by timestamp
  with the conflict journaled for audit.

This is field-level merge using the authority map we already have (the
`outbound` flag), not a generic CRDT — deliberate simplicity.

### 9.2 Echo suppression

Our own outbound write comes back on the next incremental poll (Zoho
bumps `last_modified_time`). Without care this (a) re-marks rows dirty,
(b) can resurrect a stale intermediate state. Rule: an inbound upsert
whose payload equals the state we last pushed (compare
`zoho_last_modified_time` ≤ the timestamp captured in the outbound
success echo, or compare mapped values) is a no-op except for
`zoho_raw`/`synced_at` refresh. The outbox already captures the create
echo; extend it to store the echoed `last_modified_time` as the fence.

### 9.3 Idempotency & correlation

- Inbound: upsert-by-`zoho_id` is naturally idempotent (already built).
- Outbound create: adopt `cf_middleware_id` (+ Zoho's
  `X-Unique-Identifier-Key`/`X-Upsert` where supported, §7.3) so a
  retried create after a network timeout cannot duplicate, and any echo
  is attributable even if the response was lost.
- Outbound ordering: per-record ordering via the outbox journal; add
  dependency ordering (parent contact before its estimate) by resolving
  FK `zoho_id`s at push time and requeueing with backoff when a
  dependency hasn't landed (§8.4 step 3).

### 9.4 The safety nets (already built, keep them)

Weekly forced FULL sync per module (catches anything incremental windows
missed — Zoho's `last_modified_time` filter does not report *deletes*),
`soft_delete_missing` reconciliation, row-level `sync_logs`, and
`zoho_queue_logs` as the replayable journal.

---

## 10. Freshness

*"Instantly see the available stock of any item if it changes on Zoho."*

Truth first: with a polled third-party API there is no literal
"instantly" — there is **bounded staleness**, and the architecture already
gives sub-second local fan-out once Postgres knows. The freshness chain:

```
Zoho change ──(A: webhook, seconds │ B: incremental poll, ≤ interval)──▶
  targeted detail fetch ──▶ Postgres upsert ──▶ Debezium (ms) ──▶ Kafka ──▶
     ├─▶ Meilisearch (search reflects new stock)
     ├─▶ ClickHouse (analytics)
     └─▶ Soketi push (G4b) ──▶ FSA/DLP UI updates live
```

- **Baseline (built):** incremental sync on `sync_interval_minutes`. For
  items, tighten to 2–5 min — an incremental poll on a quiet window costs
  ~1 request against the 100/min budget.
- **Fast path (G4): Zoho webhooks via workflow rules** (Books and
  Inventory both support workflow-rule webhooks on module events). Ingress
  design — the **fetch-on-notify** pattern:
  1. `POST /api/zoho/webhooks/{module}` verifies a shared secret, does
     **no processing**, journals a `zoho_queue_logs` row, enqueues
     `fetch_detail(module, zoho_id)` (machinery that already exists for
     queued N+1), returns 200 in <100 ms.
  2. The worker fetches the authoritative document and runs the normal
     upsert path. **Never trust the webhook body as data** — webhook
     payloads are configurable/truncated, arrive out of order, and get
     dropped; they are *triggers*, the poll remains truth (exactly the
     stance in [zoho-module-implementation-guide.md](zoho-module-implementation-guide.md) §Optional).
  3. Debounce per `(module, zoho_id)` with a short Redis SETNX so a burst
     of edits coalesces into one fetch.
- **Client push:** the search-indexer pattern (FastStream consumer on
  `zoho-mirror.public.*`) extends to a thin consumer that publishes
  `item.stock_changed` to Soketi channels — completing the "agent sees it
  live" loop without FSA ever polling.

Net effect: seconds-level freshness when webhooks fire, minutes-level
guaranteed floor from polling, and the request path *never* touches Zoho —
preserving the prime directive (Zoho is not a synchronous dependency).

---

## 11. Pattern glossary

| Pattern | Where it appears here |
|---|---|
| **Anti-Corruption Layer** (DDD) | The mapper + field maps translate Zoho's unstable dialect into our model; Zoho's quirks never leak past `zoho/sync/`. |
| **System-of-record inversion / materialized integration mirror** | Postgres is truth for the apps; Zoho is one more synced system. |
| **Schema-on-write projection + schema-on-read escape hatch** | Typed columns for the known/queried; `zoho_raw` for the unknown/deferred. |
| **Transactional Outbox** | Local commit + journal in one transaction; async push with retries (`outbox.py`). |
| **CQRS-lite / command-query asymmetry** | Outbound = Zoho's write contract; inbound = Zoho's read documents. Never confuse the two (§7). |
| **Fetch-on-notify** | Webhooks trigger targeted re-fetch; polling remains authoritative (§10). |
| **CDC fan-out** | WAL → Debezium → Kafka → Meilisearch/ClickHouse/Soketi; app writes never dual-write to derived stores. |
| **Idempotent upsert + natural-key identity** | `zoho_id` matching with soft-delete revival; `cf_middleware_id` for outbound idempotency. |
| **Eventual consistency with bounded staleness + reconciliation** | Incremental cursors, weekly full sync, `soft_delete_missing`. |

---

## 12. Per-module decisions & roadmap

### 12.1 Classification of the vendored modules

| Module (docs file) | Ownership | Strategy | Child tables | Notes |
|---|---|---|---|---|
| organizations | O1 | FULL+inline detail (no modified filter) | — | ✅ built |
| taxes, currency, chart-of-accounts, users, locations, opening-balance | O1 | FULL or INDEX (small, some lack modified filters) | tax group→components | **Build first** — they are every module's Class C targets |
| contact-persons | O1-ish sub-resource | via contacts detail | (is a child table) | synced through contacts, own write endpoints |
| contact | O3 | INCREMENTAL + queued detail | addresses, contact_persons | §8.2; needs G2 before enabling outbound broadly |
| items | O3 (narrow local surface) | INCREMENTAL + queued detail | item_locations | §8.3; webhook priority for stock (G4) |
| estimate, invoices, sales-order | **O2** | INCREMENTAL inbound + outbox-first outbound | line_items | §8.4; needs G1+G5 |
| customer-payments, credit-note, sales-receipt | O2/O3 per flow | INCREMENTAL | applied-invoices mapping | payments apply-to-invoice is a Class D mapping table |
| purchase-order, bills, vendor-*, expenses, journals, debit-note, recurring-* | O1-mirror initially | INCREMENTAL | defer child tables | mirror-only (INBOUND) until a local feature writes them |
| bank-*, fixed-assets, base-currency-adjustment, time-entries, projects, tasks | O1-mirror | INCREMENTAL/INDEX | — | `zoho_raw`-heavy, minimal field maps |
| custom-modules | O3 | INCREMENTAL | — | degenerate hybrid, §8.5 |

### 12.2 Implementation order

1. **O1 masters** (taxes, currencies, chart of accounts, users,
   locations) — INDEX/FULL strategies, thin field maps. Unblocks all
   Class C `NestedEntityRule`s.
2. **G1 child-collection support** in the engine (replace-set upsert of
   owned children keyed by Zoho sub-ids) + **contacts** with addresses
   (PostGIS) & persons.
3. **Items** + item_locations + **G4 webhooks** (fetch-on-notify ingress,
   debounce) + Soketi stock push.
4. **G5 outbound builders** + **estimates** end-to-end (the O2 flagship,
   §8.4), then invoices/sales orders on the same template.
5. **G2 conflict/echo machinery**, then widen contacts/items outbound.
6. Long tail of mirror-only modules as features demand; promote fields
   from `zoho_raw` with evidence.

Each step lands via the existing recipe (ZOHO_SYNC_ENGINE.md §8):
model → register → migrate → Debezium include-list → tests.

---

## 13. Anti-patterns

1. **Never** make a request path call Zoho synchronously (including
   "just this once" for freshness — that's what §10 is for).
2. **Never** store `*_formatted`/derived values in columns or push them
   outbound; presentation is computed locally per our locale rules.
3. **Never** build outbound payloads by mutating/echoing the read
   document (`zoho_raw`) — write-contract only (§7).
4. **Never** add NOT NULL/strict constraints to mirrored business
   columns; ingestion robustness outranks database purism (mixin
   doctrine).
5. **Never** trust webhook payloads as data, and never let webhooks
   replace polling — triggers, not truth.
6. **Never** dual-write to Meilisearch/ClickHouse from app code; CDC is
   the only feeder.
7. **Never** let a Class C embedded snapshot become the canonical copy of
   a master (a contact's inlined `GST18` is a cache of the taxes module's
   row, not a second truth).
8. **Never** treat an EAV table or per-tenant DDL as the answer to custom
   fields; hstore + raw array covers query, drift, and write-back.
9. **Never** model an empty array you've never seen populated (Class G) —
   `zoho_raw` holds it until reality provides a spec.
10. **Never** hand-write per-module beat schedules, HTTP calls, or token
    logic — the engine's config, registry, and core client are the only
    entry points (established doctrine).

---

*Related docs:* [ZOHO_SYNC_ENGINE.md](ZOHO_SYNC_ENGINE.md) (the engine
this framework governs) · **[zoho-realtime-sync-architecture.md](zoho-realtime-sync-architecture.md)
(v2 — refines §10 and the `zoho_raw` write rule: payload provenance,
webhook ingress, the stock lane, line-item snapshots)** ·
[zoho-module-implementation-guide.md](zoho-module-implementation-guide.md)
(hands-on recipe) · [MODULES.md](MODULES.md) (cross-cutting modules) ·
[zoho-docs-md/](zoho-docs-md/) (vendored API reference cited throughout).
