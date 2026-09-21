# Geocoding, reverse geocoding and routing

**Status:** ✅ live (no provider configured by default) · **Code:** `app/modules/geo/geocoding/` ·
**Tests:** `tests/test_geocoding_providers.py` (17), `tests/test_geocoding_service.py` (16),
`tests/test_geo_distance.py` (11) · **Storage:** `geo.geocode_api_calls` ·
**Parent:** [the location hub](README.md)

---

## 1. The one rule

**A provider builds requests and parses responses. It never makes an HTTP call.**

```
GeocodingProvider          service.py
──────────────────         ─────────────────────────────────────────────
build_forward(query)  ──▶  cache lookup → breaker → rate limit → HTTP
                           → record the call → parse ──┐
parse(payload)        ◀────────────────────────────────┘
                           → results, or fall through to the next provider
```

Everything a provider would otherwise have to remember — timeouts, retries, the
rate limit, the circuit breaker, caching, the licence window, cost accounting,
the audit row — lives in the service, written once. Three things follow:

* **providers are pure functions.** Every parser test runs against a saved
  payload with no network and no HTTP mocking. `tests/test_geocoding_providers.py`
  feeds the same Pune address to all four and asserts they produce the same
  columns — which is the only way to notice that one of them quietly drops the
  district.
* **a new provider inherits the operational behaviour by existing.** It cannot
  forget the breaker, because the breaker is not its code.
* **swapping providers is configuration**, not a migration of every caller.

## 2. Configuration

```ini
GEOCODING_ENABLED=false            # nothing calls out until this is true
GEOCODING_PROVIDER=google          # the primary
GEOCODING_FALLBACK_PROVIDERS=nominatim
ROUTING_PROVIDER=valhalla          # "" = straight-line distances, computed locally
```

Full list in `.env.example`. `GET /api/geocoding/providers` reports what is
configured, which settings are missing (by **name**, never value), each
provider's cost and cache window, and whether its circuit is open.

Disabled by default on purpose: no deployment should start making paid
third-party calls because a key happened to be present in the environment.

## 3. Providers

| Provider | Role | Needs | Licence cache | Notes |
|---|---|---|---|---|
| `google` | geocoding | `GOOGLE_MAPS_API_KEY` | 30 days | best Indian coverage; paid |
| `mapbox` | geocoding | `MAPBOX_ACCESS_TOKEN` | 30 days | v6 by default; v5 via `GEOCODING_MAPBOX_BASE_URL` |
| `nominatim` | geocoding | `GEOCODING_NOMINATIM_USER_AGENT` | operator's | free; **~1 req/s, no bulk use** on the public instance |
| `pelias` | geocoding | `GEOCODING_PELIAS_BASE_URL` | operator's | self-hosted; the geocoder that pairs with Valhalla |
| `valhalla` | **routing** | `ROUTING_VALHALLA_BASE_URL` | — | self-hosted `/sources_to_targets` |
| `google` / `mapbox` | routing | as above | — | Distance Matrix |
| `haversine` | routing | nothing | — | the offline floor; always available |

### Valhalla cannot geocode

Worth stating plainly, because it is the one thing about this list that
surprises people. **Valhalla is a routing engine over the OSM graph.** It has
no address database; its `/locate` snaps a coordinate to the nearest road,
which is not the question "where is 12 MG Road". Its geocoding counterpart is
**Pelias** — the two came out of Mapzen and are normally deployed together.

So the fully self-hosted, zero-third-party configuration is:

```ini
GEOCODING_PROVIDER=pelias
GEOCODING_PELIAS_BASE_URL=http://pelias:4000
ROUTING_PROVIDER=valhalla
ROUTING_VALHALLA_BASE_URL=http://valhalla:8002
```

### The fallback chain

Not redundancy theatre. Upstreams fail in ways invisible from here: a key hits
its daily cap at 4pm, a self-hosted Pelias is mid-redeploy, Google returns
`ZERO_RESULTS` for an address Nominatim knows because OSM covers that district
better. The chain falls through on **failure and on an empty answer**, costs one
extra call on the unhappy path, and turns an outage into a slower answer.

Unconfigured providers are dropped from the chain rather than raising, so a
chain can be named once and keys enabled over time.

## 4. What every provider is translated into

`AddressComponents` keys are exactly the writable columns of `geo.places`, so a
result applies to a place with no second mapping step. Google says
`administrative_area_level_2`, Mapbox says `context.district`, Nominatim says
`state_district`; all three mean `district`.

Two details that are easy to get wrong and are handled once, per provider:

* **the house number is rejoined to the street.** Every provider keeps them
  apart, in a different place. A `street` column holding "Mahatma Gandhi Road"
  without the 12 is not an address.
* **confidence is normalized to 0–1.** Google's `location_type` (ROOFTOP →
  1.0, APPROXIMATE → 0.4), Mapbox's `match_code.confidence` grades, Pelias's
  own fraction. Nominatim's `importance` is deliberately treated as a weak
  signal: it ranks *prominence*, not match quality — a famous landmark scores
  high for a vague query.

## 5. `geo.geocode_api_calls` — cache, audit trail and spend ledger

One table, three jobs, because separating them means three writes and three
chances to disagree about what happened. Every call is recorded: the hits, the
empties and the failures.

What is **servable** and what is merely **recorded** is decided by `expires_at`:

| Outcome | `expires_at` | Served again? |
|---|---|---|
| results | provider licence window (Google 30 days) | yes |
| `ZERO_RESULTS` | +24 h | yes — an address that does not exist today will not exist in an hour, and rediscovering that on every retry is how a bill grows |
| failure / rejection | already in the past | **never**, but visible in the audit trail |

**The cache key is the query's identity, not the built request.** Rounding and
whitespace normalization live in `GeoQuery.normalized()` /
`ReverseQuery.normalized()` — a reverse geocode is rounded to ~11 m, so two
fixes from the same doorway hit one entry instead of warming nothing. A
provider's `cache_variant` (Mapbox v5 vs v6) is part of the key, so a payload
written by one shape is never parsed as the other.

**The cache is per tenant, deliberately.** A request hash contains the address
someone searched for; a shared cache would leak one tenant's address book into
another's lookups.

**Credentials never land in it.** `cache_params` is what gets hashed and
stored, and providers keep keys out of it; `cache._scrub` is the second wall
for a future provider that forgets. Asserted in
`test_an_api_key_is_never_written_to_the_audit_table`.

**Purging.** `POST /api/geocoding/purge` (or `cache.purge_expired`) sweeps
payloads past their window. One sweep clears every raw provider response in the
platform, because this is the only table holding one — which is the whole
reason the raw payload lives in exactly one place.

## 6. Resilience

| Guard | Behaviour |
|---|---|
| timeout | `GEOCODING_TIMEOUT_SECONDS` read, `..._CONNECT_...` connect |
| retry | `GEOCODING_MAX_ATTEMPTS` on timeouts, transport errors and 408/425/429/5xx, with linear backoff |
| rate limit | fixed-window counter per provider per minute; a provider's own published policy is a **ceiling local config cannot raise** |
| circuit breaker | N consecutive transient failures open it for the recovery window; the Redis key's TTL is the cool-down |

**Fails open.** Redis backs the limiter and the breaker; if Redis is down,
geocoding keeps working without them. The Zoho governor is fail-*closed*
because exceeding Zoho's quota blocks the whole organization — a geocoding
overrun costs money, not availability, so the trade-off runs the other way.

A 4xx that is not 408/425/429 is a `ProviderRejected`: the request or the
account is wrong, retrying is pointless, and it does **not** count towards the
breaker — the provider is plainly answering.

### The Google trap

Google answers `200 OK` with `status: REQUEST_DENIED` and an `error_message`
when the key is wrong, unreferered or unbilled. Trusting the HTTP status turns
a broken key into "no results found", silently, for as long as nobody checks.
`check_payload` inspects the body; `OVER_QUERY_LIMIT` (per-second throttling)
is retryable while `OVER_DAILY_LIMIT` (the account is out) is not.

## 7. API

| Route | Who | |
|---|---|---|
| `POST /api/geocoding/forward` | member | address text → coordinates |
| `POST /api/geocoding/reverse` | member | coordinates → address |
| `POST /api/geocoding/route` | member | distance + duration between two points |
| `GET /api/geocoding/providers` | member | configured, missing settings, circuit state |
| `POST /api/geocoding/providers/{name}/reset` | tenant admin | close a tripped circuit early |
| `POST /api/geocoding/purge` | tenant admin | drop payloads past their licence window |
| `POST /api/locations/{ref}/geocode` | member | fill a place's coordinates from its postal fields |
| `POST /api/locations/{ref}/reverse-geocode` | member | fill a place's postal fields from its coordinates |

**POST, not GET, for the lookups.** An address typed into a search box is
personal data, and query strings end up in access logs, proxy caches and
browser history. The body does not.

Every response carries `provider`, `cached`, `call_id`, `providers_tried` and
`errors`, so a caller can see whether a bill was incurred and why a provider
was skipped. The provider's raw payload is never echoed — it is held once,
under its licence, in `geo.geocode_api_calls`.

### Geocoding a place

`POST /api/locations/{ref}/geocode` sets `verification_status` to
`geocoded_only` and leaves `is_verified` **false**. A provider returning a
point is not evidence a courier can find the door; only
`POST /api/locations/{ref}/verify` claims that.

On a **Zoho-linked place** only the position and the provenance are written —
Zoho owns the address lines (`ZOHO_OWNED_PLACE_FIELDS`), so a geocode can never
fight the next sync.

If another place already holds the returned `provider_place_id`
(`uq_places_provider_place_live`), the id is conceded rather than the geocode
failing: the coordinates are still written and
`geo.geocoding.duplicate_provider_place` is logged with both place ids. Two of
our places are the same doorway — worth knowing, not worth a 500.

## 8. Distances without a provider

`app/modules/geo/distance.py` is the haversine utility: `haversine`,
`distance_m`, `bearing`, `destination`, `bounding_box`, `within`, and the
`Unit` / `Direction` vocabulary. No dependency — it is forty lines of
trigonometry, and a dependency is a supply chain.

**PostGIS remains the authority.** It owns stored geometry, the GiST indexes
and every query that filters or sorts by distance. Use this module only when
there is no round trip to spend: validating input before a write, scoring
candidates already in memory, or the routing floor. Asking the database for the
distance between two numbers you are already holding is a network hop for
arithmetic.

**Accuracy:** the formula assumes a sphere, so it is off by up to ~0.5% against
WGS84. Immaterial for "is this the same doorway" (25 m) and for a straight-line
estimate; not good enough for billing by distance or legal boundaries — those
go to `ST_Distance` on geography, which is ellipsoidal.

With no `ROUTING_PROVIDER`, `POST /api/geocoding/route` answers with the
great-circle distance and a **null duration**. Never a travel time nobody
measured; `provider: "haversine"` says exactly what was returned. A routing
provider that fails falls back to the same floor rather than erroring.

## 9. Why not geopy, and why not geopandas

**geopy** — no. It is a client wrapper around ~50 geocoders, which is the layer
built here minus everything that makes it operable: no tenant-scoped cache, no
provenance, no cost ledger, no breaker, no normalization into our columns. It
would be wrapped on day one. Two harder blockers: its async adapter needs
`aiohttp`, which this project deliberately removed (`requirements.txt`: "single
client; aiohttp removed"), and it has no Valhalla support. Its `distance`
module is the only genuinely useful part, and PostGIS plus
`app/modules/geo/distance.py` already cover it.

**geopandas** — not in the service image; see `requirements-geodata.txt`. It
pulls pandas, pyproj and GDAL (hundreds of megabytes) for code no request path
executes, it is synchronous and CPU-bound so a DataFrame operation inside a
handler blocks the event loop for every other request on that worker, and it
duplicates what PostGIS already does against indexes on the data's own side of
the network. It **is** the right tool for the offline boundary import
(README §11 item 2), which is why the file exists — installed into a throwaway
environment, never the app venv. In-process geometry uses shapely, already a
runtime dependency via geoalchemy2.

## 10. Adding a provider

```python
class MyGeocoder(GeocodingProvider):
    name = "mine"
    requires = ("MY_API_KEY",)
    cache_days = 30

    def build_forward(self, query):  return ProviderRequest(url=..., params=..., cache_params=...)
    def build_reverse(self, query):  ...
    def parse(self, payload, api_type): return [GeocodeResult(...)]
```

List it in `providers/__init__.py`, or call `registry.register_geocoder(cls)` at
startup for an out-of-tree one. Keep the API key in `params`/`headers` and out
of `cache_params`. Nothing else changes.

## 11. Open items

| # | Item |
|---|---|
| 1 | Provider parsers are written from published API shapes and tested against saved payloads; none has been run against a live key yet |
| 2 | Batch geocoding (a Celery lane that geocodes un-geocoded places within the rate limit) |
| 3 | Autocomplete / typeahead (`PLACE_AUTOCOMPLETE` is in the enum; session tokens matter for Google's billing) |
| 4 | Wire `place_relationships` distance/duration to `route_matrix` on write (currently PostGIS `ST_Distance`) |
| 5 | Resolve `places.admin_boundary_id` from a geocode once `geo.admin_boundaries` is seeded |
| 6 | Per-tenant provider keys (today one set per deployment, like the Zoho connection) |
