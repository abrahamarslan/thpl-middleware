# Tax assignments — one polymorphic table for "this entity carries these taxes"

**Status:** implemented and verified live (2026-09-25).
**Code:** `app/modules/taxes/{assignment,mixins,registration}.py`,
`assignment_{crud,service,schema,api}.py` · **Migrations:** `84daf73430b6`
(tables, triggers, `category` registration), `cbdb4590446e` (repairs three broken
orphan finders — §11).
**First consumer:** categories (`tax_preferences`, fed by Zoho's
`category_tax_preferences`) — see also
[`categories-zoho-sync-review.md`](categories-zoho-sync-review.md) §6 O1, now closed.

---

## 1. What existed, and what did not

You asked whether a polymorphic "which entity carries which tax" table was already
built. **It was not.** The `tax` schema had two org-level tables and nothing that
attaches a tax to a *thing*:

| Existing table | What it says | Why it can't do this |
|---|---|---|
| `organization_tax_components` | which organizations may **use** a tax (a grant) | organization ↔ tax only |
| `org_default_tax_preferences` | an organization's default tax per inter/intra | organization only |

So a category, an item, a customer or an invoice line had no home for its taxes —
and each would have grown its own column or child table (Zoho's
`category_tax_preferences`, an item's `tax_id`, a contact's `tax_exemption_id`, a
line's `line_item_taxes`). This adds the one table they all share. The two existing
tables are unchanged and keep their meaning: **grants say what an organization may
use; assignments say what an entity carries.**

## 2. The shape

```
core.entity_types  ◄── FK ──  tax.taxable_entity_types  ◄── FK ──  tax.tax_assignments ──► tax.tax_components
 (the platform's               (policy: which classes                 owner_type_code + owner_id  └─► tax.tax_exemptions
  polymorphic registry)         may carry taxes, and how)             + context + optional snapshot
```

* **`tax.taxable_entity_types`** — GLOBAL policy, one row per entity class that may
  carry taxes: `allows_multiple` (one tax per context vs several apply together),
  `allows_exemption`, `is_enabled`. Written by the migration of the module that owns
  the entity. No write API.
* **`tax.tax_assignments`** — one row per (owner, tax-or-exemption, context).
  `owner_type_code` + `owner_id` name the owner; `tax_component_id` **or**
  `tax_exemption_id` names what it carries; `tax_specification` (`inter`/`intra`) and
  `transaction_type` (`sales`/`purchase`) narrow *when*; `NULL` in either means "any".

**Name.** I did not call it `taxables`: house precedent is `categorizables` /
`taggables`, but "taxable" already means "subject to tax" in this domain, and a
`taxable` row that says "this is a tax" reads backwards. `tax_assignments` says what
the row is. The consumer side keeps the house vocabulary: `HasTaxesMixin`.

## 3. What a row means

| Column | Meaning |
|---|---|
| `owner_type_code` | `core.entity_types.code` (`category`, later `item`, `customer`, `invoice_line` …). FK to the policy table — so the class is registered **and** opted in, in the database |
| `owner_id` | the owner's internal id. No FK (polymorphic); proved at COMMIT |
| `tax_component_id` / `tax_exemption_id` | a tax rate or **group** / an exemption. Exactly one (or neither while *pending*, below) |
| `tax_specification` | `inter` / `intra` / `NULL` = any — GST's inter-state vs intra-state |
| `transaction_type` | `sales` / `purchase` / `NULL` = both |
| `position` | order when several taxes apply together |
| `source_system` | `NULL` = maintained locally · `'zoho'` = fed by the sync (read-only through the API) |
| `external_ref` | while **pending**: the source's tax id, when we have not synced that tax yet |
| `snapshot`, `frozen_at` | the tax as it was when the owning document was issued (§7) |

**One tax per context, or several.** Zoho gives a category, an item and a contact
exactly one tax per inter/intra context, so those classes register
`allows_multiple=False` and the database rejects a second. An invoice line in India
carries IGST *and* cess together, so it registers `allows_multiple=True`. A tax
*group* (GST18 = CGST9 + SGST9) covers the common multi-tax case without needing it.

**Exemptions.** Items, contacts and lines can carry a `tax_exemption_id` in Zoho; a
category cannot. `allows_exemption` says which classes may, and the same row shape
holds either.

**Pending rows.** A source can name a tax the `taxes` module has not synced yet. The
row is written anyway with `tax_component_id = NULL` and `external_ref` set, plus a
`sync.pending_references` waiter that the **generic** reconcile lane links
(`UPDATE tax.tax_assignments SET tax_component_id = …`). Nothing new was built for
that — and the entity is never silently left untaxed. Pending rows never answer a
resolution.

## 4. Integrity — enforced by the database, pre-flighted by the service

| Rule | Service (clean 4xx) | Database (authoritative) |
|---|---|---|
| owner class is registered and opted in | `TaxRuleError` | FK `tax_assignments → taxable_entity_types → core.entity_types` |
| owner exists | 404 | deferred `assert_entity_exists` |
| owner is in the assignment's tenant **and organization** | derived from the owner | deferred `tax.assert_owner_scope` (probes the owner table's columns — works for any class) |
| class may carry an exemption | 422 | deferred `check_tax_assignment_integrity` |
| one tax per context unless several are allowed | 422 | same trigger, serialised per owner by an advisory lock |
| no duplicate tax in a context | 422 | partial unique indexes, `NULLS NOT DISTINCT` (NULL = "any" must collide with itself) |
| the tax is the same tenant's | "not found" | composite FKs to `tax_components` / `tax_exemptions` |
| the organization may **use** the tax | 422 (`organization_tax_components`) | — (a source vouches for its own taxes) |
| a frozen assignment never changes | 409 | `tax.guard_frozen_tax_assignment` |
| a source's rows are not edited locally | 422 | — |
| orphans (owner hard-deleted) | — | `tax.find_orphan_tax_assignments()` |

Every rule is asserted twice in `tests/test_tax_assignments.py`: once through the
service/API for the message, once by **writing past the service** and committing, for
the database.

## 5. Making an entity taxable — the whole recipe

Three steps, none of them a change to the `tax` schema.

**1 · In the entity's own migration** (or seeder) — one call:

```python
from app.modules.taxes.registration import register_taxable_entity_type

register_taxable_entity_type(
    op.get_bind(), code="item", name="Item", target_schema="catalog", target_table="items",
    allows_multiple=False, allows_exemption=True,
)
```

It registers the class in `core.entity_types` (unless already there) and opts it in.
Idempotent, and it **never overwrites** a rule an operator has tightened.

**2 · On the model** — one mixin:

```python
class Item(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasTaxesMixin, Base): ...
```

`Item.tax_assignments` is a view-only relationship (`lazy="raise_on_sql"`): read it
with `selectinload(Item.tax_assignments).joinedload(TaxAssignment.tax_component)`.

**3 · In the entity's service** — write through the one writer:

```python
await tax_assignments.replace_assignments(db, "item", item.id, specs, organization_id=…, actor_id=…)
await tax_assignments.remove_owner_assignments(db, "item", item.id, reason=…)   # on delete
```

…and accept the shared input shape in the API: `tax_preferences: list[TaxAssignmentItem]`.

The policy each class from your list would register (Zoho's shapes):

| Class | `allows_multiple` | `allows_exemption` | Why |
|---|---|---|---|
| `category` *(live)* | no | no | one tax per inter/intra; Zoho categories carry no exemption |
| `item` | no | yes | `tax_id` per context + `tax_exemption_id` |
| `customer` (contact) | no | yes | default tax + exemption = "tax preferences". `gst_treatment` and `place_of_supply` are **columns of the contact**, not assignments |
| `invoice_line` | **yes** | yes | India's `line_item_taxes[]`; issued lines are frozen (§7) |

Import direction is enforced by `.importlinter`: consumers import `taxes`, `taxes`
never imports a consumer (`taxes-never-import-a-consumer`).

## 6. Resolution — "which tax applies here?"

`select_applicable(rows, specification, transaction_type)` (pure) narrows one
owner's rows to a context:

* a row applies when each context column is either unset ("any") or equal to the
  context asked for;
* **only the most specific level survives** (both columns set › one › none) — an
  owner's `inter` tax **overrides** its any-context tax for an inter-state sale
  instead of stacking on it;
* what remains at that level applies together, in `position` order;
* asking with `specification=None` ("I don't know") matches only rows that don't
  care — never a row that names a specification.

`resolve_taxes(db, owners=[("invoice_line", 9), ("item", 4), ("category", 2)], …)`
walks a chain **most specific first** and returns the first owner whose assignments
apply, falling back to the organization's default (`org_default_tax_preferences`).
The chain is the **caller's policy**: this module knows what each owner carries, not
that a line inherits from an item that inherits from a category. Exposed as
`GET /api/taxes/assignments/resolve?owner=item:4&owner=category:2&specification=inter`.

## 7. Assignments are references, not amounts — and how to freeze one

A row points at a **live** `tax_components` row, so a rate change reaches every
category and item that carries it. That is right for a category and wrong for an
invoice already sent. `freeze_owner(db, "invoice_line", line_id)` (for the document
module to call when it issues a document) writes a `snapshot` — name, rate, type
and, for a group, **its members** (so CGST 9 + SGST 9 survives either changing) —
and stamps `frozen_at`. From then on the database refuses any change to the row
(soft-delete is still allowed) and the service refuses to replace the owner's taxes.

**Tax amounts are not here.** They depend on a taxable base this table never sees;
the document module computes them from a resolved (or frozen) assignment. An
exemption's snapshot keeps only its id and type — its code and name are P2 (they hold
customers' names, see `exemption.py`), so erasure stays one place to act.

## 8. Categories — wired end to end

**API.** `POST/PATCH /api/categories` accept `tax_preferences` (the shared
`TaxAssignmentItem`); `GET` returns them. On PATCH, *present* means replace (an empty
list clears the local taxes), *absent* means untouched. Deleting a category removes
its assignments. A Zoho-linked category's taxes are read-only, like its fields.

**Zoho sync.** The detail document's `category_tax_preferences` →
`tax_assignments` with `source_system='zoho'`, in the categories hook:

* the tax id resolves through the crosswalk (a leaf tax and a tax **group** share one
  id namespace and both land in module `taxes` — verified: live `IGST18` and the
  `GST18` group resolve);
* only the **detail** document carries the array; a thin list row says nothing about
  taxes and never clears them;
* an unsynced tax → a pending row + waiter (§3); two taxes for one context, or an
  opted-out class → logged and skipped, never a failed page;
* a replace touches only `source_system='zoho'` rows.

**Backfill.** A normal sync never revisits an unchanged category, but each crosswalk
row keeps the full document it last applied. `python -m
app.modules.categories.zoho.backfill` replays those through the same hook — **no API
calls**, idempotent — for categories synced before this existed.

## 9. HTTP — `/api/taxes/assignments`

| | |
|---|---|
| `GET /taxable-types` | which classes can carry taxes, and their rule |
| `GET /resolve?owner=type:id…&specification=&transaction_type=&organization_id=` | which tax applies |
| `GET /{owner_type}/{owner_id}` | one owner's taxes |
| `PUT /{owner_type}/{owner_id}` | replace the owner's **local** taxes |
| `DELETE /{ref}?reason=` | remove one local assignment (`TenantAdmin`) |

## 10. Verified live (real Zoho, dev stack)

| Check | Result |
|---|---|
| Both migrations on the dev DB | applied; `category` registered + opted in |
| The tax ids Zoho names for categories | `IGST18` (leaf) and `GST18` (group) both in the `taxes` crosswalk |
| Backfill (no API calls) | `scanned 18, replayed 18` → **36 assignments** (18 × inter + intra), all Zoho-sourced, all resolved, 0 pending |
| Real sync path | one category forced to re-apply: `updated=2`, hook ran twice, assignments **unchanged** (ids 1–36, none recreated, none soft-deleted) |
| API DTOs | all 18 categories serialise with 2 `tax_preferences` each |
| Resolution | `category, inter → IGST18` · `intra → GST18 (group)` · no context → none |
| Celery planner | healthy after restart (6 of 6 ticks) |

## 11. Found on the way

* **Three of the four `find_orphan_*` safety nets could never run.**
  `core.find_orphan_entity_aliases()` (pre-existing), `core.find_orphan_categorizables()`
  (mine, earlier today) and this table's own all declared `text` result columns over
  `varchar` source columns, so every call raised *"structure of query does not match
  function result type"*. Nothing called them. Only `extfields.find_orphan_field_values()`
  worked. Fixed in `cbdb4590446e` (`CREATE OR REPLACE`, one `::text`) and pinned by
  `tests/test_orphan_finders.py`, which runs all four. This was caught by writing the
  orphan test for the new table — an untested safety net is not one.
* **`alembic check` does report index-name drift on the four categories tables** — my
  earlier claim in the categories review that it reported "nothing" filtered only
  comment operations. The hand-written migrations name indexes `ix_<table>_<col>`
  where the model's default is `ix_<schema>_<table>_<col>`; the same is true of the
  `extfields` tables. Cosmetic, house-wide, left alone. The new tables have **no** drift.
* A stale-identity-map bug caught by the API test: after replacing a category's taxes
  the same request returned the *old* ones. The service now expires the relationship.

## 12. Not built, and why

| Item | Why | Recommendation |
|---|---|---|
| An **item / customer / invoice-line module** | none exists (`contacts/items` are on hold) | register each with `register_taxable_entity_type` when it lands (§5) |
| A soft-deleted (tombstoned) **category keeps live assignments** | the engine's tombstone calls no hook; the service's own delete does clean up | reads go through the category so it is invisible; add a tombstone callback if `usage_of_component` counts must be exact |
| A pending **exemption** (kind is not stored on the row; only the waiter's column says) | only taxes arrive pending today | add `external_kind` if a source names unsynced exemptions |
| The **reconcile lane is CLI-only** ([delta v3 §6.3](sync-crosswalk-delta-v3.md)) | pre-existing | schedule it; pending assignments then link unattended |
| **Org defaults** (`org_default_tax_preferences`) stay a separate table | they work, and are org-level | could become `owner_type='organization'` assignments later; resolution already falls back to them |
| **Rate-change impact** | `crud.usage_of_component` counts carriers; no endpoint | expose it on `GET /api/taxes/{ref}` if a UI needs "used by N" |

## 13. Tests

| File | Covers |
|---|---|
| `tests/test_tax_assignments.py` (32) | context resolution (pure), identity, snapshot, mixin, index shape · category API create/replace/clear/keep, one-per-context, no-exemption, grants, cross-tenant, delete cascade · generic API · several-taxes + exemption class · diff-based replace and source separation · resolution chain + org-default fallback · freeze + frozen guard · pending → reconcile · **the database rules by writing past the service** · disabled class · orphan finder · idempotent registration |
| `tests/zoho_sync/test_categories_adapter.py` (+7) | Zoho prefs → assignments · pending + reconcile · Zoho-side change · thin row clears nothing · bad data skipped · linked category refuses edits · backfill |
| `tests/zoho_core/test_masters_e2e.py` | through the **real transport**: 3 categories × 2 taxes resolved to the components the `taxes` module synced |
| `tests/test_orphan_finders.py` (4) | every orphan finder runs |
| `tests/test_tax_schema.py`, `test_tenancy.py`, `conftest.py`, `.importlinter` | eight tables; policy table allow-listed as global; truncation order; taxes never imports a consumer |

Mutation-checked: removing the relationship expiry, the specificity rule, the
integrity trigger, or the frozen guard turns the matching test red.

**Suite:** full backend run **998 passed, 14 skipped, 0 failed** (was 955 before this
work: +43 tests). One earlier full run showed a single failure in
`test_currencies.py::test_a_currency_in_use_is_archived_not_deleted` (a live-rate count;
no tax code path); it passed alone, in its file, in the same order as the failing run,
and in the next full run — recorded here as an unexplained one-off, not as a fix.
`ruff` clean on every file owned; import contracts 7 kept (the new
`taxes-never-import-a-consumer` included); both migrations round-trip; `alembic check`
shows no drift on `tax_assignments` / `taxable_entity_types` / `tax_exemptions`.
