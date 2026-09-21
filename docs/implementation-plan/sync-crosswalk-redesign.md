# The sync crosswalk — one sync store for every source and every module

**Status:** proposed (rev 2 — corrected against the codebase) · **Owner:** backend / platform data
**Schemas:** `sync`, `currency` · **Postgres:** 18 (`config/postgres`, PostGIS image)
**Supersedes:** `docs/implementation-plan/currency-sync-consolidation.md` §§3.2–3.3 and §§4–10
(the per-module `currency.currency_sync` table and the A/B partitioning question).
**Keeps from it:** §1 problem statement, §3.1 canonical currency row, §3.5 adapter shape,
§3.7 precedence, §3.8 exchange rates.
**Related:** `docs/ZOHO_SYNC_ENGINE.md` · `docs/zoho-sync-implementation/apply-gate.md` ·
`docs/tenancy/README.md` · `app/modules/zoho/sync/`

> **Rev 2 changelog.** Review found seven defects in rev 1; every one is fixed below and
> listed in the appendix. The three that changed the *design* (not just the prose):
> the crosswalk is written by an atomic guarded upsert rather than a read-modify-write
> (§2.6); the apply gate reads `deleted_at` from a join to the entity, never from a
> denormalised copy (§2.7); and the engine does **not** move to `app/modules/sync/` —
> that claim was false and is withdrawn (§3.5).

---

## 1. The question, answered

> *"I don't want to keep sync details on every table — but on a partitioned table.
> Is that a good architecture?"*

**The instinct is right and it is the single highest-leverage change available to this
platform. The count is wrong: it is two tables, not one, and only one of them is
partitioned by time.**

Sync bookkeeping is not one workload. It is two, with opposite access patterns, and
forcing them into one table makes each one bad at the other's job:

| | **gate state + identity** | **payload history** |
|---|---|---|
| Rows | exactly one per `(source, module, external id)` | one per *change* |
| Read pattern | point lookup by external id, on **every payload** | range scan by time, rarely |
| Write pattern | update in place | insert only |
| Needs | `UNIQUE`, O(1) index, skinny rows | cheap bulk insert, O(1) retention |
| Lifetime | as long as the record exists | N months |

A single time-partitioned table (design **A** in the currency doc) serves the second
column well and the first badly, for two reasons that are not tunable:

1. **No uniqueness.** Postgres requires every unique index on a partitioned table to
   include the partition key. Partitioned by `synced_at`, you cannot declare "one live
   row per Zoho id". That is not a cosmetic loss — it is the only thing standing between
   you and two "current" rows for the same record when the scheduled scan, a webhook and
   a queued detail-fetch land in the same second. The engine already runs all three lanes.
2. **No pruning on the hot path.** The gate lookup is `WHERE source_system=… AND
   module=… AND external_id=…`. There is no time predicate — you are looking for the
   latest row and you don't know when it was written. So every lookup fans out across
   every partition, and planning cost grows with the partition count ([PG docs,
   §5.12.3](https://www.postgresql.org/docs/current/ddl-partitioning.html)). The
   "optional fast path" in the currency doc §3.2 is not optional; it is the primary table.

So the answer to *open decision 1 (A or B?)* and *open decision 2 (fast path?)* is the
same answer: **both, and they are different tables.**

### 1.1 This is a known pattern, twice over

* **MDM cross-reference (XREF) tables.** Informatica's multidomain MDM stores the
  mastered values on the *base object* and keeps one XREF row per source-system record,
  uniquely keyed on `(source PK, source system)`, carrying that source's own values and
  its load metadata. Delete management, merge/unmerge and "which source said what" all
  hang off the XREF, never off the base object
  ([Informatica](https://docs.informatica.com/master-data-management/multidomain-mdm/10-4/configuration-guide/part-3--building-the-data-model/building-the-schema/configuring-base-objects/cross-reference-tables.html)).
* **Data Vault 2.0 hub + satellite.** The hub holds the business key and its surrogate;
  each source system gets its **own satellite** carrying that source's descriptive data
  and load timestamps. Adding a source is a new satellite, never a change to the hub —
  "combining multiple sources into one satellite is never an option"
  ([Varigence](https://docs.varigence.com/bimlflex/delivering-solutions/delivering-data-vault/data-vault-concept-satellite/)).

`currency.currencies` is the base object / hub. `sync.sync_records` is the XREF /
satellite. The design below is those two patterns with a Postgres shape.

### 1.2 The payoff you did not ask for — and it is the bigger one

You described the real goal in the second half of the question:

> *"Invoice will have taxes in API response. I will only store `tax_id` if the tax exists
> in my db or, if it doesn't, go get that `tax_id`, fetch it, insert it, and then put
> that `tax_id` in invoice."*

That is **reference resolution**, and a central crosswalk is what makes it one query
instead of N. With per-table `zoho_id` columns, resolving one invoice page means:
`SELECT id FROM taxes WHERE zoho_id = ANY(…)`, then the same against `currencies`,
`contacts`, `items`, `salespersons`, `warehouses` — six round trips, six different column
names, six different tenancy filters, and a new one every time a module is added.

With one crosswalk it is **one** statement for the whole page across every referenced
module:

```sql
SELECT module, external_id, entity_table, entity_id
FROM   sync.sync_records
WHERE  tenant_id = $1 AND source_system = 'zoho'
  AND  (module, external_id) IN (('taxes','9876'), ('currencies','12'), …);
```

Everything else in §4 — fetch-on-miss, stubs, the pending-reference queue — is built on
that one lookup. The sync-bookkeeping cleanup is the *excuse*; the crosswalk is the
*product*.

---

## 2. Target architecture

```
                   ┌──────────────────────────────────────────┐
  Zoho / SAP ──▶   │  connector (transport, auth, governor)   │
                   └───────────────────┬──────────────────────┘
                                       │ payload
                   ┌───────────────────▼──────────────────────┐
                   │  engine: gate → map → resolve → write    │
                   └───┬──────────────┬───────────────────┬───┘
      gate state /     │              │ mapped values     │ raw + outcome
      identity         │              │                   │
            ┌──────────▼────────┐  ┌──▼───────────────┐  ┌▼──────────────────┐
            │ sync.sync_records │  │ currency.        │  │ sync.sync_payloads│
            │ XREF · 1 row per  │──▶ currencies       │  │ history · append  │
            │ (source, module,  │  │ (canonical/hub)  │  │ RANGE(synced_at)  │
            │  external_id)     │  │ business columns │  │ retention = DROP  │
            │ LIST(source_system)│ │ NO sync columns  │  └───────────────────┘
            └───────────────────┘  └──────────────────┘
                     ▲
                     │ one batched lookup
            ┌────────┴──────────┐
            │ ReferenceResolver │  external id → local id, for every module at once
            └───────────────────┘
```

### 2.1 `sync.sync_records` — the crosswalk (hot, one row per record)

```sql
CREATE TABLE sync.sync_records (
    id                  bigint GENERATED ALWAYS AS IDENTITY,

    -- TenantScopedMixin: tenant_id NOT NULL + nullable organization_id, with the
    -- composite FK (tenant_id, organization_id) -> org_management.organizations
    tenant_id           bigint      NOT NULL,
    organization_id     bigint,                       -- NULL = tenant-wide (settings)

    -- identity of the record IN THE SOURCE
    source_system       text        NOT NULL,         -- 'zoho' | 'sap' | 'manual'
    connection_id       bigint,                       -- which credential produced it
    module              text        NOT NULL,         -- registry key: 'currencies', 'invoices'
    external_id         text        NOT NULL,         -- Zoho currency_id / SAP key

    -- identity of the record LOCALLY (polymorphic — see §2.4)
    entity_table        text        NOT NULL,         -- 'currency.currencies'
    entity_id           bigint,                       -- NULL only while provisional
    link_state          text        NOT NULL DEFAULT 'linked',   -- linked | provisional | orphaned

    -- apply-gate state (was ZohoMirrorMixin, per entity table)
    source_modified_at  timestamptz,                  -- monotonic fence
    raw                 jsonb,                        -- current richest document
    raw_hash            bytea,                        -- no-op detection
    raw_source          text,                         -- list:full | detail_fetch | nested:x | webhook
    raw_synced_at       timestamptz,
    remote_deleted_at   timestamptz,                  -- tombstone evidence (source deleted it)
    sync_version        bigint      NOT NULL DEFAULT 0,   -- counter AND upsert guard (§2.6)
    synced_at           timestamptz NOT NULL DEFAULT now(),
    first_seen_at       timestamptz NOT NULL DEFAULT now(),

    -- opt-in capture (§3.3)
    custom_fields       jsonb,
    comments            jsonb,

    -- AppMetaMixin: app_version, app_metadata   (tenancy conformance — §2.8)
    -- TimestampMixin: created_at, updated_at
    PRIMARY KEY (id, source_system)
) PARTITION BY LIST (source_system);

CREATE TABLE sync.sync_records_zoho    PARTITION OF sync.sync_records FOR VALUES IN ('zoho');
CREATE TABLE sync.sync_records_manual  PARTITION OF sync.sync_records FOR VALUES IN ('manual');
CREATE TABLE sync.sync_records_default PARTITION OF sync.sync_records DEFAULT;

-- THE identity constraint: one crosswalk row per source record. Includes the
-- partition key, so it is legal on a partitioned table — and it is the conflict
-- target the guarded upsert infers (§2.6).
CREATE UNIQUE INDEX uq_sync_records_identity
    ON sync.sync_records (tenant_id, source_system, module, external_id);

CREATE INDEX ix_sync_records_entity ON sync.sync_records (entity_table, entity_id);
CREATE INDEX ix_sync_records_module_live ON sync.sync_records (tenant_id, source_system, module)
    WHERE remote_deleted_at IS NULL;
CREATE INDEX ix_sync_records_provisional ON sync.sync_records (tenant_id, module)
    WHERE link_state = 'provisional';

ALTER TABLE sync.sync_records ALTER COLUMN raw SET COMPRESSION lz4;
```

**Why `LIST (source_system)`:** every engine query knows its source, so pruning always
fires; the partition count stays at 3–5 forever; per-source `VACUUM`, backfill and "drop
SAP entirely" become one DDL; and partitioning **now** avoids a rewrite later, since a
plain table cannot be converted in place and this is the last table you want to rewrite
at 50M rows.

**Why the raw document lives here and not only in history:** replaying a mapping change
("I added `iso_numeric_code` to the field map, re-map every currency without calling
Zoho") needs the *current* raw of *every* record, which history cannot guarantee once
retention has dropped old partitions. One copy, overwritten in place — exactly what
`zoho_raw` does today, just moved off the entity table.

> **Hot-path rule (enforceable in review):** the gate must `SELECT` explicit columns,
> never the whole ORM entity. `raw` is TOASTed out of line, so a column-disciplined gate
> never touches it; a lazy `SELECT *` de-TOASTs a 30 KB invoice document on every single
> payload. The engine already does this in `_stored_versions` — extend the habit.

### 2.2 `sync.sync_payloads` — the history (cold, append-only, time-partitioned)

```sql
CREATE TABLE sync.sync_payloads (
    id              bigint GENERATED ALWAYS AS IDENTITY,
    synced_at       timestamptz NOT NULL DEFAULT now(),
    tenant_id       bigint NOT NULL,          -- LedgerMixin
    organization_id bigint,                   -- LedgerMixin (tenancy conformance — §2.8)
    sync_record_id  bigint NOT NULL,          -- logical ref (no FK: both sides partitioned)
    source_system   text   NOT NULL,
    module          text   NOT NULL,
    external_id     text   NOT NULL,
    entity_table    text,
    entity_id       bigint,
    outcome         text   NOT NULL,          -- inserted | updated | resurrected | tombstoned
    raw             jsonb,                    -- NULL when the module opts out
    raw_hash        bytea,
    raw_source      text,
    sync_version    bigint,
    changed_fields  text[],
    run_id          uuid,
    -- AppMetaMixin: app_version, app_metadata  (LedgerMixin)
    PRIMARY KEY (id, synced_at)
) PARTITION BY RANGE (synced_at);
```

Monthly partitions. **This is genuinely append-only, so `LedgerMixin` is the correct
mixin** (`TenantScopedMixin` + `AppMetaMixin`) — unlike `sync_records` (§2.8).

**Append only when something actually changed.** The apply gate already returns
`unchanged` for a no-op; only `INSERTED / UPDATED / RESURRECTED / tombstoned` append a
payload row. Without that rule a daily scan of 200k unchanged invoices writes 200k fat
rows a day and the design is worse than what it replaces.

**Per-module raw opt-out.** `SyncContract.history_raw: bool = True`. For low-volume
masters keep the full document — it is the audit trail and it is tiny. For high-volume
documents set it `False`: history keeps the hash, the outcome and `changed_fields`, and
the current document still lives on the crosswalk row.

**Sizing.** 1M invoices × ~20 KB raw ≈ 20 GB on `sync_records` (lz4 → well under 10 GB).
With `history_raw=True` and 3 changes per invoice you would add ~60 GB of history per
retention window — which is exactly why documents opt out and masters do not.

### 2.3 What leaves the entity tables

| Today | Tomorrow |
|---|---|
| `ZohoIdentityMixin` (`zoho_id`, `public_id`) on every mirror | `zoho_id` → `sync_records.external_id`. `public_id` → `LocalPublicIdMixin`, only on push-capable tables |
| `ZohoMirrorMixin` (8 columns) on every mirror | `sync_records` columns |
| `custom_fields` HSTORE on every mirror | `sync_records.custom_fields` JSONB |
| a partial unique index on `(tenant_id, zoho_id)` per table | one `uq_sync_records_identity` |
| `_soft_delete_missing` scanning each entity table for live ids | one indexed read of `ix_sync_records_module_live` |

**Do canonical tables keep a `zoho_id` column?** The currency doc §2.1 says yes. I
recommend **no — not as identity.** Source #3 must cost zero migrations on N entity
tables; per-source id columns re-import the problem you are deleting. Concretely: the
engine never reads or matches on an entity-table source id; `Currency.zoho_id` /
`currency_id` already describe themselves in the model as *"L1 source echoes … retained
here only for reconciliation"* and keep exactly that contract (written for debugging,
never authoritative, never uniquely indexed); new modules do not get them at all.

### 2.4 The one real cost: no foreign key on the polymorphic link

`entity_table` + `entity_id` cannot be a foreign key — a column cannot reference N
tables, and a per-module crosswalk would cost the one-query resolver in §1.2. Mitigations:

1. **Startup validation.** The registry already fails the process on a bad spec; extend
   it to assert every registered `entity_table` is a real mapped table carrying the
   declared `match_on` columns. A typo dies at boot, not at 03:00.
2. **One write path.** Only the engine writes `entity_table`, from the registered spec.
3. **Orphan sweeper** in the reconcile lane: rows whose entity is gone flip to
   `link_state='orphaned'` and are reported, never silently deleted.
4. **Soft-delete doctrine helps.** Entity rows are soft-deleted, so the target almost
   never disappears.

### 2.5 Matching: how two sources become one row

When a payload arrives and **no crosswalk row exists**, the engine must decide whether it
is a new canonical row or a second source's view of an existing one. That is a declared
**match key**, not a guess: `match_on = ("currency_code",)`.

1. crosswalk hit on `(tenant, source, module, external_id)` → that entity, done;
2. else match the canonical table on `match_on` → **link** a new crosswalk row to the
   existing entity (this is how Zoho's `USD` and SAP's `USD` become one row);
3. else insert a new canonical row and a new crosswalk row.

Step 2 is where precedence applies: the lower-precedence source gets its own crosswalk
row and its own `raw`, and writes canonical columns only where it outranks the incumbent
(`SyncContract.owned_fields`, the pattern `geo.ZOHO_OWNED_PLACE_FIELDS` already uses).

`match_on = ()` skips step 2 — every source gets its own canonical row until a steward
merges them. Never invent a match.

### 2.6 Concurrency: a guarded upsert, not a read-modify-write

**The problem (review finding 4).** Today's mirror tables inherit `RowVersionMixin` via
`TenantEntityMixin`, so a concurrent apply raises `StaleDataError` instead of silently
overwriting. A naive crosswalk row is a read-modify-write with no such guard: the unique
index stops *duplicate rows*, but two lanes — the very scheduled-scan / webhook /
detail-fetch trio this design is motivated by — can both pass the gate and one loses its
`raw`/`hash`/`version`. That is a regression, and a test that asserts "one row, one
entity" does not catch it.

**Why not `row_version`.** `tests/test_tenancy.py:144` asserts that any table carrying
`row_version` also carries the full `ENTITY_COLUMNS` set — status, is_verified, the four
audit-user columns, `deleted_at`, `deleted_reason`. The crosswalk is not an entity and
those columns would be dead weight invented to satisfy a test.

**The fix — one atomic statement, monotonic guard.** The crosswalk write is a Core
`INSERT … ON CONFLICT DO UPDATE` inferring `uq_sync_records_identity`, with a `WHERE`
that only lets the row move *forward*:

```sql
INSERT INTO sync.sync_records (tenant_id, source_system, module, external_id, …)
VALUES (…)
ON CONFLICT (tenant_id, source_system, module, external_id) DO UPDATE
SET raw = EXCLUDED.raw, raw_hash = EXCLUDED.raw_hash, …,
    sync_version = sync.sync_records.sync_version + 1,
    synced_at = now()
WHERE  EXCLUDED.source_modified_at IS NULL
   OR  sync.sync_records.source_modified_at IS NULL
   OR  EXCLUDED.source_modified_at >= sync.sync_records.source_modified_at
RETURNING id, sync_version;
```

This is strictly better than optimistic locking: the loser writes nothing and raises
nothing (no exception, no page-savepoint rollback into `_apply_one_by_one`), and the
guard is the same monotonic fence the apply gate already implements — now enforced by the
database instead of only decided in Python. `RETURNING` empty ⇒ another lane won ⇒ the
engine counts `stale_ignored`. `sync_version` is an observable counter and the visible
evidence of a write, never a lock.

The entity row keeps its own `row_version` (via `OrgEntityMixin`), so entity-side
concurrency behaves exactly as it does today.

### 2.7 The local soft-delete rule survives the split

**The problem (review finding 3).** `apply.decide` rule: *a row soft-deleted **locally**
(`deleted_at` set, no sync tombstone) is refreshed but never revived — a user's delete is
not the sync's to undo.* Today `RowState.deleted_at` comes from the entity row
(`engine.py:873 _row_state`). The crosswalk has no `deleted_at`, so `RowState.from_xref`
cannot produce it and the rule would silently break.

**Rejected fix:** denormalising `entity_deleted_at` onto the crosswalk. It drifts the
moment an operator soft-deletes a currency through the API — i.e. exactly the case the
rule exists for.

**The fix:** load it. Every record in a page belongs to **one module**, therefore **one
entity table**, so this is a plain join, not a polymorphic one:

```sql
SELECT x.<gate columns>, e.deleted_at
FROM   sync.sync_records x
LEFT   JOIN currency.currencies e ON e.id = x.entity_id
WHERE  x.tenant_id = :t AND x.source_system = 'zoho' AND x.module = 'currencies'
  AND  x.external_id = ANY(:ids);
```

`RowState` is then built from both sides: `remote_deleted_at` from the crosswalk,
`deleted_at` from the entity. `_load_rows` already issues one query per page; it becomes
one *join* per page. `apply.py` stays pure and its decision table is untouched.

**Both sides of that join must opt out of the soft-delete filter, for two different
reasons** (found by mutation-testing the Phase 3 implementation; the first was not what
the design predicted):

1. **The page loader** (`crosswalk.load_page`) needs `include_deleted=True` because the
   automatic criteria turns the `LEFT JOIN` into an inner one — a crosswalk row whose
   entity is soft-deleted drops out of the result *entirely*, the engine reads "no
   crosswalk row", treats a known record as new and inserts a duplicate. The failure is
   a duplicate row, not a bad gate decision.
2. **The entity lookup** (`_resolve_entity`) needs it so a soft-deleted entity is found
   and reused rather than re-created.

The gate rule itself ("refreshed, never revived") is enforced by the engine simply not
clearing `deleted_at` unless `decision.revive` is set, and `revive` requires a *sync*
tombstone (`remote_deleted_at`), which a local delete never sets. `RowState.deleted_at`
matters to the gate only via `legacy_tombstone`, which a crosswalk row never carries; it
is still populated because `_stored_versions` uses it to force a detail re-fetch for a
tombstoned record (`_already_current`).

**Tombstoning writes both sides.** `_soft_delete_missing` (`engine.py:710`) today sets
`deleted_at` **and** `remote_deleted_at` on the entity. After the split it must set
`deleted_at` on the **entity** and `remote_deleted_at` on the **crosswalk**, in one
transaction — otherwise a tombstone is half-recorded and the resurrection fence fails.

### 2.8 Tenancy conformance (review findings 1 & 2)

`tests/test_tenancy.py:186 test_every_table_is_entity_ledger_or_an_explained_global`
requires every non-global table to carry `LEDGER_COLUMNS = {tenant_id, organization_id,
app_version, app_metadata}`, and — if it carries `row_version` — the full `ENTITY_COLUMNS`
set. Rev 1's three tables would all have failed it.

| Table | Mixins | Why |
|---|---|---|
| `sync.sync_records` | `TenantScopedMixin`, `AppMetaMixin`, `TimestampMixin` | **Not a ledger** — it is updated in place (`raw`/`hash`/`version` overwritten), and `LedgerMixin` is by doctrine append-only. Not an entity either: no status, no verification, no audit user, no soft delete. Carrying no `row_version` keeps it out of the `ENTITY_COLUMNS` branch; §2.6 is the concurrency answer |
| `sync.sync_payloads` | `LedgerMixin` | genuinely append-only — the mixin fits exactly |
| `sync.pending_references` | `LedgerMixin` | operational queue; rows are inserted and deleted, never versioned |

Rev 1 also claimed "`LedgerMixin`: app_version, app_metadata, created_at, updated_at".
**False** — `LedgerMixin` is `TenantScopedMixin + AppMetaMixin` and has **no** timestamps
(`app/database/mixins.py:455`). `sync_records` takes `TimestampMixin` explicitly.

Two wiring changes rev 1 missed entirely:

* `alembic/env.py:80` — `_OWNED_SCHEMAS` must gain `"sync"`, or autogenerate will not see
  the schema and `_include_name` will filter it out of every comparison.
* `tests/conftest.py:37` — `_TEST_TABLES` must gain the three tables in FK-safe order
  (`sync.pending_references`, `sync.sync_payloads`, `sync.sync_records`), or state leaks
  between tests.

---

## 3. Engine changes

### 3.1 `SyncContract` — per-module, per-source declaration

```python
class SyncContract(BaseModel):
    source_system: str = "zoho"
    entity_table: str                            # 'currency.currencies'
    match_on: tuple[str, ...] = ()               # §2.5
    crosswalk: bool = False                      # opt-IN; False = today's in-place mirror
    history_raw: bool = True                     # §2.2
    capture_custom_fields: bool = True
    capture_comments: bool = False
    owned_fields: frozenset[str] = frozenset()   # canonical columns this source may write
    references: tuple[ReferenceRule, ...] = ()   # §4
```

`crosswalk` defaults to **False**: the five existing modules keep today's behaviour
byte-for-byte until each is converted, one PR at a time.

### 3.2 `SourceConnector` — the transport seam

```python
class SourceConnector(Protocol):
    name: str
    async def list_pages(self, cfg, params, start_page) -> AsyncIterator[Page]: ...
    async def fetch_detail(self, cfg, external_id) -> dict: ...
    def external_id_of(self, payload, cfg) -> str | None: ...
    def modified_at(self, payload) -> datetime | None: ...
```

`ZohoConnector` wraps today's `zoho_client` + governor + breaker unchanged. This is a
seam for a *second source's transport* — it is **not** what would make the engine
portable out of `app/modules/zoho/` (§3.5).

### 3.3 Mixins after the split

| Mixin | Columns | Lives on |
|---|---|---|
| `LocalPublicIdMixin` *(new)* | `public_id` | push-capable entity tables only |
| `ZohoIdentityMixin` / `ZohoMirrorMixin` | unchanged | **deprecated**; only unconverted modules |

`custom_fields` becomes JSONB on the crosswalk. The HSTORE → JSONB migration for existing
mirrors happens per module *as that module is converted*, never as a fleet-wide sweep.

### 3.4 Apply path, two-model

```
payload
  ├─ external_id = connector.external_id_of(payload)
  ├─ xref+entity = crosswalk LEFT JOIN entity, page-batched, one query      ← §2.7
  ├─ gate  = decide(RowState(xref, entity), Incoming(...))                  ← unchanged logic
  │           └─ unchanged / stale → record event, return
  ├─ values = map_inbound(cfg, payload)
  ├─ values |= resolver.resolve_references(cfg, payload)                    ← §4
  ├─ entity = xref.entity | match_on lookup | new                           ← §2.5
  ├─ WRITE entity   (business columns only, ORM, row_version as today)
  ├─ UPSERT xref    (guarded, atomic — no rows ⇒ stale_ignored)             ← §2.6
  └─ APPEND sync_payloads  (only when the gate wrote)
```

### 3.4a Known cost of the crosswalk path (accepted, not hidden)

**One guarded upsert per record, not per page.** The batched page apply still loads gate
state in one query and flushes entities once, but each written record issues its own
`INSERT … ON CONFLICT` round trip. Batching them would mean `executemany`, and a
`RETURNING` under the monotonic guard does not line up with its input rows — a rejected
row returns nothing, so results cannot be mapped back to records. Correctness before
throughput: only *writers* pay it, and in steady state a scan is almost all no-ops. If an
invoice-scale module ever makes this hurt, the fix is a two-step (bulk upsert without
`RETURNING`, then one `SELECT` of the winners), not weakening the guard.

**One entity load per writer.** The page preload deliberately fetches gate columns plus
`deleted_at`, not whole entities, because most payloads in a steady-state scan are
`unchanged` and would never touch the entity. A record that passes the gate then loads its
entity individually. First-ever syncs pay this on every row; a batched entity preload
keyed on the writers' `entity_id`s is the obvious follow-up if that shows up in a profile.

### 3.5 Where the code lives — the engine does **not** move

**Rev 1 claimed the engine is "~95 % source-neutral" and that it moves to
`app/modules/sync/` in Phase 4. Both were wrong, and they contradicted rev 1's own
file-by-file table, which left `engine.py` under `zoho/sync/`.**

`engine.py:66-90` imports `zoho.control.events`, `zoho.core.client`,
`zoho.core.exceptions`, `zoho.sync.{config,mapper,mixins,models,registry}`, plus lazy
`zoho.control.config` and `app.tasks.zoho_sync`. Moving it under a "sync may not import
zoho" contract means abstracting **events, stats, exceptions, models, registry, config and
task dispatch** — seven seams, not one connector.

**So: the engine stays at `app/modules/zoho/sync/engine.py` for this entire plan.**
`app/modules/sync/` contains only genuinely source-neutral *new* code with zero imports
from `app.modules.zoho`:

| New file | Contents |
|---|---|
| `app/modules/sync/models.py` | `SyncRecord`, `SyncPayload`, `PendingReference` |
| `app/modules/sync/contract.py` | `SyncContract`, `ReferenceRule`, `OnMissing` |
| `app/modules/sync/crosswalk.py` | the guarded upsert (§2.6), the batched lookup (§1.2), the join-with-entity loader (§2.7) |
| `app/modules/sync/matching.py` | `match_on` resolution (§2.5) |
| `app/modules/sync/references.py` | pure policy: which misses get FETCH / STUB / DEFER / NULL. The actual fetch is an injected callable, so this file never imports the engine |

Existing files changed **in place**: `zoho/sync/engine.py` (two-model path),
`zoho/sync/registry.py` (contract validation instead of `_GATE_COLUMNS`),
`zoho/sync/config.py` (`contract` field), `zoho/sync/mapper.py` (JSONB custom fields),
`zoho/control/retention.py` (§3.6).

`.importlinter` gains: `app.modules.sync` may not import `app.modules.zoho` or any
feature module. Moving `apply.py` / `mapper.py` / `config.py` down into
`app/modules/sync/` is **deliberately out of scope** — it churns five working modules for
no functional gain and belongs in the PR that lands the second source.

### 3.6 Retention must be generalised, not "registered" (review finding 5)

Rev 1 said `sync_payloads` is "one more table name in the same machinery, one more policy
row". It is not. `app/modules/zoho/control/retention.py` is hardcoded to
`EVENTS_TABLE = "zoho_sync_events"` (`:40`), **daily** partition names (`:104`), the
`(id, occurred_at)` pk tuple (`:195`), the `public.` schema in its `to_regclass` probe
(`:115`), and `EVENT_CLASS` (`control/models.py:208`) for policy matching.
`sync_payloads` is monthly, in the `sync` schema, keyed `(id, synced_at)`, and has
`outcome`, for which `ZohoRetentionPolicy.event_class` has no analogue.

> `pg_partman` is installed in the deployment image and `pg_partman_bgw` is preloaded —
> but it is **not an option here**: `alembic/versions/…_zoho_control_plane.py:8` records
> that partition maintenance was hand-rolled *precisely because the scratch test image
> does not ship pg_partman*. Generalising our own code is the only path that keeps the
> migration runnable in CI.

The refactor is a descriptor plus parameterisation:

```python
@dataclass(frozen=True, slots=True)
class PartitionedTable:
    qualified: str                     # 'zoho_sync_events' | 'sync.sync_payloads'
    ts_column: str                     # 'occurred_at'      | 'synced_at'
    pk: tuple[str, str]                # ('id','occurred_at') | ('id','synced_at')
    period: Literal["daily", "monthly"]
    class_column: str | None           # None (uses EVENT_CLASS) | 'outcome'
    class_map: Mapping[str, str]       # outcome/event_type -> policy class

EVENTS   = PartitionedTable("zoho_sync_events", "occurred_at", ("id","occurred_at"),
                            "daily", None, EVENT_CLASS)
PAYLOADS = PartitionedTable("sync.sync_payloads", "synced_at", ("id","synced_at"),
                            "monthly", "outcome", PAYLOAD_CLASS)
```

`partition_name`, `ensure_partitions`, `list_partitions`, `drop_expired_partitions` and
`purge_events` each take a `PartitionedTable` **defaulting to `EVENTS`**, so existing
callers and tests are untouched; `run_maintenance` loops over `MAINTAINED`. The existing
retention tests must pass unchanged — that is the regression gate for this refactor.

**A correctness rule the monthly period forced out (found while building this).**
`drop_expired_partitions` measured a partition's age from its **start** date. For daily
partitions start == end, so this was invisible. For a monthly partition it silently drops
live data: on 20 March, February's partition is 47 days old by its start date and would
be dropped under a 30-day keep — while its last rows are only 20 days old. Age is now
measured from `PartitionedTable.last_day_held()`, the newest date the partition can hold,
which is the day itself for a daily table (behaviour unchanged) and the month's last day
for a monthly one. `tests/zoho_core/test_retention_payloads.py::
test_a_month_is_not_dropped_while_its_last_days_are_still_kept` is the regression test,
and it was mutation-checked: reverting `last_day_held` to the start date makes it fail.

**Policy classes need no schema change.** `ZohoRetentionPolicy.event_class` is a class
label, not an event type; `PartitionedTable.class_map` is what maps a table's own column
to it (`EVENT_CLASS` over `event_type` for events, `PAYLOAD_CLASS` over `outcome` for
payloads). Retention for a new table is therefore policy **rows**, not DDL.

---

## 4. Reference resolution

`NestedEntityRule` already handles *embedded* child payloads. References are the other
half: the parent carries only an **id**.

```python
ReferenceRule(
    attr="tax_id", module="taxes",
    fk="tax_id",                    # canonical column receiving the LOCAL id
    external_fk="tax_external_id",  # optional: keep the source id alongside
    on_missing=OnMissing.STUB, many=False,
)
```

### 4.1 The algorithm, per page (not per record)

1. **Collect** every `(module, external_id)` pair named by any rule across the page.
2. **Resolve in one query** (§1.2) → `{(module, external_id): entity_id}`, cached for the
   run (an invoice page references the same 12 taxes over and over).
3. **Apply hits.** Set `fk`. **Always also set `external_fk`**, even on a hit — it is
   free, and it lets a reconciler repair any linkage bug later without re-reading Zoho.
4. **Misses, by declared policy:**

| `on_missing` | Behaviour | Use for |
|---|---|---|
| `FETCH` | call the owning module's detail endpoint now, through the existing governor/breaker, apply it, link. Single-flight per `(module, external_id)` per run; counted against a budget | low-volume masters |
| `STUB` *(default for documents)* | insert a minimal canonical row (`status='provisional'`) + crosswalk row `link_state='provisional'`, link the FK immediately, enqueue a real fetch | contacts, items — anything high-cardinality |
| `DEFER` | write `external_fk`, leave `fk` NULL, append to `sync.pending_references` | genuinely optional references |
| `NULL` | keep only `external_fk` | ids we never intend to master |

5. **Budget.** `max_reference_fetches_per_run` (default ~50). An invoice page that
   triggers 200 unplanned detail calls will trip the Zoho rate limiter and take the
   run's whole quota with it. Over budget, `FETCH` degrades to `STUB` and logs
   `sync.reference.budget_exhausted`. **"Go fetch it and insert it first" is correct
   per record and catastrophic per page without this ceiling.**

### 4.2 Why `STUB` and not `FETCH` as the default

A stub is one INSERT; a fetch is one API call against a quota shared by every module in
the fleet. The stub links immediately (the invoice is correct and queryable *now*) and is
idempotent: the later real sync finds the crosswalk row and **fills the same row**, no
duplicate, because that row already carries the external id.

### 4.3 Ordering: masters before documents — a scheduler change, not a config field

**Review finding 7.** `planner.plan()` (`control/planner.py:118`) is a pure, flat lane
scheduler over `ModuleView` with `max_concurrent_runs=2`. It has no notion of module
ordering, and `ModuleView` carries no `depends_on`. Declaring `depends_on` on the config
does nothing by itself.

Making "masters before documents" real requires: `depends_on` on `ModuleView`; a
topological rank computed once in the registry (cycle ⇒ boot failure); `plan()` suppressing
a dependent lane until each dependency has a `last_full_sync_time` (a field `ModuleView`
does not currently carry, so `ModuleView` and its builder change too); and the candidate
sort becoming rank-major. That is a real change to a heavily table-tested pure function,
so it is **its own phase (7)**, not a bullet inside the resolver phase.

The resolver does not need it. A cold cache is exactly what `STUB` and `FETCH` are for;
the DAG only lowers the miss rate.

### 4.4 `sync.pending_references`

```sql
CREATE TABLE sync.pending_references (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id bigint NOT NULL, organization_id bigint,       -- LedgerMixin
    source_system text NOT NULL, module text NOT NULL, external_id text NOT NULL,
    waiting_table text NOT NULL, waiting_id bigint NOT NULL, waiting_column text NOT NULL,
    attempts int NOT NULL DEFAULT 0, last_attempt_at timestamptz, created_at timestamptz,
    -- AppMetaMixin: app_version, app_metadata
    UNIQUE (tenant_id, source_system, module, external_id, waiting_table, waiting_id, waiting_column)
);
```

Drained by a reconcile lane: resolve, `UPDATE <waiting_table> SET <waiting_column> = …`,
delete the row. Also the honest answer to "what did we fail to link?" — a number an
operator can watch instead of silent NULLs.

---

## 5. Currencies — the first implementation

Currencies are the right pilot precisely because they are boring: one unpaginated
endpoint, no `last_modified_time`, hundreds of rows, one child collection. Everything
risky in the design is exercised, nothing risky in the data is.

| File | Change |
|---|---|
| `app/modules/currencies/model.py` | `Currency` unchanged except `zoho_id`/`currency_id` documented as non-authoritative echoes. `ExchangeRate` gains `external_source` + `external_id`; unique becomes `(tenant, currency, effective_date, rate_source)` |
| `app/modules/currencies/enums.py` | `CurrencySource` (`zoho`, `sap`, `manual`) |
| `app/modules/currencies/service.py` | owned-field guard: a PATCH touching a `ZOHO_OWNED_CURRENCY_FIELDS` column on a crosswalk-linked row → 422 |
| `app/modules/currencies/zoho/` *(new)* | `spec.py`, `fields.py`, `hooks.py`, `__init__.py` |
| `app/modules/zoho_currencies/` | deleted at **cutover** (§6 M4), not before — see the phase-0 note |

```python
contract=SyncContract(
    source_system="zoho",
    entity_table="currency.currencies",
    match_on=("currency_code",),       # how SAP's USD finds Zoho's
    crosswalk=True,
    history_raw=True,                  # tiny module: keep every document
    owned_fields=ZOHO_OWNED_CURRENCY_FIELDS,
)
```

`post_upsert` projects `payload['exchange_rates']` into `currency.exchange_rates`
(`rate_source='zoho'`) and refreshes the `Currency.exchange_rate` **cache**; the truth
stays in `exchange_rates`.

---

## 6. Migration

**M1 — `sync` schema (additive).** `CREATE SCHEMA sync`; the three tables, the LIST
partitions, 3 months of RANGE partitions, the retention-policy rows. `_OWNED_SCHEMAS` and
`_TEST_TABLES` updated in the same PR (§2.8). Nothing reads them yet.

**M2 — currency expand (additive).** `ExchangeRate.external_source` / `external_id`; the
rate unique index gains `rate_source`.

**M3 — backfill (data, idempotent, re-runnable).** Every live `zoho_currencies` row →
a `currency.currencies` row (matched on `(tenant, code)`, inserted when absent, business
columns **filled only when absent**) + one `sync.sync_records` row (`source_system='zoho'`,
`module='currencies'`, `entity_table='currency.currencies'`, gate columns copied,
`custom_fields` via `hstore_to_jsonb`) + one `exchange_rates` row. `organization_id`
resolved via the connection→org map; unresolvable rows **quarantined and reported**,
never guessed. Emits a reconciliation report: matched vs inserted, quarantined, and every
field conflict it declined to overwrite. Dry-run on a restored copy first.

**M4 — cutover.** Flip the spec, run one sync, assert the report is all-`unchanged` (the
hashes match ⇒ the backfill was faithful). Then delete `app/modules/zoho_currencies/`.

**M5 — contract (destructive, gated).** Drop `zoho_currencies`.

---

## 7. Phases

> **Phase-0 note (changed in rev 2).** Rev 1 deleted `app/modules/zoho_currencies/`
> first. That would leave currencies with no registered adapter for four phases —
> against this plan's own no-big-bang doctrine. The deletion moves to M4, where a working
> replacement already exists.

| # | Phase | Done when |
|---|---|---|
| 1 | ✅ **`sync` schema + package.** M1 (`b8d31c7f4a52`); `SyncRecord`/`SyncPayload`/`PendingReference`; `SyncContract` (`crosswalk=False` default); `crosswalk.py` upsert + lookup; `_OWNED_SCHEMAS`, `_PARTITIONED_PARENTS`, `_TEST_TABLES`, `.importlinter` | **done.** Conformance passes; DDL verified on PG18 (LIST/RANGE strategies, partition routing, unique index on every partition, lz4); guarded upsert rejects an older payload with no lost update; migration round-trips; 9 crosswalk tests |
| 2 | ✅ **Retention generalised.** `PartitionedTable` + `MAINTAINED`; `run_maintenance` covers both tables; policy seed `c41e9b7d2f60` | **done.** The 6 existing retention tests pass **unchanged**; 11 new tests cover monthly partitions, the `sync` schema, outcome→class mapping and the `last_day_held` rule (mutation-checked) |
| 3 | ✅ **Engine two-model path.** `apply_payload` split into a dispatcher over `_apply_in_place` (untouched) and `_apply_crosswalk`; join-loader (§2.7), guarded upsert (§2.6), history append, `ModuleSyncConfig.contract`, registry contract validation, `_tombstone_crosswalk` writing both sides | **done.** All 319 pre-existing zoho tests pass with the engine changed — parity is structural, since the old body is byte-for-byte intact. 7 new crosswalk tests, mutation-checked (removing either `include_deleted`, the upsert guard, or the write-only-history rule turns them red) |
| 4 | **Currency adapter.** M2, `currencies/zoho/`, ownership guard, rate projection | adapter tests against saved payloads, no network |
| 5 | **Backfill + cutover.** M3, M4, M5 | post-cutover sync reports all-`unchanged`; `zoho_currencies` gone |
| 6 | **Resolver.** `ReferenceRule`, batched resolve, `STUB`/`FETCH`/`DEFER`, budget, `pending_references` drain lane | a fixture invoice payload links 6 references in 1 query; budget exhaustion degrades instead of hammering |
| 7 | **Planner ordering.** `depends_on` → `ModuleView` → topological rank → `plan()` suppression + rank-major sort (§4.3) | planner table tests cover "dependent waits for a dependency's first full sync" |
| 8 | **Convert the other four masters**, one PR each (organizations, taxes, locations, zoho_users) | each module's post-cutover report is all-`unchanged` |
| 9 | **SAP-ready.** `SAPConnector`; a second contract on a shared module | a SAP currency payload links to the Zoho-mastered `USD` row and writes only its owned fields |

---

## 8. Testing

* **Gate** — existing pure decision-table tests, unchanged. That they need no edits is the
  regression test for §3.4.
* **Local soft-delete (§2.7)** — an entity with `deleted_at` set and no crosswalk
  tombstone is refreshed, **never revived**; the join-loader supplies `deleted_at`.
* **Tombstone split** — `_soft_delete_missing` sets entity `deleted_at` **and** crosswalk
  `remote_deleted_at`; a later not-newer payload cannot revive.
* **Lost update (§2.6)** — two sessions apply different payloads for one `external_id`
  concurrently; assert one row, the **newer** `source_modified_at` and its `raw_hash`
  survive, `sync_version` incremented exactly once per winning write, loser counted
  `stale_ignored`. (Rev 1's "one row, one entity" assertion passes even when an update is
  lost — this test is the one that matters.)
* **Engine parity** — a `crosswalk=False` module emits the identical write set to today.
* **Crosswalk** — insert / update / resurrect / tombstone land the right state and the
  right (or no) `sync_payloads` row; an unchanged re-run appends nothing.
* **Matching** — same `match_on` links to the existing entity; different inserts a new
  one; `match_on=()` never merges.
* **Tenancy conformance** — the three new tables pass `test_every_table_is_entity_ledger_
  or_an_explained_global` without being added to `GLOBAL_TABLES`.
* **Retention** — existing `zoho_sync_events` tests pass unchanged after the
  `PartitionedTable` refactor; monthly `sync_payloads` partitions are created ahead and
  dropped when expired.
* **Resolver** — one query per page; `STUB` rows are *filled*, not duplicated; `FETCH`
  single-flights; budget exhaustion degrades to `STUB`.
* **Migration** — a seeded `zoho_currencies` row produces the exact canonical row,
  crosswalk row and rate; a NULL-org row is quarantined, not guessed.
* `lint-imports`, `ruff`, full suite at every phase boundary.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| The engine change breaks the four working masters | `crosswalk=False` default + parity snapshot tests; conversion one module per PR (Phase 8) |
| Lost updates on the hot crosswalk row | guarded atomic upsert (§2.6) + the lost-update test |
| The local-delete rule breaks silently | join-loader (§2.7), not a denormalised copy; explicit test |
| Polymorphic link has no FK | registry boot validation + single write path + orphan sweeper |
| Retention refactor breaks event retention | existing tests must pass unchanged — that is the gate |
| `sync_records` becomes the hottest table | LIST partitioning from day 1; skinny gate reads; lz4 on `raw` |
| Reference `FETCH` storms the Zoho quota | per-run budget, single-flight, `STUB` default |
| History volume explodes on documents | append only on real change; `history_raw=False`; monthly drops |
| Backfill clobbers an operator edit | fill-only-when-absent; conflicts reported; dry run first |

---

## 10. Open decisions

1. **Organization for Zoho *settings* records** (currencies, taxes): the connection's
   organization, a tenant default org, or relax `currencies` to tenant-scoped?
   **Deferred by the owner (2026-09-21) — revisit before Phase 4.** It blocks M3 and
   therefore Phases 4–5; Phases 3, 6 and 7 do not depend on it.
2. **`match_on` for currencies:** `(currency_code,)` tenant-wide or
   `(organization_id, currency_code)`? Follows from #1.
3. **Keep the `zoho_id` / `currency_id` echo columns on `Currency`**, or drop them in M5?
4. ~~**`sync_payloads` retention**~~ — **settled.** Seeded in `c41e9b7d2f60` as
   180 days for `*` and `success`, 365 for `failure` (tombstones; "when did this record
   disappear" is the audit question). Changing it is a policy row, never a migration, so
   this was never worth blocking on.
5. **Phase 8 ordering:** `taxes` first (the first real reference target) or
   `organizations` (the smallest)?

---

## Appendix A — rev 1 defects fixed

| # | Defect | Fix |
|---|---|---|
| 1 | `sync_payloads` / `pending_references` lacked `LEDGER_COLUMNS` → would fail `test_every_table_is_entity_ledger_or_an_explained_global`; `_OWNED_SCHEMAS` and `_TEST_TABLES` unmentioned | §2.8 — `LedgerMixin` on both, plus both wiring changes as Phase-1 deliverables |
| 2 | `sync_records` labelled a ledger; "LedgerMixin: …, created_at, updated_at" was false | §2.8 — `TenantScopedMixin + AppMetaMixin + TimestampMixin`, explicitly neither ledger nor entity |
| 3 | The local-soft-delete rule silently broke (`RowState.deleted_at` has no crosswalk source); tombstone split unspecified | §2.7 — join to the entity (one module ⇒ one table); `_soft_delete_missing` writes both sides |
| 4 | Read-modify-write with no `row_version` = lost updates; the proposed test could not catch it | §2.6 — guarded atomic upsert + §8 lost-update test; `row_version` rejected with the conformance reason |
| 5 | "Retention is one table name + one policy row" | §3.6 — `PartitionedTable` refactor; `pg_partman` ruled out with the migration's own reason |
| 6 | "Engine is ~95 % source-neutral"; engine moves to `app/modules/sync/` — false, and self-contradictory | §3.5 — the engine does not move; `app/modules/sync/` is new neutral code only; the seven seams named |
| 7 | Planner DAG presented as a config field inside the resolver phase | §4.3 — named as a `plan()` + `ModuleView` change, promoted to its own Phase 7 |

Also corrected: Postgres 17 → **18**; Phase 0's premature deletion of
`app/modules/zoho_currencies/` moved to cutover (§7).

## Appendix B — what changed from `currency-sync-consolidation.md`

| That doc | This doc | Why |
|---|---|---|
| one per-module `currency.currency_sync` | one platform-wide `sync.sync_records` | a per-module sync table still costs DDL per module and cannot serve the cross-module resolver (§1.2) |
| open decision: A or B | **both**, as two tables | they are two workloads (§1) |
| `RANGE (synced_at)` on the gate table | `LIST (source_system)` on the gate, `RANGE` on history | uniqueness and pruning on the hot path |
| canonical row keeps `ZohoIdentityMixin` | crosswalk owns identity; entity source ids are echoes | source #3 must cost zero entity-table migrations |
| source-named column groups (`zoho_*`, `sap_*`) | one neutral column set + `source_system` discriminator | adding SAP is rows, not columns |
| — | `match_on` / merge semantics (§2.5) | without it, SAP creates a duplicate `USD` |
| — | `ReferenceRule` + resolver + budget (§4) | the actual goal: normalising source ids into local FKs at invoice scale |
