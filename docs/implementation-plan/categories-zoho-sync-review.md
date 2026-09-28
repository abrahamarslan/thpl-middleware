# Categories ↔ Zoho — review of the first cut, and what changed

**Status:** implemented and verified live (2026-09-25).
**Scope:** `app/modules/categories/` and its Zoho adapter, reviewed against
[`categories-taxonomies-implementation-plan.md`](categories-taxonomies-implementation-plan.md)
(the plan) and [`sync-crosswalk-delta-v3.md`](sync-crosswalk-delta-v3.md) (the
shape `currencies` and `taxes` already follow), then exercised against the real
Zoho Books API.
**Vendored API doc:** [`docs/zoho-docs-md/categories.md`](../zoho-docs-md/categories.md)
— which closes plan open question **§14 Q1** (the doc was missing when the plan
was written).

---

## 1. Verdict

The **tree/taxonomy half is solid** and needed only small fixes. The **Zoho half
had the right skeleton and the wrong storage shape**: it declared
`crosswalk=True` while the model still carried the pre-crosswalk mirror columns,
it imported a row Zoho invents, and it broke five tests that were already
passing.

| | Count |
|---|---|
| Things that were right and are unchanged | 8 (§2) |
| Defects fixed | 17 (§3) — 5 high, 6 medium, 6 low. **F17 is not a categories bug** — it was found on the way and it stopped every scheduled Zoho sync |
| Deliberate non-changes, with a recommendation | 9 (§6) |
| Tests | 14 new + 5 repaired, across 5 files; each fix has one that fails without it (§7) |

The one product-shaped gap this review found — **§6 O1, Zoho's
`category_tax_preferences`** (which GST rate a category carries) — is now **closed**:
categories carry their taxes through a new polymorphic `tax.tax_assignments` table
that any entity can use. See [`tax-assignments.md`](tax-assignments.md).

---

## 2. What was right (unchanged)

| # | What | Evidence |
|---|---|---|
| R1 | **Scoping.** All four tables are `OrgEntityMixin`; the composite FKs collapse the reference design's owner machinery (`fk_categories_taxonomy_scope`, `fk_categories_parent_scope`, `fk_categorizables_category`). | DB-level tests reject cross-scope writes; tenancy isolation test. |
| R2 | **Caught a plan error.** PostgreSQL cannot reference a *partial* unique index, so the planned `categorizables → taxonomy_entity_types` whitelist FK is impossible. The migration and model record the deviation and enforce the whitelist in `check_categorizable_integrity()`. | `test_taxonomy_entity_types_uniqueness_cannot_be_a_fk_target`. |
| R3 | **`tree.py` is pure**, iterative (no recursion limit), recomputed whole under a per-taxonomy advisory lock. | Bounds correct live: `Skin Care` 3–6 encloses `Bathing Soap & Bodywash` 4–5. |
| R4 | **The `zoho` taxonomy trigger** (`fill_category_default_taxonomy`) is the only place that can run before the NOT NULL / composite-FK checks; it is race-safe (`ON CONFLICT DO NOTHING`) and sorts ahead of the scope guard. | Live sync created `taxonomies(slug='zoho')` with no code path of ours involved. |
| R5 | **Slim/Fat DTOs** with `load_only` / `selectinload`, constant-query-count test, tenancy test, the D13 `IntegrityError` → envelope handler. | `test_detail_read_query_count_is_constant`. |
| R6 | **The engine settings that matter were right:** `INCREMENTAL` (the filter really works), `sort_column=None`, `index_then_detail`, `paginated=True`, `url→slug`, `sibling_order→position`, `visibility→is_visible`. | Live: 1 list call, 1 boundary row, 0 writes on a steady-state run. |
| R7 | **Parent resolved in a hook, not a `ReferenceRule`.** Correct — see §4.2. | Live: child linked to parent on a first sync. |
| R8 | **Registration checklist** (router, `alembic/env.py`, `_TEST_TABLES`, adapter package, search registry, docs) was complete. | — |

---

## 3. What was wrong, and what changed

Severity: **H** = wrong data or broken tests, **M** = wrong behaviour on a real
path, **L** = hygiene.

| # | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| F1 | **H** | **Registering the module broke 5 passing tests** — 4 in `tests/zoho_core/test_masters_e2e.py` (the fake Zoho wire has no `/categories`) and `test_planner_tick` (assumes no module gets the weekly-full lane; `categories` is the first `INCREMENTAL` one). | `5 failed, 376 passed` on the Zoho suites before any change. | Wire now serves `/categories` modelled on the **live** response; expectations updated; new real-transport test (F16). |
| F2 | **H** | **Zoho's synthetic `ROOT` row was imported as a category.** `GET /categories` prepends `category_id "-1"`, `name "ROOT"`, blank `created_time`/`last_modified_time`. It became a fake top-level node, and because its modified time is blank an incremental run would re-list it forever. | Baseline live sync: `created=19`, row 1 = `ROOT`. With `include_root_category=false`: 18 rows. | `list_params={"include_root_category": "false"}`. |
| F3 | **H** | **The model was not crosswalk-shaped.** `crosswalk=True` but `Category` composed `ZohoIdentityMixin + ZohoMirrorMixin + ZohoPushableMixin`: 14 columns the crosswalk path never writes. `CategoryOut` exposed two of them (`synced_at`, `zoho_last_modified_time`) — always null. | Live: `sync_version = 0`, `synced_at IS NULL`, `zoho_raw IS NULL` on all 19 rows, while `sync.sync_records` held the real data. | Migration `c063729f29c2` drops them; the row keeps one `zoho_id` echo (as `currencies` / `organizations` do). |
| F4 | **M** | **`direction=BIDIRECTIONAL` contradicted the service guard.** The guard refuses local edits to Zoho-fed fields ("change it in Zoho"), which only makes sense for an INBOUND module — and nothing pushes (outbox not built). | Spec + service read together. | `INBOUND`. `to_zoho_payload` stays as the outbox seam. |
| F5 | **M** | **`meta_keywords`** — Zoho's `seo_keyword` is one comma-separated string; the column is JSONB and the DTO declared `dict`. A synced category with SEO keywords would fail serialisation (500 on `GET /api/categories/{ref}`). | Found by reading; **not** seen live (every category in this org has blank SEO). Pinned by a test. | `csv_list` codec → JSON array; model/DTO typed `list[str]`; migration converts stored strings. |
| F6 | **M** | **Tombstoned parent broke the tree.** `recompute_bounds` set `is_root = true` for a node whose parent was soft-deleted, while `parent_id` stayed set — violating `ck_categories_root_no_parent` and failing the whole flush. Reachable when Zoho deletes a parent. | Reproduced by test; mutation (old line restored) fails it. | `is_root = parent_id is None`; the node is still laid out as a root, but not flagged one. |
| F7 | **M** | **An unresolvable parent was silently lost.** Left as a root with a log line; an unchanged row never reaches the hook again (the apply gate skips it), so nothing ever re-linked it. | By reading + test. | Queued on `sync.pending_references`; `reconcile` links it. `trg_categories_is_root` keeps `is_root` derived so the reconcile lane's bare `UPDATE … SET parent_id` cannot trip the CHECK and abort the whole drain. |
| F8 | **M** | **Deletes never propagated.** An incremental list never shows a delete, and `soft_delete_missing` was off. | Engine `_run_list_pipeline`: only `FULL` reconciles. | `soft_delete_missing=True` — the weekly-full lane (on by default) tombstones both sides. **Still gated by `ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING`, false everywhere** (§6 O5). |
| F9 | **M** | **Hierarchy ownership was undefined.** The plan said parent "remains ours", but the hook re-links `parent_id` from Zoho on every re-apply, so a local `move` would be silently undone. | Plan §6.3 vs hook. | `parent_id` joins the Zoho-owned set; `move` and `PATCH parent_id` on a linked row are refused. |
| F10 | L | A slug rename did not recompute `path` (built from slugs) for the subtree. | `tree_affected` looked at `parent_id`/`position` only. | `slug` added. |
| F11 | L | The service hand-listed the Zoho-owned fields, duplicating the adapter (plan says "derived, never hand-listed"). | `service.py` constant + an equality test. | Lazy-imported from the adapter (the `currencies` pattern); duplicate deleted. |
| F12 | L | `count_live_children` loaded every child id to take `len()`. | `crud.py`. | `SELECT count(*)`. |
| F13 | L | SEO fields (`meta_*`) were not in `CategoryCreate` / `CategoryUpdate`; plan L1 makes them first-class. | `schema.py`. | Added. |
| F14 | L | `.importlinter` did not cover `categories` (platform-never-imports-a-master, features-never-call-Zoho, sync-core-source-neutral, independence). | `.importlinter`. | Added to all six contracts; `lint-imports` green. |
| F15 | L | 11 model column comments the migration never set (22 `alembic check` ops), plus a stale `zoho_id` comment. Noise for every future autogenerate. | `alembic check`. | Set in the alignment migration. **Correction:** `alembic check` still reports *index-name* drift on these tables (the hand-written migration names `ix_categories_uuid`, the model's default is `ix_core_categories_uuid`) — an earlier version of this row said "nothing", from a filter that only matched comment operations. It is house-wide (the `extfields` tables have it too), cosmetic and left alone. |
| F16 | L | **No test through the real transport.** The repo's own lesson (E29: `FakeZohoClient` hid a missing-`page_context` bug) is that new adapters go through `ZohoWire`. | `test_masters_e2e.py` had no categories. | `test_categories_end_to_end_through_the_real_transport`. |
| **F17** | **H** | **The Celery worker could not map its models, so `planner_tick` failed on every tick and NO scheduled Zoho sync of any module ran.** A worker imports only what its task modules reach; `app.tasks.documents` loads `documents.model`, whose tenant/organization FKs name tables no worker import loads, so the first ORM query raised `NoReferencedTableError: … mappers failed to initialize`. Tests never saw it (`conftest` imports the whole app). **Pre-existing and independent of categories** — categories is not on the worker's boot path, and a pristine `git archive HEAD` export fails the same way. | `celery-worker` log: `planner_tick raised unexpected` on **all 76 ticks** from the container's creation (12:55, where the log starts — the previous container's history is gone) until the fix; reproduced at boot with `import_default_modules()` + `configure_mappers()` at HEAD and in the working tree. How long it was broken before 12:55 is unknown. | `worker_init` hook in `app/tasks/celery_app.py` imports `app.router` (every router imports its module's models — nothing to keep in sync). `tests/test_worker_boot.py` runs a clean interpreter and fails with the original error when the hook is disabled. |

---

## 4. Design notes worth keeping

### 4.1 Why the model lost its mirror columns
`ModuleSyncConfig`/`SyncContract` say it plainly: `crosswalk=False` = "the
in-place mirror (`ZohoIdentityMixin` + `ZohoMirrorMixin` on the entity table)",
`crosswalk=True` = "crosswalk + history". The registry's `validate()` even
*refuses* to ask a crosswalk entity for gate columns. So a crosswalk entity with
mirror columns is not "extra fidelity" — it is fourteen columns that lie about
freshness (`synced_at` NULL on a row that synced a minute ago). What is kept is
the **echo**, per delta §3: `zoho_id` (+ its partial unique index), because
"is this row Zoho-linked?" is asked on every local edit. `match_on=("zoho_id",)`
stays: it is not the identity (the crosswalk is) but lets a wiped crosswalk
re-adopt rows instead of duplicating them.

### 4.2 Why the parent is a hook and not a `ReferenceRule`
The v3 reference machinery (`ReferenceRule`, delta §4) resolves a page's
references **in one query before any row of the page is written**. A category's
parent is a row of its *own* module and, in Zoho's hierarchical list, is almost
always in the *same page* — so a rule would `DEFER` every child on a first sync
and make an operator run `reconcile` to build a tree the same response already
contained. Hooks run after the page is flushed and its crosswalk rows are linked,
when the parent resolves. `STUB` is not an option either (`status='provisional'`
violates the CHECK and `name` is NOT NULL). What a hook *cannot* resolve now goes
on the same `pending_references` queue a rule would have used — so the platform's
"what did we fail to link?" answer stays true.

### 4.3 Why `is_root` is now trigger-derived
`is_root` must equal `parent_id IS NULL`. Two writers change `parent_id` without
the ORM: the reconcile lane (`UPDATE … SET parent_id`) and any future raw
migration. With `is_root` set by the application only, either one leaves
`is_root = true` next to a parent and `ck_categories_root_no_parent` aborts the
statement — inside the reconcile lane that aborts the drain for **every** module
of the tenant. A `BEFORE INSERT OR UPDATE OF parent_id` trigger makes the flag a
function of the column. (A `GENERATED` column would be tidier but leaves the ORM
attribute expired after an update, which under `AsyncSession` is a
`MissingGreenlet` waiting to happen.)

### 4.4 The modified-since filter
The vendored doc says `yyyy-MM-ddTHH:mm:ssZ`. Live, `…Z` is rejected
(`400 Invalid value passed for last_modified_time`) and `2026-09-20T00:00:00+0000`
works — which is exactly the engine's `_CURSOR_FMT`. No change needed; the wire
in the e2e test now enforces it so it cannot regress.

---

## 5. Live verification (real Zoho Books, dev stack, 2026-09-25)

Zoho org `60015628348`, tenant `THPL`. **48 of the 45,000 daily API calls** were
used across every probe and run (the governor's own count).

| Step | Result |
|---|---|
| Probe `GET /categories` | 19 rows: `ROOT` + 18 real; 1 child (`Bathing Soap & Bodywash` under `Skin Care`); `page_context` present. |
| Probe `include_root_category=false` | 18 rows, no `ROOT`. |
| Probe modified-since, `…+0000` / `…Z` | filters correctly / `400`. |
| **Baseline sync, old adapter** | `created=19` incl. `ROOT`; `sync_version 0`, `synced_at NULL`, `zoho_raw NULL` on every row; crosswalk full. |
| Migration on the populated table | 19 rows intact, 14 columns dropped, trigger installed. |
| Incremental sync, fixed adapter | `listed=1 created=0 updated=0 unchanged=1` — **one API call**, no `ROOT`. |
| Full sync of the already-synced tree | `unchanged=18`, 0 writes. |
| **Purge + full sync from empty** | `created=18`; no `ROOT`; `Bathing Soap & Bodywash` → parent `Skin Care`, depth 1, path `/skin_care/bathing_soap_bodywash/`, bounds nested; 18 crosswalk rows each holding the **detail** document incl. `category_tax_preferences`; `pending_references = 0`. |
| All 18 rows through `CategorySlimOut` + `CategoryOut` | valid; tree view returns depth-first order. |
| **Worker fix (F17), then the planner unattended** | Every module ran on its scheduled lane within ~3 minutes (`currencies`, `taxes`, `tax_exemptions`, `locations`, `users`, `organizations` — 0 errors). `categories` **scheduled** lane (incremental): `listed 1, unchanged 1`. `categories` **weekly_full** lane: `listed 18, unchanged 18`, 0 writes. This is the production path — Zoho → planner → Celery worker → DB — and the first time it ran in this container's lifetime. |

---

## 6. Deliberately not changed — with a recommendation

| # | Item | Why it was left | Recommendation |
|---|---|---|---|
| ~~O1~~ **DONE** | **`category_tax_preferences`.** *Built as a general capability, not a categories child table — [`tax-assignments.md`](tax-assignments.md): `tax.tax_assignments`, `HasTaxesMixin`, wired to category create/update and to the Zoho hook; verified live (36 assignments, 18 categories × inter + intra).* Original finding: Every live detail carries `[{tax_specification: inter, tax_id: IGST18}, {tax_specification: intra, tax_id: GST18}]` (the `ROOT` detail carries the org default). Stored only in the raw document today, and it is the *reason* the detail call exists. | A child table keyed to `tax.tax_components` is a design decision, not a fix. | **Do this next.** `core.category_tax_preferences(category_id, tax_specification, tax_component_id)`, filled in the hook through `resolve_many` on module `taxes` (both leaf taxes and `tax_type='tax_group'` rows resolve there). It is what lets an item inherit its GST from its category. Until then the detail call buys only three (empty) SEO fields. |
| O2 | The reconcile lane is CLI-only (delta §6.3) and, being source-neutral, does not recompute a taxonomy's nested-set bounds after linking a parent. | Rare path (a parent missing from the same run). | Schedule reconcile (delta §6.3) and give it a per-table `post_link` callback; until then bounds refresh at the next write to that taxonomy. |
| O3 | The hook recomputes the whole taxonomy **per applied row** — O(n²) on a first sync. | 18 rows now; fine to a few hundred. | Batch per page when a profile shows it (same stance as delta §6.7). |
| O4 | Zoho category `custom_fields` are `[{index, value}]`; the generic flatten keys on `api_name`/`label`/`customfield_id` and captures nothing. | Empty for this org; raw is retained. | Fall back to `cf_<index>` if a tenant starts using them. |
| **O5** | `ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING` is `false` in every env file, so **a category deleted in Zoho stays live locally** even though the module now asks for it. A tombstone also does not soft-delete the category's `categorizables` (the service's own delete does). | Platform-wide operator switch. | Turn it on when you are ready for Zoho deletes to reach the tree; decide whether a tombstone should cascade to assignments. |
| O6 | An environment that ran the **old** adapter holds a `zoho_id='-1'` `ROOT` row that nothing will remove while O5 is off. | Only dev ran it. | Dev is already clean. Elsewhere: `DELETE FROM core.categories WHERE zoho_id = '-1'` plus `DELETE FROM sync.sync_records WHERE module='categories' AND external_id='-1'`. |
| O7 | `zoho` is now a de-facto reserved taxonomy slug: a hand-made taxonomy with that slug is adopted by the trigger. | Harmless in practice. | Reserve it in `create_taxonomy` if it ever matters. |
| O8 | `categories` is the first `INCREMENTAL` master, so the planner's weekly-full lane is exercised in production for the first time. | Tested (`test_planner_tick`, e2e). | Watch the first weekly run. |
| O9 | The media migration (`768753121795`) is chained onto the original categories migration, so the alignment migration sits above media. | Not ours. | If categories has not shipped, squash `c063729f29c2` into `c7a1e9b2d4f8` before first deploy — only the dev DB needs the extra step. |

---

## 7. Tests

| File | New / changed |
|---|---|
| `tests/zoho_sync/test_categories_adapter.py` | rewritten: CSV codec; owned set derived + hierarchy; "spec declares what the live API taught us"; list params; SEO array through the API DTO; parent queued + reconcile links it; tombstoned parent; local move refused. |
| `tests/test_categories.py` | crosswalk entity has no mirror columns; SEO round-trip through the API; slug rename → subtree paths; `is_root` follows a raw `parent_id` write. |
| `tests/zoho_core/test_masters_e2e.py` | wire serves `/categories` like the live API (ROOT unless excluded, `+0000`-only filter); planner/CLI/second-pass expectations; **`test_categories_end_to_end_through_the_real_transport`** (ROOT never imported, hierarchy, raw detail with tax prefs, incremental rename touching one row, full-scan tombstone on both sides). |
| `tests/zoho_core/test_planner_tick.py` | weekly-full lane belongs to `categories` alone. |
| `tests/test_worker_boot.py` | **new** — a clean interpreter boots the worker's imports, fires `worker_init`, and every mapper configures (F17). |

**Each fix has a test that fails without it** — checked by reverting the fix and
watching the test go red: `is_root` (tree), `include_root_category` (adapter +
e2e), the pending queue, the `is_root` trigger, and the worker boot hook (which
fails with the original `NoReferencedTableError`).

Results: the categories files, masters e2e and planner tick — 53 passed; import
contracts — 6 kept, 0 broken; full backend suite — see §9.

---

## 8. Files touched

```
alembic/versions/20260925_1400_c063729f29c2_categories_crosswalk_alignment.py   NEW
app/modules/categories/model.py            drop 3 mixins, add zoho_id echo, meta_keywords list
app/modules/categories/tree.py             is_root = parent_id IS NULL
app/modules/categories/service.py          derived owned set (+parent_id), move guard, slug → tree
app/modules/categories/crud.py             count(*)
app/modules/categories/schema.py           meta_keywords list, SEO in create/update, drop 2 null fields
app/modules/categories/zoho/spec.py        INBOUND, include_root_category, soft_delete_missing, owned+parent
app/modules/categories/zoho/fields.py      csv_list codec on seo_keyword
app/modules/categories/zoho/codecs.py      NEW
app/modules/categories/zoho/hooks.py       pending_references queue for an unresolved parent
app/tasks/celery_app.py                    worker_init imports app.router (F17 — not categories-specific)
.importlinter                              categories in six contracts
tests/…                                    see §7 (incl. NEW tests/test_worker_boot.py)
docs/MODULES.md · ZOHO_SYNC_ENGINE.md §5, §9a · PROJECT_STRUCTURE.md · this file
docs/implementation-plan/categories-taxonomies-implementation-plan.md   Rev 3 banner
```

---

## 9. Re-verifying

```bash
# the categories surface (scratch containers; never the seeded app DB)
.venv/bin/python -m pytest tests/test_categories.py tests/test_categories_tree.py \
    tests/zoho_sync/test_categories_adapter.py tests/zoho_core/test_masters_e2e.py \
    tests/zoho_core/test_planner_tick.py tests/test_import_contracts.py

# live, inside the backend container (the WSL venv cannot decrypt the token)
docker exec backend alembic upgrade head
docker exec backend python -m app.modules.zoho.cli sync categories --mode full
docker exec backend python -m app.modules.zoho.cli sync categories            # steady state: 1 call, 0 writes
docker exec backend python -m app.modules.zoho.cli reconcile
```

**Full backend suite** (scratch containers, after every change above):
**955 passed, 14 skipped, 0 failed** in 6 m 53 s. The Zoho suites were
`5 failed, 376 passed` before any change (F1). Import contracts: 6 kept, 0
broken. `ruff check` on every file this change owns: clean. `alembic check`: column
comments settled; **index-name drift remains** (see F15's correction). The migration
round-trips (upgrade → downgrade → upgrade) on the scratch DB and applied cleanly to
the populated dev DB.

## 10. Gotchas worth writing down

1. **`crosswalk=True` and the mirror mixins are mutually exclusive.** Copying the
   mixin composition from an older module (or from the plan's L3) gives a table of
   permanently-NULL freshness columns.
2. **A synthetic parent in a list response is a hazard for any hierarchical Zoho
   endpoint.** Check the live list for a row whose id is the sentinel before
   trusting the doc.
3. **The vendored doc is not the spec.** `last_modified_time`'s documented format
   is rejected by the live API; the engine's own format is what works.
4. **`docker exec` needs `-i` to forward a heredoc.** Without it `psql` gets no
   input, exits 0 and prints nothing — a purge that "ran" and did nothing.
5. **A new registered module changes what "every module" means** in tests that
   enumerate the registry (planner, masters e2e, CLI). Adding a module is a
   test-suite change, not just an adapter.
6. **A Celery worker maps only the models its task modules import; the API maps
   all of them.** Everything under `pytest` runs in the API-shaped world, so a
   worker-only mapper failure is invisible to the suite (F17). Watch the worker's
   `planner_tick` after any change to `app/tasks/` or to what a task imports.
7. **`celery-worker` and `celery-beat` do not hot-reload** (the API does). After a
   migration or an adapter change, restart them, or the planner runs the old
   adapter against the new schema.
