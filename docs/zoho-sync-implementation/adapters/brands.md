# Adapter — brands (`core.brands`, an undocumented Zoho endpoint)

**Status:** ✅ live (pull only) · **Code:** `app/modules/brands/zoho/` ·
**Migration:** `20260928_1700_999509053c9f` (adds `Brand.zoho_id`) ·
**Tests:** `tests/zoho_sync/test_brands_adapter.py`,
`tests/zoho_core/test_masters_e2e.py` · **Source:** none vendored — every fact
below was confirmed live, 2026-09-28. Full design + evidence:
[`implementation-plan/brands-zoho-sync.md`](../../implementation-plan/brands-zoho-sync.md).

## The endpoint

Not in `docs/zoho-docs-md/`. `GET /brands` returns
`{code, message, brands: [{brand_id, name}]}` — no `page_context`
(`paginated=False`); `page`/`per_page` are ignored (confirmed unpaginated).
`GET /brands/{id}` returns the identical two fields (`detail_required=False`).
`last_modified_time` is accepted but has **no filtering effect**
(`strategy=FULL`, `modified_since_param=None`). Only `GET` was verified — no
`POST`/`PUT`/`DELETE` probe was made, so `direction=INBOUND` and there is no
`to_zoho_payload`.

## Table

`core.brands` (`app/modules/brands/model.py`) — the pre-existing canonical
brand master, **not a new mirror table**. This adapter added one column,
`zoho_id` (echo of `brand_id`; identity of record stays `sync.sync_records`),
plus its partial unique index. Every other column (`slug`, `code`, `kind`,
`parent_id`, `country_code`, `description`, `website_url`, `logo_storage_key`)
has no Zoho counterpart and stays fully locally editable, even on a linked row.

## Why this table and not a separate mirror

`Brand`'s original docstring said "not a Zoho mirror" — a deliberate prior
decision. Reusing it anyway, rather than adding a parallel table, was the
user's explicit choice once the endpoint was confirmed live: one brand model
for the whole app, so `brand_manufacturers`, tags, documents and
`search/registry.py` all work on synced brands for free. The risk that choice
carries — a Zoho brand silently merging into a same-named local one — is closed
by `match_on=()` (§ below), not by keeping the tables apart.

## Identity: `match_on=()`

Never merge. The same rule `taxes` uses: two authorities can share a name (a
tenant could have hand-created "Dabur" before the first sync), and guessing a
match is worse than a duplicate. `core.brands`' own `uq_brands_scope_name`
partial unique index is the backstop: a genuine name collision fails the ONE
colliding record (counted as an error in the run, isolated by the engine's
per-record retry) rather than silently duplicating or merging. Verified live by
test (`test_a_local_brand_with_the_same_name_is_never_silently_merged`).

## Scope: `brands/zoho/hooks.py::stamp_scope`

`core.brands` requires a provenance pair (`PolymorphicOwnerMixin`:
`owner_type`/`owner_id`) the payload cannot supply, and Zoho's brand list is
tenant-wide with no organization concept. The organization comes from the
run's context (the connection that scheduled the sync) — copied from
`currencies/zoho/hooks.py::stamp_scope`, not shared, because the rule-error
type differs per module. The same hook adds a slug fallback (Zoho sends no URL
key), only when the row does not already have one.

## What is NOT built, and why

- **Push.** No create/update/delete was attempted against live data with no
  documented contract to write against. `direction=INBOUND` only.
- **A brand ↔ item link.** Zoho denormalises the brand NAME directly onto each
  item (`item.brand: "HUL"`), not `brand_id` — there is no cross-reference to
  resolve through the crosswalk even if an `items` module existed.
- **Custom-field capture** is declared (`capture_custom_fields=True`, harmless)
  but nothing was observed on this resource.

## HTTP

Existing `/api/brands` surface, unchanged in shape: `GET`/`POST`/`PATCH`/
`DELETE`, brand↔manufacturer links. `BrandOut` gained `zoho_id`. A linked
brand's `name` is refused on `PATCH` (`_guard_zoho_owned`); every other field
stays writable.
