# Sync crosswalk — delta v3: scope, identity and reference resolution

**Status:** implemented (this document records what changed and what is next)
**Supersedes nothing.** It is the delta on top of
[`sync-crosswalk-redesign.md`](sync-crosswalk-redesign.md), which stays the
reference for *why* the crosswalk exists.
**Closes:** redesign open decisions **#1** (organization for Zoho settings
records) and **#2** (`match_on` for currencies); delivers **Phase 6**
(resolver). **Does not** deliver Phase 5 (backfill — moot, see §1) or Phase 7
(planner DAG — see §6.2).

---

## 1. What this delta is really about

The redesign answered *"where does sync bookkeeping live?"*. Running it against
a real deployment surfaced a different question it had left open, and open
decision #1 was the visible edge of it:

> **Which tenant and which organization does a write belong to — and who
> decides?**

Four subsystems had four different answers, and they disagreed in production:

| Who | How it decided | Result on the dev stack |
|---|---|---|
| `scripts/seed.py` | `COMPANY_TENANT_CODE` / `COMPANY_ORGANIZATION_CODE` (`backend/.env`) | tenant `THPL`, org `THPL` |
| the containers | `DEFAULT_TENANT_CODE` — **absent from `deployment/.env`**, so the code default | tenant `default` |
| the Zoho engine | the org node whose `zoho_id` is `ZOHO_ORGANIZATION_ID`, else **NULL** | org `ZOHO-60015628348` under tenant `default` |
| `geo`, `currencies`, `core`, `users` | four private copies of "the tenant's only organization, else 422" | four slightly different errors |

One database, two tenants, two organizations for one company, and org-scoped
masters failing one record at a time with *"cannot place a synced currency: no
organization in context"*. That error was not a currency bug. It was this.

**Phase 5 (backfill/cutover) is moot as a result.** The schema is greenfield
(redesign decision #5) and the dev database was rebuilt from migration zero, so
there is nothing to backfill `zoho_currencies` from. M3/M4/M5 are dropped.

---

## 2. One resolver — `app/database/scope.py`

The four private `require_organization` copies are gone. One resolution order,
used by every entry point, in one file below every feature module:

```
1. X-Organization-Code: THPL      ← explicit, human-readable, the new one
2. X-Organization-Id: <uuid>      ← explicit, kept for existing callers
3. the bound request              ← a signed-in user's own organization
4. the tenant's only organization ← a deployment that never branched
5. DEFAULT_ORGANIZATION_CODE in DEFAULT_TENANT_CODE
6. → 422 organization_required
```

Three properties are load-bearing:

* **Narrowest first.** Steps 3–5 are ordered so a *bound* request can never
  fall through to the deployment default. Falling through would silently move
  one tenant's write into another's organization — the failure mode that is
  invisible until an audit.
* **An explicit code is confined to the caller's tenant** (`for_tenant`).
  Without that, any authenticated user could name another tenant's `org_code`
  and write into it. Registration is the deliberate exception: it is
  unauthenticated, so there the code is what *chooses* the tenant.
* **The refusal is the feature.** `organization_id` is NOT NULL on every
  operational table. The alternative to a 422 naming both headers and the
  setting is an `IntegrityError` from inside a flush, which tells a caller
  nothing.

The module-specific errors survive as thin wrappers — `geo_rule_violation`,
`currency_rule_violation`, `core_rule_violation` — so API clients keep their
existing codes. Only the *logic* was shared.

### 2.1 The Zoho engine uses it too

`zoho/control/tenancy.py::zoho_tenant` now resolves, in order: the org node
carrying `ZOHO_ORGANIZATION_ID` → `configured_default()` → the tenant's only
organization. Previously an unresolved node left `organization_id` NULL and
every org-scoped master failed per record.

**This closes open decision #1.** The answer is *the connection's
organization, and the deployment default when the connection has not named one
yet* — because a deployment has one company and its Zoho data belongs to that
company. Not "relax `currencies` to tenant-scoped".

---

## 3. Identity: `zoho_id`, and adoption instead of duplication

The question was *"each module's configurable zoho_id should be what we take
from the response — or is the crosswalk enough?"* **Both, with a division that
is now explicit:**

| | Declared by | Holds | Matched on |
|---|---|---|---|
| **Identity of record** | `ModuleSyncConfig.zoho_id_attr` (`currency_id`, `tax_id`, `tax_group_id`, `tax_exemption_id`, `organization_id`) | `sync.sync_records.external_id` | **always** — the unique `(tenant, source, module, external_id)` |
| **Echo** | `SyncContract.identity_echo` (e.g. `("zoho_id",)`) | a column on the entity row | only where a module declares it in `match_on` |

So `zoho_id_attr` already *is* the per-module configurable answer to "which
field becomes `zoho_id`" — it has been since Phase 4b. The echo is optional
convenience: a column you can read without a join. Adding a source costs zero
entity-table migrations either way, which is the property the redesign was
protecting (§2.3).

**`tax.*` runs with no echo at all** and is the proof the crosswalk is
sufficient. `organizations` keeps one because `org_code` is derived from it.

### 3.1 Adoption — closing decision #2

`organizations` moved from `match_on=()` to `match_on=("zoho_id",)`, and
`scripts/seed.py` stamps `ZOHO_ORGANIZATION_ID` onto the company organization
(`tenants/seed.py::_claim_zoho_identity`, set-once, never overwritten).

The first sync then finds that row and **updates** it instead of creating a
parallel `ZOHO-<id>` node. The seeder also adopts the migration's `DEFAULT-HQ`
placeholder rather than adding a second organization beside it.

Verified on the live stack: after a full sync, `org_management.organizations`
holds exactly one row — `THPL`, `zoho_id=60015628348`, Zoho's legal name.

> **Decision #2 (`match_on` for currencies) follows:** currencies keep
> `match_on=("currency_code",)` **tenant-wide**, not `(organization_id,
> currency_code)`. Zoho's `/settings/*` endpoints are tenant-wide; scoping the
> match key per organization would create one INR per branch the day a second
> organization exists.

---

## 4. Reference resolution (Phase 6) — built

`ReferenceRule` was declared in `contract.py` and consumed by nothing; the only
real resolution was a hand-written `link_currency` hook on organizations.

**Now:** policy and mechanism are split at the file boundary.

* `app/modules/sync/references.py` — **pure**. `pairs_in_page` computes the
  whole page's reference surface; `plan_references` decides FETCH / STUB /
  DEFER / NULL against an already-resolved map and a `Budget`. No I/O, no
  engine, no session — so the policy is tested as a decision table.
* `engine.py` — **mechanism**. `_preload_references` resolves the page in
  **one** `crosswalk.resolve_many` query; `_fetch_reference` goes through the
  normal transport (governor, breaker and quota all still apply);
  `_stub_reference` inserts a provisional row and links it immediately;
  DEFER waiters are queued *after* the flush, when the waiting row has an id.
* `app/modules/sync/reconcile.py` — the drain lane, exposed as
  **`python -m app.modules.zoho.cli reconcile`**.

`max_reference_fetches_per_run` (default 50) is the ceiling. Over budget,
FETCH degrades to STUB: *"fetch it and insert it first"* is correct per record
and ruinous per page.

`link_currency` is deleted; organizations declares the rule instead. Verified
end to end on the live stack: organizations synced before currencies → one
`pending_references` row → currencies synced → `reconcile` → `linked=1`, and
`organizations.currency_id` points at INR.

---

## 5. What is now verified on the real deployment

A full live sync against Zoho, from a database rebuilt from migration zero:

| module | shape | result |
|---|---|---|
| `organizations` | list + detail, `index_then_detail` | 1 — **adopted** the seeded THPL row |
| `currencies` | one unpaginated list | 12 |
| `taxes` | list + **10 detail calls by `tax_id`** | 10, normalized into `tax.tax_components` |
| `tax_exemptions` | one unpaginated list | 17 |
| `locations`, `users` | still in-place mirrors | 2, 20 |

Every row landed in `tenant_id=1, organization_id=1` (THPL). `sync.sync_records`
carries the identity; `tax.tax_components` carries typed columns
(`tax_name`, `tax_percentage`, `tax_type`, `tax_specific_type`, …) — not JSON.

This is the list → transform → fetch-detail-by-id → upsert flow, working.

---

## 6. Next steps, in order

### 6.1 Convert `locations` and `zoho_users` to the crosswalk *(Phase 8)*
The last two in-place mirrors, and the last two `zoho_*` business tables.
Each is one PR: add `contract=SyncContract(crosswalk=True, entity_table=…)`,
move business columns to a canonical table, drop the mirror.
**Done when:** a post-cutover sync reports all-`unchanged`, and
`zoho_locations` / `zoho_users` are dropped.

### 6.2 Planner ordering *(Phase 7)*
`organizations` **must** sync before the org-scoped masters — it creates the
node they attach to — and `run_all` in `tests/zoho_core/test_masters_e2e.py`
sorts it first *as a test-local workaround*. The planner has no such notion, so
in production the ordering is luck. Registry order is import order, which is
how a test-module import order silently broke an unrelated e2e test.
**Do:** `depends_on` on `ModuleView`, topological rank in the registry (cycle ⇒
boot failure), `plan()` suppressing a dependent until its dependency has a
`last_full_sync_time`.
**Done when:** a planner table test covers "dependent waits for its
dependency's first full sync", and `run_all` can drop its sort.

### 6.3 Schedule the reconcile lane
`drain_pending_references` is CLI-only. It needs a Celery beat entry so
deferred references link without an operator.
**Done when:** a beat task drains per tenant on an interval, and
`pending_references` depth is a metric.

### 6.4 Give `tax_groups` a list source
Registered `direction=disabled` — Zoho documents create/get/update/delete for
`/settings/taxgroups` but **no list**, so the engine's scan has nothing to
walk. Groups arrive today only as `tax_type='tax_group'` rows from
`/settings/taxes`, without their members.
**Do:** resolve group members through `ReferenceRule` on the taxes payload, or
fetch each group by id when a tax names one. This is the first real consumer of
`OnMissing.FETCH`.

### 6.5 Close the `.env` / compose drift properly
`deployment/.env` now sets `DEFAULT_TENANT_CODE` / `DEFAULT_ORGANIZATION_CODE`
and `docker-compose.yml` passes both. But nothing *enforces* that the stack and
the local tooling agree — the same drift can recur with any new setting.
**Do:** a startup check that logs (or refuses, in production) when
`DEFAULT_ORGANIZATION_CODE` names an organization that does not exist, and a
`manage.sh` target that diffs the two env files for shared keys.

### 6.6 Unblock `default_taxes` / `gst_treatments`
Tables exist, no adapter — the endpoints are undocumented in
`docs/zoho-docs-md/`. Per the guardrails, an endpoint shape is not something to
invent.
**Do:** capture one real response from each, vendor it, then write the adapter.

### 6.7 Batched entity preload on first sync
Known and accepted (redesign §3.4a): a record that passes the gate loads its
entity individually, so a first-ever sync pays one query per row. Harmless at
master scale, real at invoice scale.
**Do:** preload entities keyed on the page's writer `entity_id`s — but only
once a profile shows it, not before.

---

## 7. Gotchas worth writing down

1. **Two `.env` files, and only one of them reaches the containers.**
   `backend/.env` drives local tooling (`alembic`, `pytest`, `scripts/`);
   `deployment/.env` drives the stack. A setting added to one and not the other
   is the bug in §1. `docker-compose.yml` passes variables *explicitly* — a
   value present in `deployment/.env` but absent from the compose `environment:`
   block never reaches the process either.
2. **The dev helpers used to target the scratch test database.**
   `.dev_migrate.sh`, `.dev_reset_db.sh` and `.dev_sync_run.sh` hard-coded
   `:55432`, so every "apply the migrations" quietly operated on the throwaway
   database while the real one fell 13 migrations behind. They now take a
   target and **default to the app stack**; `.dev_target.sh` holds the mapping,
   and `.dev_zoho.sh` runs the real CLI.
3. **`pytest` is the one thing that must stay on scratch** — `tests/conftest.py`
   hard-codes `:55432`, and running the suite against a seeded database breaks
   ~56 unrelated tests.
4. **A `TRUNCATE` of `org_management.organizations` leaves a state no migration
   produces.** `conftest` restores the default tenant's organization afterwards,
   and clears `tenancy`'s process-level default-org cache — a stale cached id
   stamps new rows with an organization that no longer exists.
5. **`zoho_oauth_credentials` holds the only copy of the refresh token** when
   `ZOHO_REFRESH_TOKEN` is empty. Dropping the schema loses the Zoho connection;
   it is recoverable from `deployment/backups/` **only** while
   `ZOHO_TOKEN_ENCRYPTION_KEY` is unchanged. Back that table up before any
   reset, or reconnect via `/api/zoho/auth/initiate`.
6. **A refresh token belongs to the Zoho *user*, not the org.** A
   `credential_org_mismatch` warning is informational: the stored credential
   still works, and the next rotation restores it under the configured org.
7. **`wsl --terminate` breaks Docker Desktop's bind mounts.** Containers whose
   source is a WSL path silently fall back to an empty `tmpfs`, and recreating
   them fails with `distro-services/ubuntu.sock: no such file`. Restart Docker
   Desktop after terminating the distro.
