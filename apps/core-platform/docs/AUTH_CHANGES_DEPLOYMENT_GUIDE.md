# Auth Release — Deploy to the GCP VM

**Companion to:** [`GCP_VM_PRODUCTION_DEPLOYMENT.md`](./GCP_VM_PRODUCTION_DEPLOYMENT.md)
**Domain:** `dlp.tarrinahealth.com` · **VM:** `dlp-prod` (`asia-south1-a`)
**Applies to:** the authentication release — Resend email layer, password
policy, password reset (identifier + 4-digit code/link), passwordless OTP login,
GeoIP request audit, user moderation (ban/throttle), enterprise auth audit
logging, logout, and the failed-auth persistence fix.

This guide is the delta you apply **on top of an already-running deployment**.
It tells you exactly what to push, pull, rebuild, migrate and verify.

---

## 0. What changed (at a glance)

| Area | Change | Action needed |
|---|---|---|
| Backend code | `app/modules/users/**`, `app/modules/emails/**`, `app/common/geoip.py`, `app/common/client_info.py`, `app/middleware/context.py` | **Rebuild backend image** |
| New Python dependency | `geoip2>=4.8` in `requirements.txt` | **Rebuild** (restart is not enough) |
| New DB tables/columns | `login_otp_tokens`; moderation columns on `users`; email provenance + hardened reset columns | **Run migrations** |
| GeoIP database | `config/geoip/*.mmdb` (git-ignored) + `GEOIP_*` env + volume mount | **Copy DBs to VM + set env** |
| Email (Resend) | `EMAIL_*` / `RESEND_*` env, brand values, `FRONTEND_URL` | **Set env** |
| Debezium | `table.include.list` now includes `email_events`, `email_links` | **Re-register connector** |
| Auth audit logging | Uses the existing `activity_logs` table | **No migration** |
| Compose | backend gains `./config/geoip:/app/geoip:ro` mount | Applied by the pulled file |
| Frontend | no change | no rebuild required |

**Migrations to apply (in order):**

| Revision | What |
|---|---|
| `b7c1f2a9d4e0` | emails provenance (`actor_id`/`source_ip`/`request_id`/`user_agent`), `ix_emails_created_at`, hardened `password_reset_tokens` (`code_hash`, attempts, expiry, cooldowns) |
| `d2e3f4a5b6c7` | `login_otp_tokens` table |
| `e5f6a7b8c9d0` | `users` moderation columns (`is_banned`/`*_until`/`is_throttled`/…) + indexes |

> **No migration** is needed for auth audit logging — it reuses the existing
> append-only `activity_logs` table.

---

## 1. Push from your local machine

Run locally (repo root `~/th-middleware`):

```bash
cd ~/th-middleware

# 1. Review exactly what will ship.
git status
git diff --stat

# 2. Run the test suite locally before pushing (needs the scratch DB/Redis).
#    See apps/core-platform/backend/tests/conftest.py for the docker run commands.
cd apps/core-platform/backend
.venv/bin/python -m pytest -q
cd ~/th-middleware

# 3. Commit.
git switch main
git pull --ff-only origin main
git add -A
git commit -m "feat(auth): resend email layer, password reset + OTP login, geoip, moderation, audit logging"

# 4. Push.
git push origin main
```

**If your branch is protected**, push a feature branch and open a PR instead:

```bash
git switch -c feat/auth-release
git add -A && git commit -m "feat(auth): auth release"
git push -u origin feat/auth-release
gh pr create --fill --base main
# merge after review, then on the VM pull main
```

> The `config/geoip/*.mmdb` files are **git-ignored** and are *not* pushed —
> you transfer them to the VM separately in §3.

---

## 2. Pull on the GCP VM

```bash
gcloud compute ssh dlp-prod --zone=asia-south1-a --tunnel-through-iap

cd ~/th-middleware
git fetch origin
git switch main
git pull --ff-only origin main
```

You should now see the new migrations, the auth modules, and the updated
`deployment/docker-compose.yml` / `config/debezium/zoho-mirror-connector.json`.

---

## 3. Copy the MaxMind GeoIP databases (git-ignored — easy to miss)

The `.mmdb` files exist only on your laptop; the VM's `config/geoip/` will
contain just the committed `README.md`/`.gitkeep`. Copy the three files
(requires Cloud SDK + IAP access from your laptop):

```bash
# Run on your LAPTOP, from the repo root:
GEO_SRC=~/th-middleware/apps/core-platform/deployment/config/geoip
gcloud compute scp "$GEO_SRC/GeoLite2-City.mmdb"    dlp-prod:~/th-middleware/apps/core-platform/deployment/config/geoip/ --zone=asia-south1-a --tunnel-through-iap
gcloud compute scp "$GEO_SRC/GeoLite2-Country.mmdb" dlp-prod:~/th-middleware/apps/core-platform/deployment/config/geoip/ --zone=asia-south1-a --tunnel-through-iap
gcloud compute scp "$GEO_SRC/GeoLite2-ASN.mmdb"     dlp-prod:~/th-middleware/apps/core-platform/deployment/config/geoip/ --zone=asia-south1-a --tunnel-through-iap
```

Verify on the VM:

```bash
ls -lh ~/th-middleware/apps/core-platform/deployment/config/geoip/
# Expect GeoLite2-City.mmdb (~63 MB), GeoLite2-Country.mmdb, GeoLite2-ASN.mmdb
```

> If these are missing, GeoIP is a silent no-op — the app still runs, but auth
> emails/logs show "Unknown location". Not fatal, but you lose the audit info.

---

## 4. Update `deployment/.env`

Your VM `.env` was copied from `.env.prod.example` before this release and is
missing the new keys. Append/confirm the following block (the compose file has
defaults for all of them, but set them explicitly in production):

```bash
cd ~/th-middleware/apps/core-platform/deployment
nano .env
```

```env
# --- Email (Resend) + brand ---
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxx
RESEND_DEFAULT_FROM=Tarrina Health <noreply@tarrinahealth.com>
RESEND_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxxxxxxxxx
EMAIL_PROVIDER=resend
EMAIL_ENABLED=true
EMAIL_LOG_ONLY=false
EMAIL_MAX_ATTEMPTS=3
EMAIL_TIMEOUT_SECONDS=30
EMAIL_COMPANY_NAME=Tarrina Health
EMAIL_SUPPORT_EMAIL=tech@tarrinahealth.com
EMAIL_SITE_URL=https://tarrinahealth.com
# Values with spaces MUST be quoted — shell scripts source this file.
EMAIL_COMPANY_ADDRESS="iHub, Gujarat Knowledge Consortium, Navrangpura — 380009, Ahmedabad, Gujarat, India"
FRONTEND_URL=https://dlp.tarrinahealth.com

# --- GeoIP (files copied in §3) ---
GEOIP_ENABLED=true
GEOIP_CITY_DB_PATH=/app/geoip/GeoLite2-City.mmdb
GEOIP_COUNTRY_DB_PATH=/app/geoip/GeoLite2-Country.mmdb

# --- Password reset / OTP (defaults shown; override only if desired) ---
PASSWORD_RESET_CODE_LENGTH=4
PASSWORD_RESET_CODE_TTL_MINUTES=10
PASSWORD_RESET_LINK_TTL_MINUTES=60
PASSWORD_RESET_MAX_ATTEMPTS=3
LOGIN_OTP_CODE_LENGTH=6
LOGIN_OTP_TTL_MINUTES=15
LOGIN_OTP_MAX_ATTEMPTS=5

# --- Authentik outbound sync (only if you have a service-account token) ---
AUTHENTIK_SYNC_ENABLED=false
AUTHENTIK_BASE_URL=http://authentik-server:9000
AUTHENTIK_SERVICE_TOKEN=
```

> **New keys you may not have yet:** `GEOIP_*`, `EMAIL_*` (brand),
> `FRONTEND_URL`. `RESEND_*` and `AUTHENTIK_SYNC_*` already exist in
> `.env.prod.example`.

**Do not** edit the `AUTHENTIK_OIDC_*`/`AUTHENTIK_SYNC_*` values unless you are
turning SSO/sync on. To enable outbound sync, create an Authentik service
account with *Core: Can create/change/delete User* + *Can reset User's
password*, then set `AUTHENTIK_SYNC_ENABLED=true` and paste the token.

Validate before doing anything else (both must be silent):

```bash
docker compose config -q
docker compose config 2>&1 | grep -i 'variable is not set'
docker compose config | grep -c certresolver      # still >= 6 (prod override active)
```

---

## 5. Rebuild the application image & recreate the app containers

One image (`core-platform-backend:latest`) serves **backend, celery-worker,
celery-beat, flower, and search-indexer**. Rebuild it once (this installs
`geoip2`), then recreate every consumer.

```bash
cd ~/th-middleware/apps/core-platform/deployment

# 1. Rebuild (BuildKit caches unchanged layers; installs geoip2).
docker compose build backend

# 2. Recreate app services without touching data stores.
docker compose up -d --no-deps backend celery-worker celery-beat flower search-indexer

# 3. Confirm they are up and healthy.
docker compose ps
docker compose logs --tail=50 backend
```

What each gets:
- `backend` — new routes/modules, GeoIP mount, new env.
- `celery-worker` — email delivery task changes; same new image.
- `celery-beat` / `flower` / `search-indexer` — same image, no behaviour change, recreated for version consistency.

**Frontend:** unchanged in this release — no rebuild needed. (Rebuilding is
harmless if you prefer consistency: `docker compose build frontend && docker
compose up -d --no-deps frontend`.)

---

## 6. Run the database migrations

```bash
docker compose exec backend alembic upgrade head

# Confirm you are at the new head.
docker compose exec backend alembic current
# -> e5f6a7b8c9d0 (head)   (and b7c1f2a9d4e0, d2e3f4a5b6c7 below it)
```

Expected log lines: `b7c1f2a9d4e0` → `d2e3f4a5b6c7` → `e5f6a7b8c9d0`.

> If `alembic current` shows nothing or a base revision, the `DATABASE_URL` is
> wrong — check `docker compose config | grep DATABASE_URL`.
>
> Migrations are additive (new columns are nullable / have server defaults),
> so existing rows are unaffected. Take a DB backup first if you want a
> comfort blanket: `./manage.sh db-backup`.

---

## 7. Re-register the Debezium connector

The connector now streams `public.email_events` and `public.email_links` (for
ClickHouse/Grafana email analytics). Re-apply it:

```bash
cd ~/th-middleware/apps/core-platform/deployment

# Wait for the Connect REST API.
until docker exec debezium curl -sf http://localhost:8083/connectors >/dev/null 2>&1; do sleep 5; done

./manage.sh register-debezium
./manage.sh debezium-status
# Expect "state": "RUNNING" for connector + task.
```

> Re-putting the same connector name updates its config. Because a prior offset
> exists, `snapshot.mode=initial` does **not** re-snapshot existing tables; it
> just starts streaming the two newly-added tables. If you *want* a fresh
> snapshot, delete and recreate the connector — but that is not required.
>
> The registration script now **waits up to 150 s** for the Connect REST API and
> prints the Debezium logs if it never comes up, so it no longer returns
> silently when the container is still booting. If it reports the API is
> unreachable, check `docker compose ps debezium` / `docker compose logs
> debezium` and re-run once it is `healthy`.

Verify the new topics exist (via the loopback-bound Kafbat UI tunnel or):

```bash
docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list | grep -E 'email_events|email_links'
```

---

## 8. Verify the deployment

### 8.1 Health & routes

```bash
curl -fsS https://dlp.tarrinahealth.com/api/health
curl -fsS https://dlp.tarrinahealth.com/api/ready

# New public policy endpoint (proves the auth release is live):
curl -fsS https://dlp.tarrinahealth.com/api/auth/password-policy
# -> {"code":"ok","data":{"min_length":8,...}}
```

### 8.2 Auth email smoke test (Resend)

Register a throwaway account (or use `POST /api/auth/forgot-password` for an
existing one) and confirm the email arrives. In a non-prod emergency you can set
`EMAIL_LOG_ONLY=true` to persist without calling Resend.

```bash
curl -fsS -X POST https://dlp.tarrinahealth.com/api/auth/forgot-password \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"tech@tarrinahealth.com","reset_type":"code"}'
# -> {"code":"ok","data":{"sent":true,...}}   (always uniform)
```

Check the worker actually sent it:

```bash
docker compose logs --tail=50 celery-worker | grep -E 'email_sent|email_queued|email_send_failed'
```

### 8.3 GeoIP is enriching audit info

Request a reset from a real network and inspect the queued email row / logs:

```bash
docker compose exec -T postgres bash -lc 'PGPASSWORD="$POSTGRES_PASS" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DBNAME" -c "select source_ip, actor_id, request_id, template_name from emails order by id desc limit 5;"'
```

The staff-facing security email also shows city/country once GeoIP is loaded.

### 8.4 Moderation (JWT required)

```bash
TOKEN=$(curl -fsS -X POST https://dlp.tarrinahealth.com/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"<admin>","password":"<pw>"}' | jq -r .data.access_token)

curl -fsS -X POST https://dlp.tarrinahealth.com/api/users/1/throttle \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reason":"abuse test","until":"2026-12-31T00:00:00Z"}'
curl -fsS -X POST https://dlp.tarrinahealth.com/api/users/1/unthrottle -H "Authorization: Bearer $TOKEN"
curl -fsS https://dlp.tarrinahealth.com/api/users/1/moderation -H "Authorization: Bearer $TOKEN"
```

### 8.5 Audit trail is being written

```bash
docker compose exec -T postgres bash -lc 'PGPASSWORD="$POSTGRES_PASS" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DBNAME" -c "select created_at, action, status, actor_id, subject_id, ip_address from activity_logs order by id desc limit 25;"'
```

Register / log in / log out / reset / throttle a test user and confirm the
corresponding rows (`auth.register`, `auth.login.success`, `auth.login.failure`,
`auth.logout`, `auth.password.reset.request`, `auth.password.reset.completed`,
`user.moderation.throttle`, …) appear.

---

## 9. Rollback plan

If something is wrong, roll the **app** back without touching data stores:

```bash
cd ~/th-middleware
git log --oneline -5
git checkout <previous-good-commit>
cd apps/core-platform/deployment
docker compose build backend
docker compose up -d --no-deps backend celery-worker celery-beat flower search-indexer
```

The three new migrations are additive. If you must revert the schema:

```bash
docker compose exec backend alembic downgrade d2e3f4a5b6c7   # drops moderation columns
# or fully: alembic downgrade b7c1f2a9d4e0 && alembic downgrade 408b15338657
```

> `downgrade` **drops** columns/tables (and the data in them). Take a
> `./manage.sh db-backup` first. Prefer rolling the app back and leaving the
> schema forward-compatible.

---

## 10. Copy-paste runbook

```bash
# ── LAPTOP ────────────────────────────────────────────────────────────────
cd ~/th-middleware
git switch main && git pull --ff-only origin main
# (tests) cd apps/core-platform/backend && .venv/bin/python -m pytest -q && cd -
git add -A && git commit -m "feat(auth): auth release" && git push origin main

GEO=~/th-middleware/apps/core-platform/deployment/config/geoip
for f in GeoLite2-City.mmdb GeoLite2-Country.mmdb GeoLite2-ASN.mmdb; do
  gcloud compute scp "$GEO/$f" "dlp-prod:~/th-middleware/apps/core-platform/deployment/config/geoip/" \
    --zone=asia-south1-a --tunnel-through-iap
done

# ── VM (via: gcloud compute ssh dlp-prod --zone=asia-south1-a --tunnel-through-iap) ──
cd ~/th-middleware && git pull --ff-only origin main
cd apps/core-platform/deployment

# edit .env: GEOIP_*, EMAIL_*/RESEND_*, FRONTEND_URL, AUTHENTIK_SYNC_* (see §4)
./manage.sh env-check                                # catch shell-hostile .env values
docker compose config -q
docker compose config 2>&1 | grep -i 'variable is not set' || true

docker compose build backend
docker compose up -d --no-deps backend celery-worker celery-beat flower search-indexer
docker compose ps

docker compose exec backend alembic upgrade head
docker compose exec backend alembic current        # e5f6a7b8c9d0 (head)

until docker exec debezium curl -sf http://localhost:8083/connectors >/dev/null 2>&1; do sleep 5; done
./manage.sh register-debezium && ./manage.sh debezium-status

curl -fsS https://dlp.tarrinahealth.com/api/health
curl -fsS https://dlp.tarrinahealth.com/api/auth/password-policy
docker compose logs --tail=50 backend celery-worker
```

---

## 11. Notes for this release

- **Failed-auth persistence fix.** Previously, raising `AuthError` on a bad
  login/OTP/reset caused the request transaction to roll back, silently
  discarding the failure counters — so **account lockout and the OTP/reset
  attempt caps never persisted**. This release commits security state + its
  audit row before raising. After deploy, lockout and attempt caps work for
  real. A regression test (`tests/test_auth_failure_persistence.py`) guards it.
- **GeoIP is optional/graceful.** Missing DB or a private IP → no location,
  never an error.
- **Resend is required for auth emails.** If `RESEND_API_KEY` is unset, queued
  emails fail at delivery (visible in `celery-worker` logs). Set it, or run
  non-prod with `EMAIL_LOG_ONLY=true`.
- **Moderation endpoints require a token but no role today** (same as the rest
  of `/api/users`); add an admin guard before exposing them to non-operators.
- **Audit logging** is dual-write (`activity_logs` + structured logs). The full
  design and event catalog are in
  [`AUTH_AUDIT_LOGGING_PLAN.md`](./AUTH_AUDIT_LOGGING_PLAN.md).

---

## 12. Troubleshooting this release

### 12.1 `POST /api/auth/login` → 500 `internal_error`
**Almost always: migrations were not applied.** The User model now selects the
moderation columns (`is_banned`, `is_throttled`, `banned_until`, …); if the
`users` table lacks them, every query that loads a user raises
`asyncpg.UndefinedColumnError: column users.is_banned does not exist` → 500.

```bash
docker compose exec backend alembic current      # must be e5f6a7b8c9d0 (head)
docker compose exec backend alembic upgrade head
docker compose logs --tail=80 backend | grep -iE 'UndefinedColumn|does not exist'
```

Also confirm the image was actually rebuilt after `git pull` (an old image
without the new schema paired with a new DB, or vice-versa, produces the same
class of error).

### 12.2 Login returns `401 Invalid credentials` with a correct password
1. **Field renamed:** login now takes `identifier` (not `email_or_username`).
   `{"identifier":"you@x.com","password":"…"}`.
2. **Account lookup:** confirm the row exists and by which identifier:
   ```bash
   docker compose exec -T postgres bash -lc 'PGPASSWORD="$POSTGRES_PASS" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DBNAME" -c "select id,email,username,phone,is_deactivated,deleted_at,length(password) as hash_len,left(password,4) as hash_prefix from users order by id desc limit 10;"'
   ```
   - No row → the account was never created (or under a different email).
   - `hash_prefix` not `$2a$`/`$2b$`/`$2y$` → the stored value is not a bcrypt
     hash (e.g. an imported/legacy/empty value). A malformed hash now returns a
     clean `401`, never a 500; the user should use **forgot-password** to set a
     known password.
3. **Lockout/throttle:** `select locked_at, failed_login_attempts, is_throttled
   from users where email='you@x.com';` — a lockout returns 401 "Account locked",
   a throttle returns 429.

### 12.3 OTP / reset email never arrives (API says `{"sent": true}`)
`sent: true` is deliberately uniform and does **not** prove an email was sent.
Check, in order:

1. **Did the account resolve?** Unknown/deactivated/banned identifiers return
   `sent: true` and send nothing (anti-enumeration). Confirm the user row exists
   (§12.2).
2. **Was an `emails` row created, and what is its status?**
   ```bash
   docker compose exec -T postgres bash -lc 'PGPASSWORD="$POSTGRES_PASS" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DBNAME" -c "select id,status,error_message,provider_message_id,created_at,sent_at from emails order by id desc limit 5;"'
   ```
   - `pending` forever → the Celery worker never picked it up.
   - `failed` → read `error_message` (usually Resend rejected the request).
3. **Worker has a *real* Resend key and the new image.**
   ```bash
   docker compose exec celery-worker printenv | grep -E 'RESEND_API_KEY|EMAIL_ENABLED|EMAIL_LOG_ONLY'
   docker compose logs --tail=100 celery-worker | grep -E 'email_|resend'
   ```
   A blank key, or the placeholder `RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxx`
   copied from a template, makes **every** send fail with HTTP 401. It must be a
   real key from the Resend dashboard (`re_…`). The worker won't pick up an edited
   `.env` until it is recreated: `docker compose up -d --no-deps celery-worker`.
   (The backend now also logs `email_provider_misconfigured` when the key is
   empty.)
4. **Resend side:** the API key is valid and the sending domain is **verified**,
   and `RESEND_DEFAULT_FROM` uses that domain. If the domain is unverified,
   Resend returns a 4xx and the row goes `failed`.
5. **Fastest sanity check:** set `EMAIL_LOG_ONLY=true` and re-request — the row
   should flip to `sent` (marked logged, not delivered), proving the pipeline
   works and isolating the problem to Resend credentials.

> **psql auth gotcha:** the `postgres` container authenticates the Unix socket
> with **peer** auth and the `docker exec` OS user is `root`, so a bare
> `psql -U app` fails with `Peer authentication failed`. Always connect over TCP
> with the container's password, as above (`-h 127.0.0.1` +
> `PGPASSWORD="$POSTGRES_PASS"`). `./manage.sh shell-postgres` and
> `db-backup`/`db-restore` already do this after this release.

### 12.4 `manage.sh` fails with `.env: line N: syntax error` / `command not found`
`manage.sh` (and `register-debezium`, `db-backup`, `prod-ssl`, …) **source**
`.env` with `set -a; . .env`. A value containing an unquoted space, `$`, `&`,
`<`, `>` (or a non-printing char) is fine for `docker compose` but breaks the
shell. Classic offenders:

```env
AUTHENTIK_ADMIN_PASSWORD=8Osc&YM$RJ8MlPJ&          # & splits commands, $ expands
RESEND_DEFAULT_FROM=Tarrina Health <noreply@x.com> # < is a redirect
EMAIL_COMPANY_ADDRESS=iHub, Navrangpura 380009     # spaces
```

Lint and fix:

```bash
cd ~/th-middleware/apps/core-platform/deployment
./manage.sh env-check
```

Quote every flagged value (single quotes unless it contains one):

```env
# AUTHENTIK_ADMIN_PASSWORD is dev-only and unused in production — delete it.
RESEND_DEFAULT_FROM="Tarrina Health <noreply@tarrinahealth.com>"
EMAIL_COMPANY_ADDRESS="iHub, Gujarat Knowledge Consortium, Navrangpura — 380009, Ahmedabad, Gujarat, India"
```

> `register-debezium` was also hardened in this release to read the DB
> credentials from the running `postgres` container instead of sourcing `.env`,
> so it no longer depends on a clean `.env`. The other subcommands still do —
> run `./manage.sh env-check` after any manual `.env` edit.

The templates (`.env.prod.example`, `.env.example`) now ship these values
quoted.

---

## 13. API change for this release

`POST /api/auth/login` now takes a single **`identifier`** field (username,
email **or** phone) instead of `email_or_username`. Update any client/web app
accordingly. Registration accepts optional `username` and `phone`; blank
strings are treated as absent. `POST /api/auth/change-password` identifies the
user from the bearer token (body is only `current_password`/`new_password`).
