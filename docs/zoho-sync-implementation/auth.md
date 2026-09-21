# Token manager v2 & credential storage

**Status:** ✅ built and **live** · **Code:** `app/modules/zoho/core/auth.py`,
model `ZohoOAuthCredential` in `app/modules/zoho/model.py`, migration
`alembic/versions/20260918_0900_c3d4e5f6a7b8_zoho_oauth_credentials.py`,
OTel URL scrubbing in `app/core/observability.py` ·
**Tests:** `tests/zoho_core/test_auth.py` (12), `tests/zoho_core/test_url_scrubbing.py` (4)

---

## 1. Purpose

Hand every process one valid Zoho access token, refresh it **exactly once per
fleet**, and keep the refresh token — the long-lived credential — out of every
place it leaked to in v1.

Zoho's limits (`docs/zoho-docs-md/oauth-zoho.md`) make this coordination, not
caching:

| Zoho rule | Consequence |
|---|---|
| access token lives 1 h | refresh with a margin (`ZOHO_TOKEN_REFRESH_MARGIN`, 120 s) |
| ≤ 10 access tokens per refresh token per 10 min → "Access Denied" | single-flight refresh + a throttle guard at 8 |
| ≤ 15 active access tokens; the 16th invalidates the oldest | a stampede breaks tokens *in use*, not just wastes calls |
| refresh token deleted on revoke / password change | must be detected (`invalid_code`) and stop the engine |
| token endpoint takes secrets **in the query string** | span URLs must be scrubbed |

---

## 2. What changed from v1

| # | v1 (`token_manager.py`, deleted) | v2 |
|---|---|---|
| 1 | lock released with `DEL` — a slow refresher could delete the next holder's lock | owner token + Lua compare-and-delete |
| 2 | lock TTL 30 s = refresh timeout → lock could lapse mid-refresh | TTL = `ZOHO_TIMEOUT_SECONDS + 15` |
| 3 | `invalidate()` deleted whatever was cached → a late 401 evicted a *fresh* token | `invalidate(token)` deletes only if the cache still holds that token |
| 4 | refresh token stored via `system_settings_service.set_setting` → plaintext in `setting_values` **and** `setting_audit_logs` | encrypted row in `zoho_oauth_credentials`; the migration **deletes** the old rows and their audit entries |
| 5 | refresh token cached in Redis (`zoho:refresh_token`) with no TTL under `allkeys-lru` | never in Redis; in-process cache (5 min) only |
| 6 | Celery sync client refreshed from `ZOHO_REFRESH_TOKEN` only | one manager for every process |
| 7 | revoked token = generic auth error | `ZohoAuthRevokedError` (category `AUTH_REVOKED`, CRITICAL log) |
| 8 | OTel httpx spans recorded `client_secret`, `refresh_token`, `code` | request hook scrubs span URLs |

---

## 3. How it works

### 3.1 `get_token()`

```
cached in Redis (zoho:oauth:{org}:access)? ──yes──► return
         │ no (legacy zoho:access_token also read once, never written)
SET zoho:oauth:{org}:refresh_lock <owner> NX PX (timeout+15 s)
   ├─ lost  → poll the cache every 0.25–0.4 s (jittered) up to 20 s → token or ZohoAuthError
   └─ won   → re-check cache → _refresh() → cache token (TTL = expires_in − margin)
              → release lock with compare-and-delete(owner)
```

`_refresh()`:

1. load the refresh token from the `CredentialStore`;
2. `INCR zoho:oauth:{org}:refresh_count` (EX 600) — above 8 → `ZohoAuthThrottledError` (CRITICAL: indicates a caching bug);
3. POST the token endpoint (query params as Zoho requires);
4. `invalid_code` / `invalid_grant` / `invalid_client` → `ZohoAuthRevokedError`;
5. validate `api_domain` against the configured base URLs (Multi-DC mix-up → ERROR log);
6. persist a rotated refresh token if Zoho returned one.

If Redis is down the manager refreshes without coordination and keeps the
token in process memory until expiry — degraded, never blocked.

### 3.2 `CredentialStore`

| Source (in order) | When |
|---|---|
| `zoho_oauth_credentials` row, `pgp_sym_decrypt(refresh_token_enc, key)` | `ZOHO_TOKEN_PERSISTENCE_ENABLED=true` **and** `ZOHO_TOKEN_ENCRYPTION_KEY` set |
| `ZOHO_REFRESH_TOKEN` env | bootstrap seed / persistence disabled |
| neither | `CredentialUnavailable` ("connect the integration") |

Writes (`store()`): upsert by `org_id`, `credential_version + 1`, `rotated_at`,
`rotated_by` (operator user id), `api_domain`, `scope`. Without an encryption
key the store **refuses to write** (logs `zoho.auth.credential_not_persisted`)
and keeps the token in memory — never plaintext at rest.

`revoke()` nulls the ciphertext and sets `revoked_at`.

### 3.3 Table `zoho_oauth_credentials`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint PK | |
| `org_id` | varchar(64) | unique index |
| `refresh_token_enc` | bytea | `pgp_sym_encrypt(token, ZOHO_TOKEN_ENCRYPTION_KEY)` |
| `api_domain` | varchar(255) | from Zoho's token response |
| `scope` | varchar(1024) | granted scopes |
| `credential_version` | int | increments per rotation |
| `rotated_at`, `rotated_by` | timestamptz, bigint | who reconnected, when |
| `revoked_at` | timestamptz | set on disconnect |
| `created_at`, `updated_at` | timestamptz | |

Not in Debezium's include list and never to be added.

---

## 4. Configuration

| Setting | Default | Meaning |
|---|---|---|
| `ZOHO_TOKEN_PERSISTENCE_ENABLED` | `false` | store the refresh token in Postgres |
| `ZOHO_TOKEN_ENCRYPTION_KEY` | `""` | **new** — required for persistence; keep in `.env` only, quote it |
| `ZOHO_REFRESH_TOKEN` | `""` | bootstrap seed |
| `ZOHO_TOKEN_REFRESH_MARGIN` | 120 | seconds subtracted from `expires_in` |
| `ZOHO_ACCESS_TOKEN_URL` | `https://accounts.zoho.in/oauth/v2/token` | token endpoint |
| `ZOHO_TIMEOUT_SECONDS` | 30 | refresh HTTP timeout (lock TTL derives from it) |

**Production rollout (WSL Docker stack):**

1. Generate a key: `openssl rand -base64 48`; add to `deployment/.env.prod` as
   `ZOHO_TOKEN_ENCRYPTION_KEY="…"` (quoted — shell scripts source the file) and
   set `ZOHO_TOKEN_PERSISTENCE_ENABLED=true`. Both are already passed through
   the `x-backend-env` anchor in `deployment/docker-compose.yml` and listed in
   `.env.example` / `.env.prod.example`.
2. Recreate the backend and worker containers so they pick up the variables.
3. `alembic upgrade head` (the backend container runs it on deploy).
4. Reconnect once via `/api/zoho/auth/initiate` — the old plaintext value was
   deleted by the migration on purpose, so the secret is rotated rather than
   copied.
5. Losing the key = losing the stored token: reconnect again. Rotating the key
   = reconnect after changing it.

### 4.1 Redis keys (DB 0)

| Key | TTL | Content |
|---|---|---|
| `zoho:oauth:{org}:access` | `expires_in − margin` | access token |
| `zoho:oauth:{org}:refresh_lock` | timeout + 15 s | lock owner id |
| `zoho:oauth:{org}:refresh_count` | 600 s | refreshes in the window |
| `zoho:access_token` (legacy) | — | read once for zero-downtime deploy; never written |

---

## 5. Event loops & Celery

Since Phase 5 every worker process runs its tasks on one long-lived loop
([`worker-event-loop.md`](worker-event-loop.md)), so `CredentialStore` uses the
module-level pooled `async_session_factory` everywhere, exactly as in the API.
`bind_session_factory` remains only for tests that inject their own engine.
(History: E06.)

---

## 5b. Connecting Zoho (OAuth consent) — the two URLs

| Setting | What it is | Example (dev) |
|---|---|---|
| `ZOHO_REDIRECT_URL` | Zoho's `redirect_uri` = **our callback**. Must match the Zoho API console entry exactly | `https://app.local/api/zoho/auth/callback` |
| `ZOHO_AUTH_RETURN_URL` | where the **browser** lands after a successful connect (a frontend page). Empty = the callback answers `{"connected": true, "persisted": true}` | `https://app.local/settings/integrations` or empty |
| `ZOHO_AUTH_RETURN_HOSTS` | extra hosts `?return_url=` may point to (FRONTEND_URL / callback / return hosts are always allowed) | empty |

Flow (Swagger or browser):

1. `GET /api/zoho/auth/initiate?redirect=false` → `data.authorization_url`
   (leave `return_url` empty unless you want a specific page).
   It is **refused with 409 `zoho_token_storage_not_configured`** until
   `ZOHO_TOKEN_PERSISTENCE_ENABLED=true` and `ZOHO_TOKEN_ENCRYPTION_KEY` are set.
   Without them the refresh token from the consent would live only in that
   API process's memory for ~5 minutes and never reach the workers (E32).
2. Open the URL, then log in to Zoho and consent.
3. Zoho redirects to `/callback?code=…&state=…`. The state is checked (one use,
   10 min), the code is exchanged, the refresh token is stored **encrypted** in
   `zoho_oauth_credentials`, and an auth pause is lifted. Then the callback
   answers JSON or redirects to the return URL.
4. Check with `GET /api/zoho/auth/status` → `is_connected: true`, or
   `python -m app.modules.zoho.cli check --live`.

| Callback answer | Meaning |
|---|---|
| 200 `{"connected": true, "persisted": true}` | connected (no return URL configured) |
| 307 → return URL | connected |
| 400 `zoho_consent_failed` "Zoho did not grant access: access_denied" | the consent was declined or failed at Zoho |
| 400 `zoho_consent_failed` "This is Zoho's OAuth callback…" | the URL was opened without `code`/`state`. Harmless, **not** a failed connect (E31) |
| 401 invalid/expired state | older than 10 min, already used, or not started by `/initiate` |
| 400 `return_url_not_allowed` (at `/initiate`) | the `return_url` points to a foreign host (open-redirect protection) |

---

## 5c. Can we sync right now? — `GET /api/zoho/auth/connection`

A bare sample request has three problems:
* it spends quota on every call;
* it cannot say *why* syncing won't happen;
* `GET /organizations` succeeds even with a wrong org id (E35).

The report (`app/modules/zoho/core/connection.py`) combines:

| Check | Cost |
|---|---|
| configuration (client id/secret, org id, redirect URL) | free |
| stored credential (encrypted DB vs env) | free |
| cached access token | free |
| engine switches (auth pause, engine pause, pull, paused modules) | free |
| today's quota / governor state | free |
| circuit breakers | free |
| last successful and last failed real Zoho call (recorded by the transport) | free |
| **live probe** `GET /organizations/{ZOHO_ORGANIZATION_ID}` (org-scoped, INTERACTIVE) | 1 call, only when needed |

| `probe=` | Behaviour |
|---|---|
| `auto` (default) | probe only if no success within `ZOHO_CONNECTION_PROBE_AFTER_SECONDS` (900) or the last call failed |
| `always` | force it; single-flighted and cached `ZOHO_CONNECTION_PROBE_CACHE_SECONDS` (60) |
| `never` | local checks only (dashboards) |

The answer is `{can_sync, state, summary, organization, checks[], last_success, last_error, probed}`,
where `state` is one of:
* `connected`;
* `degraded` (warnings);
* `not_connected` (no credential);
* `misconfigured` (config, or 6041 wrong org);
* `blocked` (switch or quota).

`python -m app.modules.zoho.cli check [--live]` prints the same report.

---

## 6. OTel URL scrubbing (`app/core/observability.py`)

`HTTPXClientInstrumentor().instrument(request_hook=…, async_request_hook=…)`
overwrites `http.url` and `url.full` on every httpx span:

| URL | Recorded as |
|---|---|
| `https://accounts.zoho.in/oauth/v2/token?refresh_token=…&client_secret=…` | `https://accounts.zoho.in/oauth/v2/token` (query dropped) |
| any host with `client_secret, refresh_token, code, token, access_token, password, api_key` params | those values → `REDACTED` |
| `https://www.zohoapis.in/books/v3/invoices?organization_id=…&page=2` | unchanged |

---

## 7. Operations

| Symptom | Meaning | Action |
|---|---|---|
| `zoho.auth.refresh_revoked` (CRITICAL) | refresh token deleted/revoked in Zoho | reconnect via `/api/zoho/auth/initiate` |
| `zoho.auth.refresh_throttled` (CRITICAL) | > 8 refreshes in 10 min | a caching bug — check Redis health/evictions; do not keep retrying (Zoho locks the client) |
| `zoho.auth.api_domain_mismatch` (ERROR) | token minted in another data centre | fix `ZOHO_ACCOUNTS_URL`/base URLs |
| `zoho.auth.credential_not_persisted` (WARNING) | persistence disabled or key missing (now prevented up front: `/initiate` answers 409) | set `ZOHO_TOKEN_PERSISTENCE_ENABLED` + `ZOHO_TOKEN_ENCRYPTION_KEY`, reconnect |
| `zoho_oauth_return_url_is_callback` (WARNING) | someone passed the callback URL as `return_url` | ignored automatically (E31) |
| `CredentialUnavailable` | no token anywhere | connect the integration |

`GET /api/zoho/auth/status` still reports `is_connected`; `health()` returns
`token_ttl_seconds, has_token, refreshes_in_window, credential_source,
db_persistence, redis_healthy` for the admin API (Phase 4).

---

## 8. Open items

| # | Item | When |
|---|---|---|
| 1 | ~~Pass `ZOHO_TOKEN_ENCRYPTION_KEY` / `ZOHO_TOKEN_PERSISTENCE_ENABLED` through compose~~ | ✅ done 2026‑09‑18 (with the governor variables) |
| 2 | Engine auth-pause switch on `ZohoAuthRevokedError` | Phase 4 switches |
| 3 | `zoho_token_ttl_seconds` / `zoho_token_refresh_total` metrics | Phase 4 metrics |
| 4 | Remove the legacy `zoho:access_token` read after one release | next release |
