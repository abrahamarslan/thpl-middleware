# Adapter — taxes (the `tax` schema)

**Status:** ✅ live (pull) for `taxes` and `tax_exemptions` · `tax_groups` registered **disabled** ·
**Code:** `app/modules/taxes/` · **Migration:** `62303d9097fe` (replaces `f84b5c2e60a7`'s `tax.taxes`) ·
**Tests:** `tests/test_tax_schema.py`, `tests/zoho_core/test_taxes_adapter.py`, `test_masters.py`,
`test_batch_apply.py` · **Source:** `docs/zoho-docs-md/taxes.md` + the captured payloads catalogued in
`app/modules/taxes/mappings.py`

## Tables

| table | class | what it is |
|---|---|---|
| `tax.tax_components` | ENTITY (`TenantEntityMixin` + deactivation) | one row per tax **or** tax group, discriminated by `tax_type` (`tax` · `compound_tax` · `tax_group`). Zoho shares one id namespace between the two, hence one table |
| `tax.tax_group_members` | scoped, audited, soft-deletable | which leaf components compose a group; `position` = index in Zoho's `taxes[]` |
| `tax.tax_exemptions` | scoped, audited, soft-deletable | exemption reasons. `tax_exemption_code` / `exemption_name` are **P2** (they hold customers' personal names) |
| `tax.organization_tax_components` | `MultiTenantMixin` (org NOT NULL) | organization ↔ component grants, M:N; `is_active` is the per-organization switch |
| `tax.org_default_tax_preferences` | scoped, audited, soft-deletable | default component per organization and `inter`/`intra`; `NULLS NOT DISTINCT` unique so a tenant-wide default is still unique |
| `tax.gst_treatment_types` | **GLOBAL** (allow-listed in `test_tenancy.py`) | GST / tax treatment vocabulary; nullable `owner_type`/`owner_id` provenance |

No table carries a Zoho id: identity is `sync.sync_records`. Every child FK is composite
`(tenant_id, x_id)`, so a row can never pair components of two tenants. Lifecycle (`status`,
deactivation) is on `tax_components` only; `status` is Zoho-fed (`lower`, empty → `active`).

## Modules

| module | endpoint | state | notes |
|---|---|---|---|
| `taxes` | `GET /settings/taxes[/{id}]` | ✅ FULL daily, `index_then_detail` | leaf rows. Post-hook grants the context organization the component (never re-grants a revoked one) |
| `tax_exemptions` | `GET /settings/taxexemptions[/{id}]` | ✅ FULL daily, `paginated=False` | documented list has no `page_context` (the currencies precedent) — revisit if a tenant exceeds one page |
| `tax_groups` | `GET /settings/taxgroups/{id}` | ⏸ **DISABLED** | Zoho documents create/get/update/delete but **no list**, so the scan has nothing to walk. The adapter is complete and tested via `apply_payload`; the Phase-6 resolver will fetch a group by id when an invoice names one |

`taxes[]` → `tax_group_members` resolves each member through the crosswalk. A member not synced
yet **raises `TaxGroupError`**: the record's transaction rolls back and the next attempt is judged
afresh — a group is never silently linked to fewer members than Zoho lists. A group listing a
group, or a deleted member, raises likewise. A payload with no `taxes` key changes nothing; an
empty array soft-deletes every member.

## Rules worth knowing

* `tax_type` accepts `tax`, `compound_tax` (documented by Zoho; the redesign paste omitted it) and
  `tax_group`. The **legacy numeric** `tax_type` (0/2) is refused, not guessed — which integer is
  which has not been verified; the raw integer belongs in `source_default_tax_type_code`.
* `tax_specific_type` has no CHECK (India, Mexico and South Africa each define their own); the
  generic sentinel `"tax"` and `""` decode to NULL, and a group is always NULL (CHECK).
* A value a CHECK would refuse (`tax_specification` ≠ inter/intra, a rate outside `0…999.9999`) is
  dropped by its codec with a warning — the record survives.
* Direction: `BOTH` only for attributes Zoho documents as create/update arguments; everything
  captured-but-unverified is `IN`, so `to_zoho_payload` cannot send it. Groups are refused by
  `to_zoho_payload` (different resource).
* `content_hash` on the entity is **not** stamped by the sync (the crosswalk's `raw_hash` is the sync's
  hash); it serves hash-guarded writers that bypass the crosswalk.

## Not wired (no documented endpoint)

`default_taxes[]` → `org_default_tax_preferences` (+ `is_non_advol_tax`, `source_new_tax_type`,
`source_default_tax_type_code`) and `gst_treatments[]` / `tax_treatments[]` →
`gst_treatment_types` have tables, constraints and catalog rows, but no adapter: their endpoints are
not in `docs/zoho-docs-md`, and the master prompt forbids inventing one.

## HTTP (read-only, authenticated) — `/api/taxes`

`GET ?tax_type=&specific_type=&organization_id=` (Slim) · `GET /{ref}` (Fat: members + crosswalk
`sources`; `ref` = local id, uuid or Zoho id) · `GET /exemptions` · `GET /gst-treatments` ·
`GET /default-preferences?organization_id=`.

## Field catalog

`app/modules/taxes/mappings.py` records every Zoho leaf path (class A–K, layer, transform,
sensitivity). It is lineage, not the executable contract (`zoho/fields.py` is); `test_tax_schema.py`
fails if a catalog target is not a column, or a `FieldSpec` runs without a catalog row.
