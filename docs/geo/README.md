# Location hub — places, addresses, geofences

**Status:** ✅ live · **Schema:** `geo` · **Migration:** `4f2f2a8c7898` (additive, reversible) ·
**Code:** `app/modules/geo/` · **Tests:** `tests/test_geo.py` (23) ·
**Depends on:** [tenancy](../tenancy/README.md)

Not to be confused with **`app/modules/locations`**, the read-only Zoho *warehouse location*
mirror at `/api/zoho/locations`. That module records what Zoho said. This one owns addresses
for the whole platform, and projects each Zoho location into a usable place.

---

## 1. The shape

```
geo.places            THE canonical physical place — the only table storing coordinates
  ▲
  │ geo.place_links   any entity ↔ a place: the polymorphic address book
  │                   (owner_type + owner_id → place_id, typed, dated, optionally frozen)
  │ geo.geofences     zones with an entry / exit / dwell policy
  │ geo.place_relationships   place ↔ place, with metrics per transport mode
  │
geo.geocode_api_calls every external geo-API payload, stored once (cost, audit, licence)
geo.admin_boundaries  administrative reference areas — the only GLOBAL table here
```

**One place, many owners.** A customer, three of its invoices and a contact person at the same
site all point at one `places` row. The alternative — an address block copied onto every table
that needs one — is how the same warehouse ends up stored five times with five spellings, and
why "which of these is the real address" stops having an answer.

**Design Rule Zero.** A place has no owner, no "visited at", no telemetry. The moment it
carries `customer_id` it is no longer reusable. Ownership is a *link*, not a column.

## 2. The coordinate

`coordinates` (PostGIS `geography(Point,4326)`) is the only position stored. `latitude`,
`longitude` and `geohash8` are Postgres GENERATED columns; the application cannot write them,
so a point and its decimal copy can never drift apart.

`geohash8` (≈19 m cells) plus `ST_DWithin` give the **near-duplicate probe**: before writing a
new place, `create_place` looks for one within 25 m and returns that instead. Pass
`?reuse_duplicates=false` when two real doorways are genuinely that close.

Longitude comes first in WKT. The service builds every point, so no caller has to remember.

## 3. The address book — `geo.place_links`

Two things usually conflated, kept apart:

| Column | Means |
|---|---|
| `owner_type` + `owner_id` | **WHO** owns the address — the entity class and its id |
| `link_type` | **WHAT KIND** of address it is for them: billing, shipping, home, office, site, current, permanent, primary, other |

A single morph column carrying both is how `shipping` ends up as an entity class, and why
nobody can then answer "every billing address in this tenant". `owner_type` is a closed set
(`OWNER_TYPES` in `model/link.py`) with a CHECK constraint, so a typo is a failed write rather
than a row nobody finds again. Phase 6 adds `contact`, `invoice`, `estimate` … to that tuple.

### One link table, not two

The reference design this was built from splits effective-dated *postal addresses* from
operational *place links*. Here they are the same shape — owner, place, type, primary flag,
validity window — and two tables of that shape means every reader has to ask which one a
customer's billing address is in. The split earns its keep only where a personnel/KYC contract
differs from an operational one; this platform has no such contract, so the temporal machinery
lives on the one table and applies only where it is true.

### What the database guarantees

| Guarantee | How |
|---|---|
| one open **primary** per owner + link type | partial unique `uq_place_links_one_primary` |
| the same place is not attached twice for the same purpose | partial unique `uq_place_links_dedupe` (`purpose` is NOT NULL, default `''`, so it can key an index) |
| `current` / `permanent` addresses **never overlap in time** | EXCLUDE `place_links_no_overlap` (GiST + btree_gist) |
| a customer may hold ten shipping addresses | those types are simply not in `SINGLE_VALUED_LINKS` |
| an address of another tenant's organization is impossible | composite FK `(tenant_id, organization_id)` |

A new `current` address closes the one it supersedes (`valid_to`) instead of overwriting it —
that is the history. `GET /api/addresses/history` reads it back, closed and detached rows
included.

### Snapshots — the reason a document's address does not move

An invoice's billing address must read the same in five years even if the customer moves.
`POST /api/addresses` with `freeze: true` copies the postal block into `snapshot` at link time;
the live place keeps changing beside it. Frozen links refuse edits and detachment — they are
part of the record. Contacts link live; documents link frozen.

## 4. Verification

`is_verified` is the boolean everything filters on; `VerificationMixin` adds the nuance a
boolean cannot carry:

| Column | |
|---|---|
| `verification_status` | `unverified` · `geocoded_only` · `field_verified` · `disputed` |
| `verification_method` | `field_visit`, `utility_bill`, `otp`, `geocode` … |
| `verification_data` | the evidence: photo refs, provider response ids |
| `verified_by` / `verified_at` | who and when |

`geocoded_only` is the trap worth naming: a provider returning a point is not evidence that a
courier can find the door. **Moving a place's coordinates clears its verification** — whoever
stood at the old point did not vouch for the new one.

## 5. Provenance and cost — `geo.geocode_api_calls`

Every external geo-API response is stored once, keyed by
`(tenant_id, provider, api_type, request_hash)`:

* **cost** — a cache hit is a request nobody pays for;
* **audit** — "why is this customer pinned in the wrong district", answerable a year later
  against the exact bytes the provider returned;
* **licence** — Google permits caching geocode results for 30 days but `place_id` indefinitely.
  A per-row `expires_at` and one purge job over this table clears every raw payload in the
  platform; no other table needs to know the rule.

The cache is per tenant on purpose: a request hash contains the address that was looked up, so
a shared cache would leak one tenant's address book into another's lookups.

## 6. Tenancy — the new strict mixin

`MultiTenantMixin` (`app/database/mixins.py`) differs from `TenantScopedMixin` by one word:
`organization_id` is **NOT NULL**. With a nullable column the composite FK is MATCH SIMPLE and
a NULL organization skips the check; here every row is checked, and "tenant-wide" rows cannot
appear by accident. `OrgEntityMixin` is the full entity bundle on top of it.

The cost is that a caller with no organization bound would hit a raw IntegrityError, so
`service.require_organization` resolves it first:

1. the request's organization (`X-Organization-Id`, or the user's own);
2. else the tenant's single organization;
3. else a 422 naming the header — not a constraint violation.

`ondelete="CASCADE"` here versus RESTRICT on `TenantScopedMixin`: deleting a tenant is still
blocked by the RESTRICT tables, so in practice the cascade only fires for a tenant whose other
data is already gone.

## 7. Why `admin_boundaries` is GLOBAL

Maharashtra's boundary is not one tenant's data, and a district MULTIPOLYGON is measured in
megabytes — a per-tenant copy would multiply the largest rows in the database for no gain. It
joins `countries` and `timezones` in the allow-list of explained global tables
(`tests/test_tenancy.py`). Anything a tenant draws for itself — beats, territories, hub zones —
is a `Geofence`, which **is** tenant-scoped.

Its `path` is a materialized text path (`/india/maharashtra/pune/`) like
`org_management.organizations.hierarchy_path`, rather than `ltree`: one tree idiom in the
codebase beats two, and it needs no extra extension or custom SQLAlchemy type.

## 8. Zoho locations become places

`app/modules/locations/zoho/hooks.py::project_place` runs after every locations sync and
upserts a place with `zoho_id` set and `kind = 'warehouse'`. `location_name`, `is_primary` and
`parent_location_id` mirror the Zoho fields, so the warehouse hierarchy survives the trip
(`parent_location_id` stays NULL until the parent location itself syncs).

Zoho owns those columns (`ZOHO_OWNED_PLACE_FIELDS`): a PATCH touching them on a Zoho-linked
place is refused with a message pointing at Zoho, exactly like the organization rule. Fields
Zoho does not know about — `landmark`, `operating_hours`, `custom_attributes`, verification —
stay ours to edit. A Zoho-linked place is archived, never deleted: the next sync would
recreate it.

## 9. API

| Prefix | |
|---|---|
| `/api/locations` | places (**not** `/api/zoho/locations`, the Zoho mirror) |
| `/api/addresses` | the address book |
| `/api/geofences` | zones |
| `/api/admin-boundaries` | reference data for address forms |

| Route | Who | Notes |
|---|---|---|
| `GET /locations` · `/{ref}` | member | filters: `kind`, `status`, `q`, `postal_code`, `verified` |
| `GET /locations/nearby?latitude=&longitude=&radius_m=` | member | nearest first, GiST-served |
| `POST /locations` | member | `?reuse_duplicates=false` to force a new row |
| `PATCH /locations/{ref}` | member | `row_version` required → 409 on mismatch |
| `POST /locations/{ref}/verify` · `/archive` | member | |
| `DELETE /locations/{ref}?reason=` | tenant admin | leaves with no links only |
| `GET /locations/{ref}/addresses` | member | who uses this place — read before archiving |
| `GET|POST /locations/{ref}/relationships` | member | distance and bearing computed at write time |
| `GET /addresses?owner_type=&owner_id=` | member | `current_only=false` includes closed windows |
| `GET /addresses/history` | member | every window an owner has held |
| `POST /addresses` | member | `place` **or** `new_place`; `freeze` for documents |
| `PATCH /addresses/{ref}` · `/verify` · `DELETE` | member | frozen links refuse all three |
| `GET /geofences` · `/containing?latitude=&longitude=` | member | polygons and circles in one query |
| `POST|PATCH|DELETE /geofences` | tenant admin | |
| `GET /admin-boundaries` · `/resolve` | member | `POST` is tenant admin |

`{ref}` is a uuid (preferred) or the numeric id.

## 10. Deliberately not built yet

The reference design also carries a telemetry layer — `location_events`, `location_pings`,
`track_segments`, `user_live_locations`. It is **not** here, because every one of those tables
references `shifts`, `visits` or `route_stops`, none of which exist in this platform, and the
hypertables need TimescaleDB, which this stack does not run. Building them now would mean six
tables nothing can write to.

The address book stands on its own and is what Phase 6 (contacts, invoices, estimates) needs.
When field tracking arrives, `LocationEvent` hangs off `geo.places` and `geo.geofences`
unchanged — that is what the `dwell_threshold_s` policy on a fence is already for.

## 10b. Geocoding

Addresses become coordinates through a swappable provider layer —
**[geocoding.md](geocoding.md)**. Highlights:

* providers build requests and parse payloads; the service owns caching,
  retries, rate limiting, the circuit breaker, cost accounting and provenance;
* a fallback chain that falls through on failure *and* on an empty answer;
* `geo.geocode_api_calls` is the cache, the audit trail and the spend ledger;
* `POST /api/locations/{ref}/geocode` fills a place and marks it
  `geocoded_only` — never `is_verified`;
* **Valhalla is routing, not geocoding**; pair it with Pelias.

Straight-line maths with no provider and no dependency lives in
`app/modules/geo/distance.py` (haversine, bearing, destination, bounding box).

## 11. Open items

| # | Item |
|---|---|
| 1 | ~~A geocoding client~~ — done: [geocoding.md](geocoding.md), a provider layer over Google / Mapbox / Nominatim / Pelias plus Valhalla routing. No provider is configured by default |
| 2 | Seed `geo.admin_boundaries` from the LGD / Census datasets (use `requirements-geodata.txt`, not the service image) |
| 3 | Resolve `places.admin_boundary_id` on write once boundaries are seeded (`boundary_for_point` exists) |
| 4 | Add `contact`, `invoice`, `estimate` to `OWNER_TYPES` with Phase 6, and a CHECK migration |
| 5 | CDC/search: index `geo.places` in Meilisearch for address type-ahead (the trgm indexes serve SQL search today) |
| 6 | Telemetry layer, once shifts/visits exist (§10) |
