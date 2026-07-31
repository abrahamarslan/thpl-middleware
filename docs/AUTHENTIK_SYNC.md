# Authentik User Sync (app → Authentik)

How the local Postgres `users` table is mirrored into Authentik so Authentik can
serve as the central SSO / admin directory while the application keeps full
ownership of the user profile.

> **Source of truth:** the local `users` table. Authentik is a *mirror* of the
> credential-bearing subset. A failed sync never rolls back a local write.

---

## 1. Two directions, do not confuse them

| Direction | Purpose | Code | Trigger |
|---|---|---|---|
| **Inbound** (Authentik → app) | Validate Authentik OIDC tokens, JIT-provision an SSO user into `users` | `app/common/security/authentik.py` + `users/service.py::provision_from_authentik` | A request arrives with an Authentik RS256 bearer token |
| **Outbound** (app → Authentik) — *this document* | Replicate local user create/update/password/disable/delete into Authentik | `app/common/security/authentik_client.py` + `users/authentik_sync.py` + `app/tasks/authentik.py` | A first-party register / profile edit / password change / (de)activation / delete |

Both are gated by **separate** settings. Inbound is `AUTHENTIK_ENABLED`
(`AUTHENTIK_OIDC_*` in compose). Outbound is `AUTHENTIK_SYNC_ENABLED`
(`AUTHENTIK_*` admin settings).

---

## 2. Login model (Option A)

First-party login (`POST /api/auth/login`) verifies against the **local bcrypt
hash**, *not* Authentik. Consequences:

- The Authentik password is a convenience copy for native-Authentik / other-SSO
  logins. If it ever drifts, **app login is unaffected** — recoverable with a
  normal password reset.
- Therefore password sync is **best-effort**, not on the critical path. Plaintext
  passwords exist only inside the request, so password sync **cannot be retried by
  Celery**; on failure the row is flagged `password_drift` and the user simply
  resets later.

---

## 3. What gets synced

| Local `User` field | Authentik field | Notes |
|---|---|---|
| `username` (or `email` if null) | `username` | Authentik requires a unique, non-empty username |
| `first_name` + `last_name` (or `name`) | `name` | Authentik has a single `name` field |
| `email` | `email` | |
| `phone` | `attributes.phone` | stored in Authentik's free-form attributes |
| `is_deactivated` | `is_active` | inverted |
| password (plaintext, request scope) | `set_password` | best-effort, see §2 |
| — | `attributes.local_user_id` | written on create for cross-reference |

The set of local fields that trigger a profile push on update is
`AUTHENTIK_SYNCED_FIELDS` in `users/authentik_sync.py`.

### ID mapping

| Column | Holds | Used for |
|---|---|---|
| `users.authentik_pk` | Authentik admin-API user **pk** | addressing every update / set_password / delete call |
| `users.external_id` | Authentik **uuid** (back-filled on create if empty) | the inbound OIDC link — matches `sub` when the OIDC provider's *subject mode* is **"Based on the User's UUID"** |

> Set the Authentik OIDC provider's subject mode to **UUID** so the inbound and
> outbound links agree.

---

## 4. Lifecycle → action map

| Service call | Authentik action | On failure |
|---|---|---|
| `register()` / `create_user()` | create user + set password, store `authentik_pk`/`external_id` | enqueue `provision_user` task |
| `change_password()` / `reset_password()` | `set_password` | flag `password_drift` (no retry — no plaintext) |
| `update_user()` (synced field changed) | `PATCH` profile | enqueue `sync_profile` task |
| `delete_user(hard=False)` | `PATCH is_active=false` | enqueue `sync_status` task |
| `restore_user()` | `PATCH is_active=true` | enqueue `sync_status` task |
| `delete_user(hard=True)` | `DELETE` (idempotent; 404 = ok) | enqueue `delete_user` task |

`authentik_sync_status` per row: `pending → synced` (or `failed` /
`password_drift` / `skipped` when `AUTHENTIK_SYNC_ENABLED=false`).

---

## 5. Resilience

- **Inline best-effort first.** The request path calls Authentik directly (we need
  the returned `pk` on create, and the plaintext on password ops).
- **Celery retry net.** Non-password failures enqueue a task in `app/tasks/authentik.py`
  (queue `default`, exponential backoff, max 5 retries). Because the stack is
  asyncpg-only, these synchronous tasks drive the async client via `asyncio.run`
  with a throwaway `NullPool` engine and a fresh `AuthentikAdminClient` per run.
- **Commit race.** A retry task may fire before the request transaction commits;
  it returns "not found" and self-retries until the row is visible.

---

## 6. One-time Authentik setup

1. **Service account** — Admin → Directory → Users → *Create Service Account*
   (e.g. `core-platform-sync`).
2. **API token** — open that user → *Tokens* → create an API token → copy it →
   set `AUTHENTIK_SERVICE_TOKEN`.
3. **Permissions** — grant the service account the *Core: Can create / change /
   delete User* and *Can reset User's password* permissions (System → Permissions,
   or add it to a group that has them).
4. **Base URL** — `AUTHENTIK_BASE_URL=http://authentik-server:9000` (internal;
   the backend and workers already share a Docker network with it). For bare-metal
   local dev use the host-published port (`http://localhost:9010`).
5. **OIDC subject mode** — set the provider's subject mode to **UUID** (§3).
6. Flip `AUTHENTIK_SYNC_ENABLED=true` and redeploy.

The token is sent as `Authorization: Bearer <token>` against `/api/v3/core/users/`.

---

## 7. Migrating existing users

Existing rows have no `authentik_pk`. Backfill links them by email (or creates
them with a random password + `password_drift`):

```bash
./manage.sh authentik-backfill          # runs synchronously in the backend container
# or enqueue on the worker:
docker compose exec backend python -c "from app.tasks.authentik import backfill; backfill.delay()"
```

Re-running is safe (already-linked rows are skipped).

---

## 8. Operations

```sql
-- Rows needing attention
SELECT id, email, authentik_sync_status, authentik_sync_error, authentik_synced_at
FROM users
WHERE authentik_sync_status IN ('failed', 'password_drift', 'pending')
ORDER BY updated_at DESC;
```

- `failed` → a retry task should be flying; check Flower (`/flower`) and the
  `app.tasks.authentik` logs in Loki.
- `password_drift` → ask the user to run forgot-password (resyncs the password),
  or it self-heals on their next `change_password`.
- Metrics/logs: structured events `authentik_admin_call`, `authentik_user_synced`,
  `authentik_*_failed` flow to Loki; task throughput appears in the celery-exporter.

---

## 9. Files

| File | Role |
|---|---|
| `app/core/conf.py` | `AUTHENTIK_SYNC_ENABLED`, `AUTHENTIK_BASE_URL`, `AUTHENTIK_SERVICE_TOKEN`, `AUTHENTIK_TIMEOUT_SECONDS`, `AUTHENTIK_USER_PATH`, `AUTHENTIK_USER_TYPE` |
| `app/common/security/authentik_client.py` | async admin API client + `AuthentikError` |
| `app/modules/users/authentik_sync.py` | orchestration: `sync_create/update_profile/set_password/set_active/delete`, field mapping, `SyncResult` |
| `app/modules/users/service.py` | calls the sync layer after each local write |
| `app/tasks/authentik.py` | Celery retry tasks + `backfill` |
| `app/modules/users/model.py` | `authentik_pk`, `authentik_sync_status`, `authentik_sync_error`, `authentik_synced_at` |
| `alembic/versions/*_add_authentik_sync_columns.py` | schema migration |
