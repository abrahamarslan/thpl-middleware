# Brands ↔ Zoho — a real, undocumented endpoint, synced on explicit instruction

**Status:** implemented and verified live (2026-09-28).
**Code:** `app/modules/brands/zoho/{spec,fields,hooks}.py` · **Migration:**
`20260928_1700_999509053c9f` · **Adapter doc:**
[`zoho-sync-implementation/adapters/brands.md`](../zoho-sync-implementation/adapters/brands.md).

---

## 1. What was asked, and what was found

The request was to "sync categories and brands from Zoho." Categories already
had a working adapter (`categories-zoho-sync-review.md`). Brands did not:
`app/modules/brands/` is the pre-existing local module, and its `Brand` model's
own docstring said, in so many words, **"not a Zoho mirror."** There is also no
`brands.md` in `docs/zoho-docs-md/` and no mention of "brand" anywhere in the
34 vendored Zoho documents (checked with a full-text search, including
`items.md` field by field).

Rather than either inventing a shape or reporting "impossible" from the
absence of a vendored doc, I ran a small number of **read-only** live probes
against the connected Zoho org (governor-tracked, well inside quota):

| Probe | Result |
|---|---|
| `GET /brands` | **200** — `{code, message, brands: [{brand_id, name}]}`, 7 rows |
| `GET /settings/brands`, `GET /itembrands` | 404 (guesses at a documented-style path; both wrong) |
| `GET /brands/{id}` | **200** — identical two fields, nothing extra |
| `GET /brands?page=1&per_page=1` | still 7 rows — pagination params ignored |
| `GET /brands?last_modified_time=…` | still 7 rows — the filter has no effect |
| `GET /items` (200 sample) | every item carries `brand: "HUL"` — **the NAME**, not `brand_id` |

So: a real, live, undocumented resource exists, its shape is minimal and now
fully known, and nothing about it was guessed — every configuration choice in
the adapter traces to one of the rows above.

**This directly contradicted the codebase's own prior decision.** That is
exactly the kind of choice this session does not make unilaterally, so I
stopped and asked (`AskUserQuestion`) with the live findings in hand: reuse
`core.brands` (reversing the "not a Zoho mirror" design), build a separate
mirror table, or just prove it works without persisting. **You chose the
first** — sync into `core.brands`, `match_on=()` (never merge a same-named
local brand). Everything below implements that answer.

## 2. What changed

* **`core.brands` gains one column: `zoho_id`** (migration
  `999509053c9f`), plus its partial unique index
  (`uq_brands_zoho_id_live`) — the same crosswalk echo shape as
  `core.categories.zoho_id`. No mirror columns (`zoho_raw`, `sync_version`, …)
  — identity and gate state live in `sync.sync_records`, exactly the
  categories/currencies precedent.
* **`app/modules/brands/zoho/`** — `spec.py` (config + contract),
  `fields.py` (one field: `name`), `hooks.py` (`stamp_scope`, copied from
  `currencies/zoho/hooks.py` rather than shared, because the rule-error type
  differs per module).
* **`Brand.service._guard_zoho_owned`** — a linked brand's `name` is refused on
  `PATCH` (change it in Zoho); every other field (`slug`, `code`, `kind`,
  `parent_id`, `country_code`, `description`, `website_url`,
  `logo_storage_key`) stays fully locally editable, since Zoho feeds nothing
  else.
* **`BrandOut.zoho_id`** exposed on the Fat DTO.
* **`.importlinter`** — `app.modules.brands` added to all six contracts that
  already list `app.modules.categories` (platform-never-imports-a-master,
  features-never-call-zoho-directly, features-independent,
  location-hub-below-masters, tenancy-core-below-masters,
  sync-core-is-source-neutral).
* **`app.modules.zoho.sync.registry._ADAPTER_PACKAGES`** — one new line.

## 3. Design choices, and why each one is what it is

### 3.1 `match_on=()` — never merge

`core.brands` enforces one live brand per (tenant, organization, normalized
name) at the database level regardless of source (`uq_brands_scope_name`). A
Zoho brand is **never** matched onto an existing local row by name-guessing —
the `taxes` module's rule ("two authorities can both define 'VAT 20%'"; here,
two names can coincide without being the same brand, or a tenant may have
hand-created "Dabur" before the first sync). If a genuine collision happens,
the write to the entity table fails on the unique index — the engine isolates
it per-record (falls back to `_apply_one_by_one`, retries once, then counts it
as an error) — the record is **never silently duplicated or merged**, and the
pre-existing local row is untouched. Proven by
`test_a_local_brand_with_the_same_name_is_never_silently_merged`: a local
"DABUR" exists, the sync tries to create a Zoho "DABUR" (different
`brand_id`), the sync record fails, the local row is unchanged and no
`zoho_id` was ever attached to it.

(`core.brands` is currently **empty** in dev, so this scenario cannot occur
today — it is guarded for the day it can.)

### 3.2 `strategy=FULL`, not `INCREMENTAL`

The live API accepts `last_modified_time` as a query parameter without
rejecting it, but it also does not filter with it — every row comes back
regardless. Declaring `INCREMENTAL` against a no-op filter would be *worse*
than declaring `FULL`: the engine would maintain a cursor that never narrows
anything, and a future reader would reasonably believe incremental scans work
here. `FULL` says what is actually true.

### 3.3 `direction=INBOUND`, no `to_zoho_payload`

Only `GET` was probed. `POST`/`PUT`/`DELETE` on an undocumented endpoint were
**deliberately never attempted** — a live org's data is not the place to guess
a write contract, and every other adapter in this codebase that offers a push
seam does so against a *documented* body shape (`docs/zoho-docs-md/`).
Categories itself was corrected from a wrongly-declared `BIDIRECTIONAL` to
`INBOUND` in the prior review for the same reason. `to_zoho_payload` is simply
absent here, not stubbed — there is nothing honest to build yet.

### 3.4 Reusing `core.brands`, not a new table

The three options put to you were: reuse `core.brands`, build a separate
mirror table, or don't persist. Reuse was chosen. The consequence recorded
here for future readers: `Brand`'s docstring no longer says "not a Zoho
mirror" — it says the opposite, and explains why the reversal happened
(this document). Anything that already depends on `core.brands` (brand↔
manufacturer links, tags, documents, `search/registry.py`) works on a
Zoho-synced brand automatically, with no separate code path.

## 4. Verified live (real Zoho Books, dev stack, 2026-09-28)

| Step | Result |
|---|---|
| `GET /brands` (initial probe) | 7 brands: NAHOA, DABUR, HIMALAYA, PROCTOR & GAMBLE, CACTUS GOODNESS, RECKITT BENCKISER, HUL |
| Migration on the dev DB | `core.brands.zoho_id` added; index created (see §6 for the merge-head detour) |
| Full sync: `python -m app.modules.zoho.cli sync brands --mode full` | `listed=7 created=7 errors=0`; slugs correctly derived (`"PROCTOR & GAMBLE"` → `proctor-gamble`), `organization_id=1`, `owner_type=organization`, `parent_id` NULL |
| Steady-state re-sync | `listed=7 unchanged=7`, one API call, zero writes |
| Crosswalk (`sync.sync_records`) | 7 rows, all `link_state=linked`, `raw_source=list:full` |
| A brand's `name` edited on a linked row via the service (`PATCH` path) | refused — `CoreRuleError`: *"name is owned by Zoho for this brand (zoho_id 954919000013118046); change it in Zoho — the next sync brings it here"* |
| The same linked row's `country_code` edited | accepted (rolled back — a read-only verification, not a persisted change) |
| `GET`-equivalent through `BrandOut` for all 7 rows | valid, `zoho_id` populated |
| Governor | 13 of 45,000 calls used across every probe and run this session |
| Celery planner, post-restart | 5+ consecutive ticks succeeded, brands correctly `skipped` once already synced within its interval |

## 5. Tests

| File | Covers |
|---|---|
| `tests/zoho_sync/test_brands_adapter.py` (9) | mapper; owned-field derivation; spec declares only what was verified live; sync creates + slug-falls-back + stamps scope; re-sync doesn't duplicate; a Zoho-side rename updates the row; **a same-named local brand is never merged** (the core correctness property of `match_on=()`); a linked row refuses a `name` edit but allows everything else. |
| `tests/zoho_core/test_masters_e2e.py` | brands added to the real-transport wire (list-only, matching the live shape exactly, including the ignored pagination/filter params); planner/CLI/second-pass/inserted-event-count expectations updated. |
| `.importlinter` / `test_import_contracts.py` | `app.modules.brands` follows the same six rules every other Zoho master does. |

## 6. Found on the way

* **The dev stack was down when this session started re-verifying** (a Docker
  Desktop/WSL restart during the long prior session; only the two standalone
  scratch containers survived). Brought back up with
  `deployment/manage.sh start` from WSL — data volumes were preserved
  (`docker compose down` keeps volumes; nothing had run `-v`), confirmed by the
  18 categories / 36 tax assignments from the prior session still being there
  after `up -d`.
* **The planner raced the migration.** `celery-worker`/`backend` bind-mount the
  code and register every adapter (including this one) the moment they start —
  before `alembic upgrade head` had been run on the freshly-restarted dev DB.
  One scheduled brands run fired in that window and recorded `errors=7` (the
  column did not exist yet). This is correctly captured in `zoho_sync_runs` as
  its own row, not hidden — the very next full sync, after the migration,
  succeeded cleanly (`created=7 errors=0`). No code fix needed; it is the
  expected shape of "a container starts before its schema is current," logged
  honestly rather than silently retried.
* **Two migrations forked from the same parent.** Another session's comments
  module (`f3a1b6c9d2e7`) and this one's brands column (`999509053c9f`) both
  chained onto `807ccba816ef` independently, producing two `alembic heads`.
  Resolved with a standard no-op merge migration
  (`8f3f9c0b6d65`) rather than re-parenting either — the safe, reversible fix
  for two genuinely independent branches.
* **The scratch Postgres this session's tooling pointed at had moved** (see
  the memory note `dev-environment-wsl.md`): `thm-scratch-pg` is now on host
  port 15432, not the hardcoded 55432 `tests/conftest.py` defaults to. Running
  the suite against the wrong port doesn't fail — it makes ~all
  integration/DB tests SKIP (their documented fallback for "services
  unreachable"), which looked at first like 577 tests had gone missing. Fixed
  by overriding `DATABASE_URL` explicitly.

## 7. Not built, and why

| Item | Why |
|---|---|
| Push (create/update/delete in Zoho) | undocumented write contract; not guessed |
| A brand ↔ item cross-reference | Zoho denormalises the brand NAME onto items, not an id; nothing to resolve through the crosswalk without an `items` module |
| Custom fields on this resource | `capture_custom_fields=True` is declared (harmless) but none were observed |
| A search/CDC wiring change | brands was already searchable/CDC'd; the new column needs no new wiring |

## 8. Full-suite re-verification

Everything above was checked against a full backend run, not just the new
files: **1103 passed, 14 skipped, 0 failed** in 13 m 06 s (up from 998 before
this task — +105 tests: the brands adapter, plus whatever landed from other
concurrent sessions in the same window). Two environmental incidents surfaced
and were resolved during this recheck, neither a code defect:

* Two accidental concurrent `pytest` runs against the same scratch database
  (my own mistake, re-running a subset while a full run was already in
  flight) produced real `IntegrityError`/`TRUNCATE`-contention failures —
  discarded, not fixed, because there was nothing to fix; both processes were
  killed and the full suite re-run once, cleanly, alone.
* That `pkill -9` left one orphaned idle Postgres backend
  (`state=idle, wait_event=ClientRead`, last statement `ROLLBACK;`) holding a
  lock the next `TRUNCATE` needed, stalling the re-run for several minutes
  with no visible progress. Found via `pg_stat_activity`, cleared with
  `pg_terminate_backend()`; the suite resumed immediately.
