# Adapter — locations (O1 master)

**Status:** ✅ live (pull) · **Code:** `app/modules/locations/` ·
**Migration:** `e6e42c16c52e` (`zoho_locations`) · **Tests:** `tests/zoho_core/test_masters_e2e.py`
· **Source:** `docs/zoho-docs-md/locations.md`

> **Since 2026‑09‑20** the `post_upsert` hook projects every synced row into a canonical place
> (`geo.places`, [`../../geo/README.md`](../../geo/README.md) §8) with `zoho_id` set and
> `kind = 'warehouse'`, so a Zoho warehouse can be addressed, geofenced and related like
> anything else. The mirror below stays the record of what Zoho said; the place is the usable
> address, and Zoho owns its postal columns.

| Aspect | Value | Why |
|---|---|---|
| Endpoint | `GET /locations` (Books) | branches; with Zoho Inventory's unified locations also warehouses |
| Pagination | **none** (`paginated=False`) | documented response has no `page_context` **[verify]** |
| Detail call | none — no `GET /locations/{id}` exists | the list row is complete |
| Id attribute | `location_id` | — |
| Strategy | `full`, daily; no weekly lane | no `last_modified_time`; 1 call/day |
| Direction | inbound only | managed in Zoho |
| Prerequisite | locations enabled in Zoho (`POST /settings/locations/enable`) | otherwise Zoho answers with an error and the run is `failed` with Zoho's message — the right signal |

| Column | Zoho attribute |
|---|---|
| `location_name`, `type`, `status`, `is_primary`, `email`, `phone` | same |
| `parent_location_id` | same (hierarchy; resolved lazily, no FK) |
| `tax_settings_id` | same (India: GSTIN settings per location) |
| `auto_number_generation_id`, `is_all_users_selected` | same |
| `associated_series_ids`, `associated_users` | same, stored as JSONB (`[{user_id, user_name}]`) |
| `address_attention/street1/street2/city/state/state_code/country` | `address.*` flattened |

HTTP (read-only): `GET /api/zoho/locations?status=active` (primary first) ·
`GET /api/zoho/locations/{ref}`.

Open:
* Inventory warehouses (`/warehouses`, Inventory API) are **not** in the
  vendored docs, so they are not built. Add the Inventory reference to
  `docs/zoho-docs-md/` first (the "docs are law" rule).
* `associated_users` as a child table when something needs to join on it.
