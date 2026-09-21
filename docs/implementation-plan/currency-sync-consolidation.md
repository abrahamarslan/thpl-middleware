# Consolidate currencies into one canonical store + a source-neutral Zoho sync engine

**Status:** proposed · **Owner:** backend / platform data · **Schema:** `currency`
**Supersedes:** the half-step that moved the Zoho mirror to `app/modules/zoho_currencies/`
**Related:** [`docs/zoho-sync-implementation/adapters/currencies.md`](../zoho-sync-implementation/adapters/currencies.md) ·
[`docs/tenancy/README.md`](../tenancy/README.md) · `app/modules/zoho/sync/` · `app/modules/currencies/`

---

## 1. Problem

Two currency stores exist: the legacy Zoho mirror `zoho_currencies` and the canonical
`currency.currencies`. `zoho_currencies` duplicates the business fields, gives downstream
modules a second `currency_id` to choose between, and can drift. We want **one currency
master**, fed by **many sources** (Zoho today, SAP next), with the Zoho sync engine
**not** hard-wired to a separate mirror table.

## 2. Design principles (from review)

1. **The canonical row keeps `ZohoIdentityMixin`.** `currency.currencies` carries the
   source identity (`zoho_id`, and later `sap_id` via a `SAPIdentityMixin` migration) plus
   all business fields.
2. **Sync bookkeeping is not on the canonical row.** `ZohoMirrorMixin` — `zoho_raw`,
   `zoho_raw_hash`, `zoho_raw_synced_at`, `zoho_last_modified_time`, `synced_at`,
   `sync_source`, `sync_version`, `remote_deleted_at` — lives in a **partitioned sync
   table** we design.
3. **The engine is source-neutral; the columns are source-named.** Do **not** rename to
   `external_*`. A source is a `(identity mixin, mirror mixin, column group)` triple:
   `ZohoIdentityMixin`/`ZohoMirrorMixin` today, `SAPIdentityMixin`/`SAPMirrorMixin` later.
   The engine reads the column names from config, so one engine drives all sources.
4. **Custom fields and comments are first-class, JSONB, configurable.** Add
   `ZohoCustomFieldsMixin` (`custom_fields` JSONB, replacing the current HSTORE) and
   `ZohoCommentsMixin` (`comments` JSONB). Almost every Zoho payload carries them; a module
   opts in and the engine captures them.

## 3. Target architecture

### 3.1 Canonical — `currency.currencies`

* Mixins: `BigIntPKWithUUIDMixin`, `OrgEntityMixin`, `VerificationMixin`,
  `DeactivationMixin`, `PolymorphicOwnerMixin`, `SoftDeleteFilteredMixin`, **`ZohoIdentityMixin`**.
* Business columns unchanged (`currency_code`, `currency_name`, `currency_symbol`,
  `currency_format`, `price_precision`, `is_base_currency`, `exchange_rate`,
  `effective_date`, formatting/rounding/accounting/risk fields).
* **No mirror columns.**
* Later: add `SAPIdentityMixin` (`sap_id`) by migration; the row can carry both ids.

`public_id` reconciliation: `ZohoIdentityMixin` currently also owns `public_id`, which
duplicates `uuid` from `BigIntPKWithUUIDMixin` (and is only needed for outbound
correlation; currencies are inbound-only). **Split the mixin**: `ZohoIdentityMixin` keeps
`zoho_id`; move `public_id` into a new `LocalPublicIdMixin` that only push-capable tables
compose. Canonical currency composes only `ZohoIdentityMixin` + `uuid`.

### 3.2 Sync store — a partitioned `currency.currency_sync`

The mirror columns move here. Two viable shapes; **A is recommended**.

**A. Append-only history, time-partitioned (recommended).**
Every applied payload appends one row; the **latest row per source identity is the current
gate state**.

```sql
CREATE TABLE currency.currency_sync (
    id                      bigint GENERATED ALWAYS AS IDENTITY,
    tenant_id               bigint NOT NULL,
    organization_id         bigint NOT NULL,
    currency_id             bigint NOT NULL,          -- set by the projection hook
    source_system           text   NOT NULL,          -- 'zoho' now, 'sap' later

    -- ZohoMirrorMixin (the zoho-owned group)
    zoho_id                 varchar(50),
    zoho_raw                jsonb,
    zoho_raw_hash           bytea,
    zoho_raw_synced_at      timestamptz,
    zoho_last_modified_time timestamptz,
    sync_source             varchar(48),
    sync_version            bigint NOT NULL DEFAULT 0,
    remote_deleted_at       timestamptz,

    -- ZohoCustomFieldsMixin / ZohoCommentsMixin
    custom_fields           jsonb,
    comments                jsonb,

    synced_at               timestamptz NOT NULL DEFAULT now(),
    -- audit / soft delete
    created_by, created_by_name, updated_by, updated_by_name,
    deleted_at, deleted_by, deleted_reason,
    PRIMARY KEY (id, synced_at)
) PARTITION BY RANGE (synced_at);

-- Latest state per Zoho id (gate lookup), per partition:
CREATE INDEX ix_currency_sync_zoho_latest
    ON currency.currency_sync (tenant_id, zoho_id, synced_at DESC)
    WHERE zoho_id IS NOT NULL;
```

* Later `SAPMirrorMixin` adds the `sap_*` column group to this same table via migration;
  `SAPIdentityMixin` adds `sap_id` to `currencies`.
* Partitions are created by the retention job (monthly), like `zoho_sync_events`.
* **Why the latest row, not a unique current row:** Postgres requires a partitioned
  table's unique index to include the partition key. A time-partitioned table cannot
  enforce one live row per `zoho_id`. Append-only history sidesteps that, keeps an audit
  trail, and matches the platform's existing `zoho_sync_events` pattern.

**B. Hash-partitioned current state (alternative).** Partition by `HASH(currency_id)` and
keep one live row per `(tenant, source_system, zoho_id)` with a real unique index
(`zoho_id` is the partition key, so the unique is legal). No time retention; history is a
separate concern. Choose B if the gate must be an O(1) unique lookup at scale.

**Optional fast path.** If scanning the latest partition row per record ever hurts, add a
small unpartitioned `currency.currency_sync_state` (one row per `(source, id)`) as the
gate's working state; the partitioned table stays the history. Not needed for currency
volume (hundreds of rows).

### 3.3 Mixin catalogue (engine)

| Mixin | Columns | Where |
|---|---|---|
| `ZohoIdentityMixin` | `zoho_id` | canonical row |
| `LocalPublicIdMixin` *(new, split out)* | `public_id` | push-capable tables only |
| `ZohoMirrorMixin` | `zoho_raw`, `zoho_raw_hash`, `zoho_raw_synced_at`, `zoho_last_modified_time`, `synced_at`, `sync_source`, `sync_version`, `remote_deleted_at` | sync table |
| `ZohoCustomFieldsMixin` *(new)* | `custom_fields` **JSONB** | sync table (configurable) |
| `ZohoCommentsMixin` *(new)* | `comments` **JSONB** | sync table (configurable) |
| `SAPIdentityMixin` / `SAPMirrorMixin` *(future)* | `sap_id`, `sap_raw`, … | canonical / sync table |

`custom_fields` moves out of `ZohoMirrorMixin` (it is HSTORE today) into
`ZohoCustomFieldsMixin` as JSONB, so a table opts in independently.

### 3.4 Engine — source-neutral contract + data/state models

`app/modules/zoho/sync/config.py` gains a `SyncContract`; defaults reproduce today's
behaviour exactly, so no existing module changes:

```python
class SyncContract(BaseModel):
    identity: str = "zoho_id"                 # column on the canonical/data row
    source_system: str = "zoho"               # discriminator written to the sync row
    # mirror columns, on the STATE model
    raw: str = "zoho_raw"
    raw_hash: str = "zoho_raw_hash"
    raw_synced_at: str = "zoho_raw_synced_at"
    last_modified: str = "zoho_last_modified_time"
    sync_source: str = "sync_source"
    sync_version: str = "sync_version"
    remote_deleted: str = "remote_deleted_at"
    synced_at: str = "synced_at"
    # opt-in capture
    custom_fields: str | None = "custom_fields"
    custom_fields_key: str = "custom_fields"
    comments: str | None = "comments"
    comments_key: str = "comments"

class ModuleSyncConfig(...):
    contract: SyncContract = SyncContract()
```

`ZohoModuleDefinition` gains optional **`state_model`** (the sync table). When set, the
engine runs a **two-model** write path:

```
payload ──▶ gate(latest state row) ──▶ map(field_map → canonical columns)
                                        │
        canonical row (currencies) ◀────┘  upsert by identity (zoho_id)
        sync row (currency_sync)   ◀──────  append raw/hash/version/custom_fields/comments
                                             + set currency_id (projection hook)
```

When `state_model` is unset, the engine behaves exactly as today (in-place mirror) — every
current module keeps working untouched.

### 3.5 Currency adapter

```python
CURRENCIES_CONFIG = resolve_module_config(
    module="currencies",
    endpoint="/settings/currencies", zoho_id_attr="currency_id",
    paginated=False, strategy=FULL, direction=INBOUND, detail_required=False,
    contract=SyncContract(identity="zoho_id", source_system="zoho"),
    field_map=[
        FieldMapping(zoho="currency_code",   local="currency_code"),
        FieldMapping(zoho="currency_name",   local="currency_name"),
        FieldMapping(zoho="currency_symbol", local="currency_symbol"),
        FieldMapping(zoho="currency_format", local="currency_format"),
        FieldMapping(zoho="price_precision", local="price_precision"),
        FieldMapping(zoho="is_base_currency",local="is_base_currency", transform="bool"),
        FieldMapping(zoho="exchange_rate",   local="exchange_rate",   transform="decimal"),
        FieldMapping(zoho="effective_date",  local="effective_date",  transform="zoho_date"),
    ],
)
SPEC = ZohoModuleDefinition(
    config=CURRENCIES_CONFIG, model=Currency, state_model=CurrencySync,
    pre_upsert=stamp_source, post_upsert=project_currency,
)
```

* `pre_upsert`: resolve the target organization; strip `None`s; refuse to overwrite a
  higher-precedence source's fields.
* `post_upsert`: set `currency_sync.currency_id`, and from the payload's `exchange_rates`
  array upsert `currency.exchange_rates` rows (`rate_source='zoho'`).
* **Ownership**: `ZOHO_OWNED_CURRENCY_FIELDS` = the eight mapped columns;
  `currencies.service.update_currency` refuses a PATCH touching them on a
  `zoho_id`-linked row (same rule as `geo.ZOHO_OWNED_PLACE_FIELDS`).

### 3.6 Multi-source (SAP and beyond)

Adding a source is additive and mechanical:

1. `SAPIdentityMixin` → `currencies` (`sap_id`), migration.
2. `SAPMirrorMixin` → `currency_sync` (`sap_*` column group), migration.
3. A `currencies/sap/` adapter registering `SyncContract(identity="sap_id",
   source_system="sap", raw="sap_raw", …)`.
4. Precedence config decides which source's fields win.

No engine fork, no second canonical table.

### 3.7 Precedence and conflict policy

```
CURRENCY_SOURCE_PRECEDENCE = ("sap", "zoho", "manual")
```

`currency_sync` is the per-source truth; the canonical row reflects the winner.
A lower-precedence sync may write its own sync row but must not overwrite canonical fields
owned by a higher source; it logs `currency.source_outranked`. Ties resolve by
`<source>_last_modified`, then `sync_version`.

### 3.8 Exchange rates

* `currency.exchange_rates` gains `external_source` + `external_id` (source identity) and
  keeps `rate_source`/`rate_type`.
* Uniqueness changes from `(tenant, currency, effective_date)` to
  `(tenant, currency, effective_date, rate_source)` so two sources can quote the same day.
* Zoho's `/settings/currencies/{id}/exchangerates` is synced as a child collection; each
  row upserts with `rate_source='zoho'`. Precedence decides which feeds the
  `Currency.exchange_rate` cache.

---

## 4. Full Zoho sync engine implementation plan

This is the engine work that makes §3 possible. It is **backward compatible**: every step
defaults to current behaviour, and no existing module opts in until the currency adapter does.

### 4.1 Config — `app/modules/zoho/sync/config.py`
* Add `SyncContract` (above); add `contract: SyncContract = SyncContract()` to
  `ModuleSyncConfig`.
* Keep `zoho_id_attr` (the payload attribute) unchanged.

### 4.2 Mixins — `app/modules/zoho/sync/mixins.py`
* Split `ZohoIdentityMixin` → keep `zoho_id`; move `public_id` to `LocalPublicIdMixin`.
* Remove `custom_fields` from `ZohoMirrorMixin`; add `ZohoCustomFieldsMixin`
  (`custom_fields` **JSONB**) and `ZohoCommentsMixin` (`comments` **JSONB**).
* Add `SAPIdentityMixin`/`SAPMirrorMixin` as a documented, unimplemented template (or
  land with the SAP adapter).

### 4.3 Engine — `app/modules/zoho/sync/engine.py`
* Read all identity/mirror attribute names from `cfg.contract` instead of literals
  (`_get_by_zoho_id` → `_get_by_identity`; `_materialise` sets `contract.*` names).
* Add the two-model path: when `defn.state_model` is set, resolve the latest state row by
  `(contract.identity, synced_at DESC)`, run the gate on it, write mapped values to
  `defn.model`, append a `state_model` row, and link them.
* Capture `custom_fields` / `comments` into their columns when configured and the model
  has them; a missing column or disabled flag is a no-op.
* Keep the in-place path byte-for-byte equivalent for modules without `state_model`.

### 4.4 Registry — `app/modules/zoho/sync/registry.py`
* Replace the hardcoded `_GATE_COLUMNS` check with validation of the **declared** contract
  columns against the relevant model (`state_model` if set, else `model`).
* Identity uniqueness: accept the canonical `(tenant_id, <identity>)` unique index, or — in
  history mode — an index on `(<identity>, synced_at DESC)` (no unique required).
* Validate `custom_fields` / `comments` columns exist when enabled.
* Validate `state_model` carries the mirror columns and an FK to the data model.

### 4.5 Mapper — `app/modules/zoho/sync/mapper.py`
* `flatten_custom_fields` → JSONB-friendly (keep nested values; stop forcing HSTORE text).
* Add a `json` transform; extract `comments` (array/object) for `ZohoCommentsMixin`.
* Existing transforms and the "missing key is skipped" rule are unchanged.

### 4.6 Apply gate — `app/modules/zoho/sync/apply.py`
* Pure logic unchanged. `RowState` is built from the state row's declared columns. In
  history mode the "stored" row is the latest state row; `remote_deleted_at` still fences
  resurrection.

### 4.7 Existing mirror tables — JSONB rollout
* A dedicated additive migration per affected table (`organizations`, `taxes`, `locations`,
  `zoho_users`, …): `custom_fields` HSTORE → JSONB (`USING hstore_to_jsonb(...)`) and add
  `comments` JSONB where the Zoho payload has it.
* Opt-in per module via `SyncContract.custom_fields` / `.comments`; a table without the
  columns is untouched.

### 4.8 Backward compatibility & guardrails
* `SyncContract` defaults = today's names; `state_model=None` = in-place behaviour.
* Registry validation is the safety net: a mis-declared contract fails at startup, not at
  03:00 in a worker (existing doctrine).
* Add engine unit tests that assert a default module produces an identical write to before.

---

## 5. Currency module changes

| File | Change |
|---|---|
| `app/modules/currencies/model.py` | `Currency` composes `ZohoIdentityMixin`; new `CurrencySync` (partitioned) with `ZohoMirrorMixin` + `ZohoCustomFieldsMixin` + `ZohoCommentsMixin`; drop `zoho_id` duplicate/`currency_id` echo; `ExchangeRate` gains source identity |
| `app/modules/currencies/enums.py` | `CurrencySource` (`zoho`, `sap`, `manual`) |
| `app/modules/currencies/service.py` | source precedence; owned-field guard; ref/sync helpers |
| `app/modules/currencies/zoho/` | **new** `spec.py`, `fields.py`, `hooks.py`, `__init__.py` registering the spec |
| `app/modules/zoho_currencies/` | **delete** (the half-step move) |
| `app/router.py`, `alembic/env.py`, `tests/conftest.py`, `tests/zoho_core/test_masters.py` | repoint/remove |
| `.importlinter` | remove the `zoho_currencies` entries added earlier; `currencies` stays a Zoho master |
| `docs/zoho-sync-implementation/adapters/currencies.md` | rewrite for the canonical target |

## 6. Migration & backfill

Three revisions, so expansion, data and contraction are separable.

**M1 — expand (additive, reversible).** Create `currency.currency_sync` (partitioned) and
its first partitions; add `zoho_id` (and later `sap_id`) to `currencies`; add source
identity to `exchange_rates`; adjust the rate unique index to include `rate_source`.

**M2 — backfill (data, idempotent).** For every live `zoho_currencies` row:

| `zoho_currencies` | → |
|---|---|
| `currency_code` | match `currencies` by `(tenant, code)`, else insert |
| `currency_name`, `currency_symbol`, `currency_format`, `price_precision`, `is_base_currency`, `exchange_rate`, `effective_date` | canonical columns (fill only when absent) |
| `zoho_id` | `currencies.zoho_id` |
| `zoho_raw`, `zoho_raw_hash`, `zoho_raw_synced_at`, `zoho_last_modified_time`, `synced_at`, `sync_source`, `sync_version`, `remote_deleted_at`, `custom_fields` | one `currency.currency_sync` history row (`source_system='zoho'`) |
| `organization_id` (may be NULL) | resolved to a real org (connection/default); NULL rows quarantined and reported |
| `exchange_rate` + `effective_date` | also upsert an `exchange_rates` row (`rate_source='zoho'`) |

A Python data migration (Alembic `op.get_bind()` or a management script) writes a
reconciliation report: inserted vs matched, quarantined (no org), field conflicts.

**M3 — contract (destructive, gated).** Drop `zoho_currencies`; downgrade recreates it and
copies Zoho-sourced rows back from `currencies` + `currency_sync` (best-effort).

## 7. Phases

0. **Un-split.** Delete `app/modules/zoho_currencies/`; revert `router`, `alembic/env`,
   `registry`, `.importlinter`, tests. Green build.
1. **Engine contract.** `SyncContract` + config; engine/registry read declared names;
   split `ZohoIdentityMixin`; add `ZohoCustomFieldsMixin`/`ZohoCommentsMixin`. Full suite
   green with defaults; engine unit tests for a neutral contract.
2. **Mixins + JSONB rollout.** HSTORE→JSONB migration for existing mirrors; mapper
   `custom_fields`/`comments`. Opt-in per module; suite green.
3. **Currency schema (M1).** `Currency` + `CurrencySync` + rate source columns; currency
   tests pass.
4. **Currency adapter.** `currencies/zoho/` spec + hooks; ownership guard; rate sync.
   Adapter tests against saved payloads (no network).
5. **Backfill (M2).** Run on a copy; assert counts and field parity vs `zoho_currencies`.
6. **Cutover (M3).** Drop `zoho_currencies`; delete the old mirror; repoint `currency_id`
   consumers.
7. **SAP-ready.** `SAPIdentityMixin`/`SAPMirrorMixin` + adapter skeleton; refs/precedence
   already support it.

## 8. Testing

* **Engine** — default module write is unchanged; neutral contract (`zoho_id` on data,
  `zoho_*` on state) writes correctly; history append + latest-state gate; custom
  fields/comments capture on/off.
* **Apply gate** — unchanged pure tests.
* **Adapter** — payload fixture → one `Currency` + one `currency_sync` row + N
  `exchange_rates`; base-currency clearing; idempotent re-run appends nothing (hash).
* **Ownership** — PATCH of a Zoho-owned field on a `zoho_id`-linked row is refused (422).
* **Precedence** — a SAP sync cannot overwrite a Zoho-owned canonical field.
* **Migration** — seeded `zoho_currencies` row maps to the exact canonical row, sync row
  and rate; NULL-org row is quarantined.
* **Tenancy** — a synced currency never lands in another tenant's org (composite FK).
* `lint-imports`, `ruff`, full suite.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Engine change breaks other masters | defaults identical; full suite at Phase 1 before any module opts in |
| Time-partition + unique-per-id tension | append-only history; latest row is state (design A); or hash-partition (B) |
| Gate lookup across partitions slows | optional `currency_sync_state` fast path; currency volume is small |
| HSTORE→JSONB migration on live mirrors | additive, reversible, per-table, `USING hstore_to_jsonb` |
| Org resolution for tenant-wide Zoho settings | explicit connection→org mapping; quarantine ambiguous; fail loud |
| Backfill overwrites an operator edit | fill-only; report conflicts; never clobber non-null canonical values |
| `zoho_currencies` referenced elsewhere | grep before M3; repoint `currency_id` consumers |

## 10. Open decisions

1. **Sync store shape:** A (append-only, time-partitioned history — recommended) or B
   (hash-partitioned one-live-row state)?
2. **Fast path:** add `currency_sync_state`, or rely on the latest history row?
3. **Organization for synced currencies:** connection's organization, tenant default org,
   or relax `currencies` to tenant-scoped?
4. **Split `ZohoIdentityMixin`** to drop `public_id` on inbound-only tables, or keep the
   redundant `public_id`?
5. **Precedence order:** `sap > zoho > manual` as the default?
6. **JSONB rollout scope:** migrate every Zoho mirror's `custom_fields` now, or opt-in per
   module as each is touched?