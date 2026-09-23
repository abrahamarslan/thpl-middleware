# Production Deployment & Data Migration Guide (v2): Google Cloud GCE VM

**Target Domain:** `dlp.tarrinahealth.com`
**Target Infrastructure:** Single hardened GCE VM (`e2-standard-8`, Ubuntu 24.04 LTS, `asia-south1-a`)
**Application Stack:** Traefik v3, FastAPI, Celery, PostgreSQL 18 + PostGIS, Redis 7.4, Kafka (KRaft), Debezium Connect, ClickHouse, Meilisearch, Authentik IAM, Soketi, Grafana LGTM.

> **This document supersedes v1** ([`GCP_VM_PRODUCTION_DEPLOYMENT.md`](./GCP_VM_PRODUCTION_DEPLOYMENT.md))
> for the deployment. v1 remains authoritative for deep TLS/ACME and host-tuning
> troubleshooting; every section here is self-contained enough to deploy from
> scratch, and **§6 is the new data-migration workstream** that v1 lacked.
>
> **What v2 adds**
> 1. A first-class **source → production data migration** workstream (Postgres `app_db`,
>    the Authentik database, stateful Docker volumes, CDC re-snapshot, Zoho backfill).
> 2. Two explicit migration **paths**: *same-schema* (dev/staging of this app) and
>    *legacy-schema* (pre–org-scope / pre–location-decomposition database), including
>    the exact `alembic upgrade head` backfill behaviour that rewrites users/roles.
> 3. **Secret-parity rules** (what must be identical between source and prod, and what must not).
> 4. A **cutover runbook** with a strict ordering and verification SQL.
> 5. A **known-issue note** for the reserved-domain email 500 (see
>    [`../../../docs/analysis-report/auth-500-error-diagnosis.md`](../../../docs/analysis-report/auth-500-error-diagnosis.md)).

---

## Table of Contents

1. [Scope, assumptions & prerequisites](#1-scope-assumptions--prerequisites)
2. [Architecture & resource allocation](#2-architecture--resource-allocation)
3. [Migration decision matrix](#3-migration-decision-matrix)
4. [Phase 1 — Local prep & GCP infrastructure](#4-phase-1--local-prep--gcp-infrastructure)
5. [Phase 2 — VM hardening, Docker, swap](#5-phase-2--vm-hardening-docker-swap)
6. [Phase 3 — Repo, secrets & production `.env`](#6-phase-3--repo-secrets--production-env)
7. [Phase 4 — First boot of the fresh stack](#7-phase-4--first-boot-of-the-fresh-stack)
8. [Phase 5 — DATA MIGRATION (the core of v2)](#8-phase-5--data-migration-the-core-of-v2)
   - 8.1 [Freeze & snapshot the source](#81-freeze--snapshot-the-source)
   - 8.2 [Migrate `app_db` — Path A (same schema)](#82-migrate-app_db--path-a-same-schema)
   - 8.3 [Migrate `app_db` — Path B (legacy schema, with backfill)](#83-migrate-app_db--path-b-legacy-schema-with-backfill)
   - 8.4 [Preserve legacy addresses (optional)](#84-preserve-legacy-addresses-optional)
   - 8.5 [Migrate the Authentik database](#85-migrate-the-authentik-database)
   - 8.6 [Migrate stateful volumes](#86-migrate-stateful-volumes)
   - 8.7 [Integrity, sequences & counts](#87-integrity-sequences--counts)
   - 8.8 [Seed reference data](#88-seed-reference-data)
   - 8.9 [Re-snapshot CDC → Meilisearch & ClickHouse](#89-re-snapshot-cdc--meilisearch--clickhouse)
   - 8.10 [Zoho data backfill](#810-zoho-data-backfill)
   - 8.11 [Authentik user backfill](#811-authentik-user-backfill)
9. [Phase 6 — Cutover & smoke tests](#9-phase-6--cutover--smoke-tests)
10. [Phase 7 — Backups, GCS archival & DR](#10-phase-7--backups-gcs-archival--dr)
11. [Phase 8 — Day-2 operations & rollback](#11-phase-8--day-2-operations--rollback)
12. [Known issues & migration troubleshooting](#12-known-issues--migration-troubleshooting)
13. [Appendix A — Copy-paste runbook](#13-appendix-a--copy-paste-runbook)
14. [Appendix B — Verification SQL](#14-appendix-b--verification-sql)

---

## 1. Scope, assumptions & prerequisites

**In scope:** deploying the `thpl-middleware` `core-platform` monorepo (backend,
frontend, IAM, CDC, observability) to one GCE VM, and migrating all persistent
data from a source environment into it.

**Out of scope:** RBAC hardening, multi-AZ, horizontal scaling, the DLP mobile apps.

### Assumptions

| # | Assumption |
|---|---|
| 1 | You have a **source environment** (dev/staging/legacy production) with the data to migrate. |
| 2 | Source and target run **PostgreSQL 18** (the deployment image is `core-platform-postgres:latest`, PG 18 + PostGIS). Match the client tooling if not. |
| 3 | You can afford a **maintenance window** for cutover (single VM, single Postgres). |
| 4 | DNS for `dlp`, `ws.dlp`, `auth.dlp`, `traefik.dlp` is either not yet live or can be switched with a low TTL. |
| 5 | You have `gcloud` authenticated, the GCP project selected, and `roles/iap.tunnelResourceAccessor`. |
| 6 | You have the source's secrets available: `JWT_SECRET_KEY`, `AUTHENTIK_SECRET_KEY`, `ZOHO_TOKEN_ENCRYPTION_KEY` (see §6.3 for which must match). |

### Prerequisites checklist

- [ ] Source DB **backed up and restorable** (pg_dump + checksum).
- [ ] Source **writes frozen** during the final delta migration window.
- [ ] GCP project, billing, and APIs enabled.
- [ ] DNS registrar access (4 A records).
- [ ] Resend API key, Zoho client credentials (India DC), GeoIP `.mmdb` files.
- [ ] `git` access to `github.com/abrahamarslan/thpl-middleware`.

---

## 2. Architecture & resource allocation

`e2-standard-8` (8 vCPU / 32 GB) + 200 GB `pd-balanced` + 8 GB swap. The stack runs
18 containers; configured limits total ~16 GB at peak. 32 GB (not 16) is required for
parallel backend/frontend builds, OS page cache (Postgres/ClickHouse), the Debezium
initial snapshot JVM spike, and an OOM safety buffer.

| Service | Container | Mem | CPU | Persistence |
|---|---|---|---|---|
| ClickHouse | `clickhouse` | 4 GB | 2.0 | `app_clickhouse_data` |
| Kafka (KRaft) | `kafka` | 3 GB | 2.0 | `app_kafka_data` |
| PostgreSQL 18 + PostGIS | `postgres` | 2 GB | 2.0 | `app_postgres_data` |
| Debezium | `debezium` | 1.5 GB | 1.0 | offset topic in Kafka |
| Authentik server/worker | `authentik-*` | 2×1 GB | 2.0 | `authentik` DB + `app_authentik_media` |
| Backend API | `backend` | 1 GB | 2.0 | `app_backend_media` |
| Celery worker/beat/flower | `celery-*`, `flower` | ~1.5 GB | 2.5 | Redis + Postgres |
| Search indexer / Meilisearch | `search-indexer`, `meilisearch` | ~1 GB | 1.0 | `app_meilisearch_data` |
| Redis / Soketi / Frontend / Traefik | — | ~1.3 GB | 2.0 | `app_redis_data`, `app_traefik_certs` |
| Observability (LGTM) | `prometheus`…`grafana` | ~2.5 GB | 1.5 | `app_*_data` volumes |
| Backups | `postgres-backup`, `backup` | 768 MB | 0.75 | `./backups` |

### Named volumes (exact names matter for migration)

| Volume | Contents | Migration priority |
|---|---|---|
| `app_postgres_data` | `app_db` + `authentik` DB | **Critical** |
| `app_authentik_media` | Authentik uploads/logos | Migrate |
| `app_backend_media` | App file uploads (`/app/media`) | Migrate if used |
| `app_grafana_data` | Dashboards, users, datasources | Migrate or re-provision |
| `app_meilisearch_data` | Search index | Rebuild (CDC) or migrate |
| `app_clickhouse_data` | Analytics | Rebuild (Kafka) or migrate |
| `app_kafka_data` | Topics + Debezium offsets | Fresh (recommended) |
| `app_redis_data` | Cache/broker | **Do not migrate** (transient) |
| `app_traefik_certs` | ACME `acme.json` | **Do not migrate** (reissue) |

See [§8.6](#86-migrate-stateful-volumes) for the tar-based volume transfer.

---

## 3. Migration decision matrix

Choose exactly one path for `app_db` **before** you start. Everything else in the
guide is identical.

| | **Path A — Same schema** | **Path B — Legacy schema** |
|---|---|---|
| **When** | Source already runs *this* app and `alembic current` = `3b7f0ae91c46` (head) | Source predates the users/roles org-scope + location decomposition (old Laravel-era or pre-`fdbf62102e86`) |
| **Method** | `pg_dump` → restore → (no migration needed) | restore the old dump → **`alembic upgrade head` backfills/transforms** |
| **Users org scoping** | Already present | Migration §`1221–1260` assigns the tenant's root/`DEFAULT-HQ` organization; syncs users from their role |
| **Location columns** | Already decomposed | Dropped by the migration; see [§8.4](#84-preserve-legacy-addresses-optional) to preserve addresses first |
| **Downtime** | Minutes | 10–60 min (snapshot + transform) |
| **Risk** | Low | Medium (one-way schema transforms) |

> [!IMPORTANT]
> **Path B is one-way.** The `fdbf62102e86` migration drops ~90 location columns
> and flips `roles.organization_id`/`users.organization_id` to `NOT NULL`. A
> `downgrade` cannot restore dropped data. Take a full source dump and a disk
> snapshot before you start.

---

## 4. Phase 1 — Local prep & GCP infrastructure

Run locally (WSL/macOS) with the repo checked out.

### 4.1 Authenticate & enable APIs

```bash
gcloud auth login
gcloud config set project <YOUR_GCP_PROJECT_ID>

gcloud services enable \
  compute.googleapis.com oslogin.googleapis.com logging.googleapis.com \
  monitoring.googleapis.com storage.googleapis.com iap.googleapis.com
```

### 4.2 Reserve a static regional IP

```bash
REGION="asia-south1"; ZONE="asia-south1-a"
gcloud compute addresses create dlp-vm-ip --region=$REGION
STATIC_IP=$(gcloud compute addresses describe dlp-vm-ip --region=$REGION --format='value(address)')
echo "Reserved Static IP: $STATIC_IP"
```

Create the 4 DNS A records now (TTL 300), and **lower the TTL on the source domain**
if cutover will reuse it:

```dns
dlp.tarrinahealth.com.         300  IN  A  <STATIC_IP>
ws.dlp.tarrinahealth.com.      300  IN  A  <STATIC_IP>
auth.dlp.tarrinahealth.com.    300  IN  A  <STATIC_IP>
traefik.dlp.tarrinahealth.com. 300  IN  A  <STATIC_IP>
```

### 4.3 Firewall (SSH only via IAP)

```bash
gcloud compute firewall-rules create allow-dlp-web \
  --allow=tcp:80,tcp:443 --source-ranges=0.0.0.0/0 --target-tags=dlp-web \
  --description="HTTP/HTTPS to Traefik"

gcloud compute firewall-rules create allow-dlp-ssh-iap \
  --allow=tcp:22 --source-ranges=35.235.240.0/20 --target-tags=dlp-ssh \
  --description="SSH only via GCP IAP"

gcloud compute firewall-rules delete default-allow-ssh --quiet 2>/dev/null || true
```

> Port **80 must stay open** — the Let's Encrypt HTTP-01 challenge uses it before
> the HTTPS redirect.

### 4.4 Create the VM

```bash
gcloud compute instances create dlp-prod \
  --zone=$ZONE --machine-type=e2-standard-8 \
  --image-family=ubuntu-2404-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=200GB --boot-disk-type=pd-balanced \
  --address=$STATIC_IP --tags=dlp-web,dlp-ssh \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
  --metadata=enable-oslogin=TRUE \
  --scopes=logging-write,monitoring-write,storage-rw
```

Connect:

```bash
gcloud compute ssh dlp-prod --zone=asia-south1-a --tunnel-through-iap
```

---

## 5. Phase 2 — VM hardening, Docker, swap

### 5.1 Packages & swap

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl gnupg git openssl jq apache2-utils ufw unattended-upgrades

sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 5.2 Kernel tuning

```bash
sudo tee /etc/sysctl.d/99-dlp.conf << 'EOF'
vm.overcommit_memory = 1
vm.max_map_count = 262144
fs.file-max = 1000000
vm.swappiness = 10
EOF
sudo sysctl --system
```

### 5.3 Docker CE + log rotation

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER

sudo tee /etc/docker/daemon.json << 'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "50m", "max-file": "5" }, "live-restore": true }
EOF
sudo systemctl restart docker
```

Reconnect SSH so the `docker` group applies.

---

## 6. Phase 3 — Repo, secrets & production `.env`

### 6.1 Clone

```bash
gh auth login --hostname github.com -p https -w
git clone https://github.com/abrahamarslan/thpl-middleware.git ~/th-middleware
cd ~/th-middleware/apps/core-platform/deployment
cp .env.prod.example .env
chmod 600 .env
```

`.env.prod.example` already sets `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`,
so every bare `docker compose` command layers the production override automatically.

### 6.2 Generate new infrastructure secrets

```bash
cd ~/th-middleware/apps/core-platform/deployment
for k in POSTGRES_PASSWORD REDIS_PASSWORD CLICKHOUSE_PASSWORD AUTHENTIK_DB_PASSWORD \
         AUTHENTIK_BOOTSTRAP_PASSWORD KAFKA_UI_PASSWORD GRAFANA_ADMIN_PASSWORD; do
  echo "$k=$(openssl rand -hex 24)"
done
for k in MEILISEARCH_KEY JWT_SECRET_KEY SOKETI_APP_SECRET AUTHENTIK_BOOTSTRAP_TOKEN; do
  echo "$k=$(openssl rand -hex 32)"
done
echo "SOKETI_APP_ID=$(openssl rand -hex 8)"
echo "SOKETI_APP_KEY=$(openssl rand -hex 16)"
echo "AUTHENTIK_SECRET_KEY=$(openssl rand -hex 48)"
```

Dashboard/Flower basic-auth hash:

```bash
docker run --rm httpd:2.4-alpine htpasswd -nbB admin 'YOUR_SECURE_PASSWORD'
# paste the hash into config/traefik/dynamic-prod/middlewares.yml
```

### 6.3 Secret-parity rules (read this before choosing what to copy from source)

| Secret | If you migrate the related data | Recommendation |
|---|---|---|
| `JWT_SECRET_KEY` | Existing first-party access/refresh tokens stay valid only with the same key | **Keep source value** to avoid mass logout; rotate later deliberately |
| `AUTHENTIK_SECRET_KEY` | Required to decrypt/sign against a restored Authentik DB; changing it invalidates sessions and encrypted fields | **Must match source** if restoring the `authentik` DB |
| `ZOHO_TOKEN_ENCRYPTION_KEY` | Required to decrypt `zoho_oauth_credentials`; losing it forces a browser re-consent | **Must match source** if restoring the Zoho token row — quote it: `ZOHO_TOKEN_ENCRYPTION_KEY="..."` |
| `POSTGRES_PASSWORD` | Postgres data volumes bake the password on first run | Can be **new** on fresh volumes |
| `REDIS_PASSWORD` | Redis is transient | Can be **new** (do not migrate Redis) |
| `AUTHENTIK_DB_PASSWORD` | The Authentik DB role password; `postgres-init` recreates it | Can be **new** on a fresh volume |
| `SOKETI_APP_ID/KEY/SECRET` | Websocket auth; clients re-authenticate anyway | Can be **new** |
| `MEILISEARCH_KEY` | Index is accessed by app + indexer only | Can be **new** |
| `ACME_EMAIL` | Let's Encrypt expiry notices | A real monitored mailbox |

Fill in `.env` per the v1 §4.3 table (Zoho, Resend, Authentik, GeoIP, tuning).
Then validate:

```bash
./manage.sh env-check
docker compose config -q
docker compose config 2>&1 | grep -i 'variable is not set'   # silent
docker compose config | grep -c certresolver                 # >= 6
docker compose config | grep -oE 'Host\(`[^`]+`\)' | sort -u # dlp/ws/auth/traefik
```

### 6.4 Copy the git-ignored GeoIP databases

From your laptop:

```bash
GEO=~/th-middleware/apps/core-platform/deployment/config/geoip
for f in GeoLite2-City.mmdb GeoLite2-Country.mmdb GeoLite2-ASN.mmdb; do
  gcloud compute scp "$GEO/$f" "dlp-prod:~/th-middleware/apps/core-platform/deployment/config/geoip/" \
    --zone=asia-south1-a --tunnel-through-iap
done
```

---

## 7. Phase 4 — First boot of the fresh stack

> [!CAUTION]
> Confirm the prod override is active (`grep -c certresolver` ≥ 6) and that you are
> **not** running `docker-compose.dev.yml` (it publishes DB ports) nor setting
> `ACMEDNS_ENABLED=true` (port 53 clash).

### 7.1 Launch data infrastructure only (do not start app containers yet)

For a data migration you want Postgres up and empty, with no backend workers
writing to it.

```bash
cd ~/th-middleware/apps/core-platform/deployment

# Postgres + its init (creates app_db + the authentik role/db) + Redis.
docker compose up -d postgres postgres-init redis

until docker compose exec -T postgres pg_isready -U app -d app_db >/dev/null 2>&1; do
  echo "waiting for postgres..."; sleep 3
done
echo "Postgres ready."
```

> If the migration path is Path A and you intend to restore into the existing
> database, still start from a fresh volume. If you are **re-running** a failed
> migration, reset first with `./manage.sh reset-db` (backs up both DBs, then wipes
> `app_postgres_data`).

### 7.2 Bring up the rest of the stack

Once `app_db` is populated (Phase 5), start everything:

```bash
docker compose up -d --build --remove-orphans
docker compose ps
```

---

## 8. Phase 5 — DATA MIGRATION (the core of v2)

> **Golden rules**
> 1. **Freeze writes on the source** before the final delta (a maintenance page or
>    `systemctl stop` on the source app).
> 2. **Move the data first, run migrations second** (Path B), or restore and skip
>    migrations (Path A, already at head).
> 3. **Never point production DNS at the new VM** until Phase 6 verification passes.
> 4. Every command below runs with the destination's actual credentials. The
>    `postgres` container exposes `POSTGRES_USER`, `POSTGRES_PASS`, `POSTGRES_DBNAME`.

### 8.1 Freeze & snapshot the source

On the **source** host:

```bash
cd <source>/apps/core-platform/deployment

# 1. Stop the writers (backend + workers) but leave Postgres running.
docker compose stop backend celery-worker celery-beat search-indexer

# 2. Freeze the schema+data in one consistent custom-format dump.
docker compose exec -T postgres bash -lc \
  'PGPASSWORD="$POSTGRES_PASS" pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -Fc --no-owner --no-privileges' > /tmp/app_db_$(date +%Y%m%d_%H%M).dump

# 3. Authentik DB too.
docker compose exec -T postgres bash -lc \
  'PGPASSWORD="$POSTGRES_PASS" pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "${AUTHENTIK_DB_NAME:-authentik}" \
     -Fc --no-owner --no-privileges' > /tmp/authentik_$(date +%Y%m%d_%H%M).dump

sha256sum /tmp/app_db_*.dump /tmp/authentik_*.dump
```

If the source is a **legacy (pre-migration) DB**, also confirm its revision:

```bash
docker compose exec -T postgres bash -lc \
  'PGPASSWORD="$POSTGRES_PASS" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select version_num from alembic_version;"'
```

Copy the dumps to the prod VM (from your laptop; adjust source path):

```bash
gcloud compute scp /tmp/app_db_*.dump       dlp-prod:/tmp/ --zone=asia-south1-a --tunnel-through-iap
gcloud compute scp /tmp/authentik_*.dump    dlp-prod:/tmp/ --zone=asia-south1-a --tunnel-through-iap
```

> For large dumps, use a GCS bucket as the hop:
> `gcloud storage cp` up from source, `gcloud storage cp` down on the VM.

### 8.2 Migrate `app_db` — Path A (same schema)

Use when the source is already at `3b7f0ae91c46` (head). On the **VM**:

```bash
DUMP=/tmp/app_db_<stamp>.dump

# Restore over the fresh app_db. --clean --if-exists makes it re-runnable.
docker compose exec -T postgres bash -lc \
  "PGPASSWORD=\"\$POSTGRES_PASS\" pg_restore -h 127.0.0.1 -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" \
     --clean --if-exists --no-owner --no-privileges" < "$DUMP"

# Confirm the migrated revision is already head.
docker compose exec backend alembic current      # -> 3b7f0ae91c46 (head)
```

If `alembic current` is behind, run `docker compose exec backend alembic upgrade head`.

> **Sequence drift:** `pg_restore` from a custom-format dump restores sequence
> `setval`s, so no manual fix is normally needed. If you used a **data-only**
> restore, run the sequence reset in [Appendix B](#14-appendix-b--verification-sql).

### 8.3 Migrate `app_db` — Path B (legacy schema, with backfill)

Use when the source predates the org-scope/location decomposition. The migration
`20260921_1241_fdbf62102e86_users_org_scope_location_decomposition_.py`
**transforms an existing database in place**:

- `INSERT`s a `DEFAULT-HQ` organization for any tenant that has none;
- backfills `roles.organization_id`, then flips it to `NOT NULL`;
- backfills `users.organization_id` from each user's role (and from the tenant's
  first organization when there is no role);
- adds `users.primary_place_id` / keeps `country_code`, drops the ~90 legacy
  location columns, and rewires the composite FKs.

**Procedure (restore first, then migrate):**

```bash
cd ~/th-middleware/apps/core-platform/deployment
LEGACY=/tmp/app_db_<stamp>.dump

# 1. Postgres is up and app_db is empty (no migrations have run yet on this volume).
#    Restore the LEGACY schema+data.
docker compose exec -T postgres bash -lc \
  "PGPASSWORD=\"\$POSTGRES_PASS\" pg_restore -h 127.0.0.1 -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" \
     --no-owner --no-privileges" < "$LEGACY"

# 2. Start ONLY the backend so we can run alembic (workers stay down).
docker compose up -d backend

# 3. Run the migration chain: old revision -> head (this performs the backfill).
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current          # -> 3b7f0ae91c46 (head)

# 4. Inspect the backfill before proceeding.
docker compose exec -T postgres bash -lc \
  'PGPASSWORD="$POSTGRES_PASS" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
   "select count(*) filter (where organization_id is null) as users_null_org from users;"'
# Expect 0.

# 5. Now start the remaining app containers.
docker compose up -d
```

If `alembic upgrade head` fails partway, **do not re-run blindly**: drop and
recreate the DB from the legacy dump (`./manage.sh reset-db` then repeat), because
Alembic DDL is not idempotent against a half-migrated schema.

> [!WARNING]
> Legacy address data lives in the old `users` location columns, which the
> migration **drops**. If you need it, run [§8.4](#84-preserve-legacy-addresses-optional)
> **before** step 1.

### 8.4 Preserve legacy addresses (optional)

Path B only. Addresses were decomposed onto the `geo` hub (`geo.places` +
`geo.place_links`, `owner_type='user'`). To carry legacy addresses across:

1. On the **source**, before migration, export the old address columns:

   ```sql
   \copy (SELECT id AS user_id, street_address, city, state, postal_code, country,
                 latitude, longitude, formatted_address
          FROM users WHERE deleted_at IS NULL) TO '/tmp/users_addresses.csv' CSV HEADER
   ```

2. Copy the CSV to the VM.
3. After the migration (`§8.3`) and reference seeding (`§8.8`), load it through the
   platform address book — preferred route is the API, which maintains the
   `users.primary_place_id` cache, effective-dating and audit:

   ```bash
   TOKEN=$(curl -fsS -X POST https://dlp.tarrinahealth.com/api/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"identifier":"<admin>","password":"<pw>"}' | jq -r .data.access_token)

   # One call per user (script the CSV):
   curl -fsS -X PATCH https://dlp.tarrinahealth.com/api/auth/me/profile \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"address":{"street":"...","city":"...","state":"...","postal_code":"...",
                     "country":"India","latitude":19.07,"longitude":72.87}}'
   ```

   A direct SQL load into `geo.places`/`geo.place_links` is possible but bypasses
   the address service's invariants (one-primary, effective-dating); only do it
   with a written reconciliation step.

### 8.5 Migrate the Authentik database

```bash
cd ~/th-middleware/apps/core-platform/deployment
ADUMP=/tmp/authentik_<stamp>.dump

# The authentik DB/role were created by postgres-init on first boot.
docker compose exec -T postgres bash -lc \
  "PGPASSWORD=\"\$POSTGRES_PASS\" pg_restore -h 127.0.0.1 -U \"\$POSTGRES_USER\" -d authentik \
     --clean --if-exists --no-owner --no-privileges" < "$ADUMP"

# Authentik applies its own migrations on boot; restart it.
docker compose up -d --force-recreate authentik-server authentik-worker
docker compose logs -f authentik-server | grep -iE 'migrat|ready|error'
```

> [!IMPORTANT]
> `AUTHENTIK_SECRET_KEY` **must equal the source's value** if you restore this DB,
> or Authentik cannot decrypt stored secrets and invalidates all sessions. The
> Authentik DB does not store its own bootstrap admin password once set — if
> `akadmin` cannot log in after restore, use the source's credentials or the
> recovery flow at `https://auth.dlp.tarrinahealth.com/if/flow/recovery/`.

### 8.6 Migrate stateful volumes

Stop the owning services, tar the volume through a throwaway container, transfer,
and untar on the VM.

**On the source** (example: Authentik media):

```bash
docker run --rm \
  -v app_authentik_media:/src:ro -v /tmp:/backup alpine \
  tar -czf /backup/vol-app_authentik_media.tar.gz -C /src .
```

Repeat for each volume you are migrating: `app_authentik_media`,
`app_backend_media`, `app_grafana_data`, optionally `app_meilisearch_data`,
`app_clickhouse_data`.

Transfer:

```bash
gcloud compute scp /tmp/vol-*.tar.gz dlp-prod:/tmp/ --zone=asia-south1-a --tunnel-through-iap
```

**On the VM**, stop the consumer and restore (example: Authentik media):

```bash
cd ~/th-middleware/apps/core-platform/deployment
docker compose stop authentik-server authentik-worker
docker run --rm -v app_authentik_media:/dst -v /tmp:/backup alpine \
  sh -c 'rm -rf /dst/* && tar -xzf /backup/vol-app_authentik_media.tar.gz -C /dst'
docker compose up -d authentik-server authentik-worker
```

| Volume | Recommended action |
|---|---|
| `app_authentik_media` | **Migrate** (logos, uploaded flows) |
| `app_backend_media` | **Migrate** if any files were uploaded |
| `app_grafana_data` | Migrate (dashboards/users), or re-provision from `config/grafana/provisioning/` |
| `app_meilisearch_data` | **Skip** — rebuilt by CDC re-snapshot (§8.9) |
| `app_clickhouse_data` | **Skip** — rebuilt from Kafka (analytics history is optional) |
| `app_kafka_data` | **Skip** — start Kafka fresh; new connector offsets trigger a snapshot |
| `app_redis_data` | **Skip** (transient) |
| `app_traefik_certs` | **Skip** — Let's Encrypt reissues for the new IP |

### 8.7 Integrity, sequences & counts

Run the checks in [Appendix B](#14-appendix-b--verification-sql) on both source and
destination and compare. Minimum bar:

- `alembic_version.version_num` = `3b7f0ae91c46`
- `users` count matches; `users.organization_id` has no NULLs
- `roles` count matches; per-org uniqueness holds
- `activity_logs`, `kyc_*`, `documents`, `emails` counts match
- No sequence is behind its table max (Appendix B resets them if needed)

### 8.8 Seed reference data

Run the master seeder **after** the migration so reference tables
(`countries`, `timezones`, `country_timezones`, document types) and the
company tenant/organization/admin (`COMPANY_*`/`DEFAULT_*` in `.env`) exist.
The seeders never overwrite edited rows.

```bash
cd ~/th-middleware/apps/core-platform/deployment

# .env must define COMPANY_ADMIN_PASSWORD for the seeded admin.
docker compose exec backend python scripts/seed.py

# Or target one seeder:
docker compose exec backend python scripts/seed.py --only company
docker compose exec backend python scripts/seed.py --only users.reference
```

### 8.9 Re-snapshot CDC → Meilisearch & ClickHouse

Debezium is configured with `snapshot.mode=initial` and an include list
(`config/debezium/zoho-mirror-connector.json`). On a **fresh Kafka volume** there
are no stored offsets, so registering the connector takes a full snapshot and the
`search-indexer` repopulates Meilisearch from the resulting topics.

If you are re-registering on a cluster that already ran (offsets exist), force a
clean snapshot:

```bash
cd ~/th-middleware/apps/core-platform/deployment

# 1. Drop the connector and its replication slot.
curl -s -X DELETE localhost:8083/connectors/zoho-mirror   # via IAP tunnel if needed
docker compose exec -T postgres bash -lc \
  'PGPASSWORD="$POSTGRES_PASS" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c "SELECT pg_drop_replication_slot('"'"'zoho_mirror'"'"') WHERE EXISTS (SELECT 1 FROM pg_replication_slots WHERE slot_name='"'"'zoho_mirror'"'"');"'

# 2. (If you kept Kafka) clear the connect offset topics, or simply start Kafka fresh.

# 3. Re-register and wait.
until docker exec debezium curl -sf http://localhost:8083/connectors >/dev/null 2>&1; do sleep 5; done
./manage.sh register-debezium
./manage.sh debezium-status            # expect RUNNING

# 4. Watch the indexer fill Meilisearch.
docker compose logs -f search-indexer | grep -iE 'index|batch|error'
```

Verify a search index is populated (JWT required):

```bash
curl -fsS "https://dlp.tarrinahealth.com/api/search/indexes" -H "Authorization: Bearer $TOKEN"
curl -fsS "https://dlp.tarrinahealth.com/api/search/organizations?q=" -H "Authorization: Bearer $TOKEN" | jq '.data.count'
```

### 8.10 Zoho data backfill

Zoho is the master for the mirrored masters (organizations, currencies, taxes,
locations, users) and the sync engine is idempotent.

```bash
cd ~/th-middleware/apps/core-platform/deployment

# 0. .env: ZOHO_TOKEN_PERSISTENCE_ENABLED=true, ZOHO_TOKEN_ENCRYPTION_KEY set,
#    and (if you want the operator API) ZOHO_OPERATOR_EMAILS.

# 1. Connect Zoho once (browser consent): Swagger -> GET /api/zoho/auth/initiate?redirect=false
#    then open data.authorization_url. The callback answers {"connected": true}.
#    (Skip if you restored zoho_oauth_credentials AND kept the same encryption key.)

# 2. Prove credentials + connectivity.
docker compose exec backend python -m app.modules.zoho.cli check --live

# 3. Full master sync + status.
docker compose exec backend python -m app.modules.zoho.cli sync
docker compose exec backend python -m app.modules.zoho.cli status

# 4. Organization mirror (in-app endpoint), mode=full.
curl -fsS -X POST "https://dlp.tarrinahealth.com/api/organizations/sync?mode=full" \
  -H "Authorization: Bearer $TOKEN"
```

The engine is governed (`ZOHO_CONTRACT_DAILY_LIMIT`, per-minute rate, concurrency);
a large backfill may span multiple runs — `cli runs` shows progress and `cli status`
shows per-module freshness.

### 8.11 Authentik user backfill

After `app_db` is restored and seeded, link/create the corresponding Authentik
users for any local users missing a link:

```bash
cd ~/th-middleware/apps/core-platform/deployment
docker compose exec backend python -c "from app.tasks.authentik import backfill; print(backfill())"
# equivalently: ./manage.sh authentik-backfill
```

> Requires `AUTHENTIK_SYNC_ENABLED=true` + a valid `AUTHENTIK_SERVICE_TOKEN`
> (Authentik admin → Directory → Tokens, service account with *Can create/change/
> delete User* + *Can reset User's password*).

---

## 9. Phase 6 — Cutover & smoke tests

### 9.1 Pre-cutover checks on the new VM

```bash
cd ~/th-middleware/apps/core-platform/deployment
docker compose ps
docker compose exec backend alembic current          # head
curl -fsS localhost:8000/health   || docker compose exec backend curl -s localhost:8000/health
curl -fsS localhost:8000/ready    || true
```

`/api/health` and `/api/ready` are also reachable through Traefik once DNS points
here; until then you can test with `--resolve`:

```bash
curl -fsS --resolve dlp.tarrinahealth.com:443:$STATIC_IP https://dlp.tarrinahealth.com/api/health
```

### 9.2 Issue TLS (automatic on first HTTPS hit)

```bash
./manage.sh prod-ssl
for h in "" auth. ws. traefik.; do curl -sI "https://${h}dlp.tarrinahealth.com/" -o /dev/null; done
openssl s_client -connect dlp.tarrinahealth.com:443 -servername dlp.tarrinahealth.com </dev/null \
  | openssl x509 -noout -issuer   # C=US, O=Let's Encrypt
```

### 9.3 Switch DNS

Point the 4 A records at `<STATIC_IP>` (they may already be, per §4.2). Wait for
propagation:

```bash
for h in dlp ws.dlp auth.dlp traefik.dlp; do getent hosts $h.tarrinahealth.com; done
```

### 9.4 Smoke tests

```bash
curl -fsS https://dlp.tarrinahealth.com/api/health
curl -fsS https://dlp.tarrinahealth.com/api/ready
curl -fsS https://dlp.tarrinahealth.com/api/auth/password-policy

# Authenticated smoke (use a real migrated admin):
TOKEN=$(curl -fsS -X POST https://dlp.tarrinahealth.com/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"<admin-email>","password":"<pw>"}' | jq -r .data.access_token)
curl -fsS https://dlp.tarrinahealth.com/api/auth/me -H "Authorization: Bearer $TOKEN" | jq '.data.email'
curl -fsS https://dlp.tarrinahealth.com/api/users?page_size=1 -H "Authorization: Bearer $TOKEN" | jq '.data.total'
```

Browser checks: frontend SPA, Authentik admin (`auth.dlp...`), Traefik dashboard
(`traefik.dlp.../dashboard/`, trailing slash), Flower (`/flower`), Grafana
(`/grafana`), and the Kafbat UI via an SSH tunnel
(`gcloud compute ssh dlp-prod --tunnel-through-iap -- -L 8088:localhost:8088`).

> [!NOTE]
> **Known issue — reserved-domain emails cause a 500.** Any `UserOut`/`UserMeOut`
> serialisation of a user whose stored email uses a reserved TLD (`.test`,
> `.local`, `.invalid`, `.localhost`) raises a Pydantic `ValidationError` → 500 on
> `/api/auth/me`, `/api/auth/me/profile`, `/api/users`, `/api/users/{id}`. If the
> source had such rows (e.g. `dev@local.test`, `…@authentik.local`), you will see
> this immediately after cutover. Full diagnosis + fix:
> [`../../../docs/analysis-report/auth-500-error-diagnosis.md`](../../../docs/analysis-report/auth-500-error-diagnosis.md).
> Immediate data check (Appendix B) lists any such rows.

---

## 10. Phase 7 — Backups, GCS archival & DR

### 10.1 Postgres & volume backups (already containerized)

- `postgres-backup` (`kartoza/pg-backup`) dumps `app_db` + `authentik` into `./backups` per `POSTGRES_BACKUP_CRON`.
- `backup` (`offen/docker-volume-backup`) tars Grafana, Authentik media and Meilisearch into `./backups` per `BACKUP_CRON`.

### 10.2 GCS offsite bucket

```bash
BUCKET_NAME="gs://dlp-prod-backups"; REGION="asia-south1"
gcloud storage buckets create $BUCKET_NAME --location=$REGION --uniform-bucket-level-access

cat << 'EOF' > gcs-lifecycle.json
{ "rule": [
  {"action":{"type":"SetStorageClass","storageClass":"NEARLINE"},"condition":{"age":14}},
  {"action":{"type":"SetStorageClass","storageClass":"COLDLINE"},"condition":{"age":30}},
  {"action":{"type":"Delete"},"condition":{"age":90}}
]}
EOF
gcloud storage buckets update $BUCKET_NAME --lifecycle-file=gcs-lifecycle.json && rm gcs-lifecycle.json
```

### 10.3 Nightly sync from the VM

```bash
sudo crontab -l 2>/dev/null | grep -v 'sync-backups-gcs' | sudo crontab -
(sudo crontab -l 2>/dev/null; echo "30 3 * * * /bin/bash /home/$USER/th-middleware/apps/core-platform/deployment/scripts/sync-backups-gcs.sh gs://dlp-prod-backups >> /var/log/gcs-backup.log 2>&1") | sudo crontab -
```

### 10.4 GCE disk snapshots

```bash
gcloud compute resource-policies create snapshot-schedule dlp-daily-disk-snapshot \
  --region=asia-south1 --max-retention-days=14 --daily-schedule --start-time=04:00
gcloud compute disks add-resource-policies dlp-prod \
  --zone=asia-south1-a --resource-policies=dlp-daily-disk-snapshot
```

### 10.5 Restore procedures

```bash
# app_db from a pg-backup dump:
./manage.sh db-restore backups/PG_app_db_YYYYMMDD_HHMMSS.sql.gz

# A single named volume from the tarball:
docker run --rm -v app_meilisearch_data:/dst -v ~/th-middleware/apps/core-platform/deployment/backups:/backup alpine \
  sh -c 'rm -rf /dst/* && tar -xzf /backup/volumes-YYYY-MM-DDTHH-MM-SS.tar.gz -C /dst'
```

---

## 11. Phase 8 — Day-2 operations & rollback

### 11.1 Deploying updates (no data loss)

```bash
cd ~/th-middleware && git pull origin main
cd apps/core-platform/deployment
docker compose build backend frontend
docker compose up -d --no-deps backend celery-worker celery-beat search-indexer frontend
docker compose exec backend alembic upgrade head
```

> Any change to the CDC include list in
> `config/debezium/zoho-mirror-connector.json` requires
> `./manage.sh register-debezium`.

### 11.2 Auto-restart on reboot (systemd)

Create `/etc/systemd/system/dlp-platform.service`:

```ini
[Unit]
Description=DLP Core Platform Docker Compose Stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/<VM_USER>/th-middleware/apps/core-platform/deployment
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose stop
TimeoutStartSec=0
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable dlp-platform.service
```

### 11.3 Rollback

**App-only rollback (schema forward-compatible):**

```bash
cd ~/th-middleware && git log --oneline -5 && git checkout <previous-good>
cd apps/core-platform/deployment
docker compose build backend
docker compose up -d --no-deps backend celery-worker celery-beat search-indexer
```

**Full rollback:** restore the app_db dump taken in §8.1 and point DNS back at the
source. Keep the source environment running (writes stopped) until the new VM has
passed verification. Never rely on `alembic downgrade` for Path B — the location
columns are gone; restore the pre-migration dump instead.

---

## 12. Known issues & migration troubleshooting

### 12.1 `/api/auth/me`, `/api/users` return 500 after migration
Reserved-domain emails from the source (`@local.test`, `@authentik.local`). See
[§9.4 note](#94-smoke-tests) and the diagnosis doc. Fast triage:

```sql
SELECT id, email FROM users
WHERE email ~* '@(.*\.)?(test|local|invalid|localhost)$';
```

### 12.2 `alembic upgrade head` fails mid-way (Path B)
Do **not** re-run on the half-migrated schema. Reset and repeat:

```bash
./manage.sh reset-db          # backs up both DBs, wipes app_postgres_data
docker compose up -d postgres postgres-init
# restore the LEGACY dump again, then alembic upgrade head
```

### 12.3 `pg_restore: error: role "app" does not exist` / ownership errors
Re-run with `--no-owner --no-privileges` (already in the commands). Roles are not
dumped by `pg_dump`; the container's `POSTGRES_USER` owns the DB.

### 12.4 Authentik users can't log in after DB restore
`AUTHENTIK_SECRET_KEY` differs from source, or the bootstrap admin row is stale.
Set the source key and recreate Authentik, or use the recovery flow / create a new
superuser via `docker compose exec authentik-server ak create_recovery_key`.

### 12.5 Zoho `yielded switch:auth_paused`
The refresh token is missing/undecryptable. Either `ZOHO_TOKEN_ENCRYPTION_KEY`
changed, or `zoho_oauth_credentials` was not migrated. Reconnect (§8.10 step 1).

### 12.6 Meilisearch index is empty after cutover
Debezium had stored offsets (Kafka volume migrated). Force a snapshot per §8.9.
Also confirm `SEARCH_CDC_TOPICS` is set and `search-indexer` is running.

### 12.7 Debezium `FAILED` — snapshot ran before migrations
Classic ordering bug: the connector snapshotted before Alembic created its tables.
Re-register (`./manage.sh register-debezium`); if the slot is stuck, drop it
(§8.9) and recreate.

### 12.8 Sequences behind after a data-only load
Run the sequence block in [Appendix B](#14-appendix-b--verification-sql).

### 12.9 `.env` shell-safety / compose variable warnings
`./manage.sh env-check`; quote values containing `$ & <space>`; remove dev-only
`AUTHENTIK_ADMIN_PASSWORD`.

### 12.10 Ports / TLS / OOM
Deep dives live in v1 §13 (Issues 1–6): `/api` falling through to the SPA,
ACME not issuing, Debezium FAILED, OOM, Kafka healthcheck, CORS.

---

## 13. Appendix A — Copy-paste runbook

```bash
# ══ SOURCE (freeze + dump) ═══════════════════════════════════════════════════
cd <source>/apps/core-platform/deployment
docker compose stop backend celery-worker celery-beat search-indexer
docker compose exec -T postgres bash -lc \
  'PGPASSWORD="$POSTGRES_PASS" pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges' > /tmp/app_db.dump
docker compose exec -T postgres bash -lc \
  'PGPASSWORD="$POSTGRES_PASS" pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "${AUTHENTIK_DB_NAME:-authentik}" -Fc --no-owner --no-privileges' > /tmp/authentik.dump
docker run --rm -v app_authentik_media:/src:ro -v /tmp:/backup alpine tar -czf /backup/vol-authentik-media.tar.gz -C /src .
sha256sum /tmp/*.dump /tmp/vol-*.tar.gz

# ══ LAPTOP (transfer) ════════════════════════════════════════════════════════
for f in /tmp/app_db.dump /tmp/authentik.dump /tmp/vol-authentik-media.tar.gz; do
  gcloud compute scp "$f" dlp-prod:/tmp/ --zone=asia-south1-a --tunnel-through-iap
done

# ══ VM: setup (Phases 1–3 from §4–§6) then: ══════════════════════════════════
cd ~/th-middleware/apps/core-platform/deployment
docker compose up -d postgres postgres-init redis
until docker compose exec -T postgres pg_isready -U app -d app_db >/dev/null 2>&1; do sleep 3; done

# ── Path A (source already at head) ──
docker compose exec -T postgres bash -lc \
  "PGPASSWORD=\"\$POSTGRES_PASS\" pg_restore -h 127.0.0.1 -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --clean --if-exists --no-owner --no-privileges" < /tmp/app_db.dump

# ── OR Path B (legacy schema) ──
# docker compose exec -T postgres bash -lc \
#   "PGPASSWORD=\"\$POSTGRES_PASS\" pg_restore -h 127.0.0.1 -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --no-owner --no-privileges" < /tmp/app_db.dump
# docker compose up -d backend
# docker compose exec backend alembic upgrade head

# Authentik DB + media
docker compose exec -T postgres bash -lc \
  "PGPASSWORD=\"\$POSTGRES_PASS\" pg_restore -h 127.0.0.1 -U \"\$POSTGRES_USER\" -d authentik --clean --if-exists --no-owner --no-privileges" < /tmp/authentik.dump
docker run --rm -v app_authentik_media:/dst -v /tmp:/backup alpine sh -c 'rm -rf /dst/* && tar -xzf /backup/vol-authentik-media.tar.gz -C /dst'

# Full stack + migrations + seed
docker compose up -d --build --remove-orphans
docker compose exec backend alembic current          # 3b7f0ae91c46 (head)
docker compose exec backend python scripts/seed.py

# CDC snapshot
until docker exec debezium curl -sf http://localhost:8083/connectors >/dev/null 2>&1; do sleep 5; done
./manage.sh register-debezium && ./manage.sh debezium-status

# Zoho
docker compose exec backend python -m app.modules.zoho.cli check --live
docker compose exec backend python -m app.modules.zoho.cli sync

# Authentik
./manage.sh authentik-backfill

# TLS
./manage.sh prod-ssl
curl -fsS https://dlp.tarrinahealth.com/api/health
curl -fsS https://dlp.tarrinahealth.com/api/ready
```

---

## 14. Appendix B — Verification SQL

Run as: `docker compose exec -T postgres bash -lc 'PGPASSWORD="$POSTGRES_PASS" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`

```sql
-- Migration state (must be head)
SELECT version_num FROM alembic_version;

-- Users org-scoped (no NULLs) with role coherence
SELECT count(*) AS users, count(*) FILTER (WHERE organization_id IS NULL) AS null_org,
       count(*) FILTER (WHERE role_id IS NOT NULL AND organization_id <> (
         SELECT r.organization_id FROM roles r WHERE r.id = users.role_id)) AS role_org_mismatch
FROM users;

-- Roles per organization uniqueness
SELECT tenant_id, organization_id, code, count(*)
FROM roles WHERE deleted_at IS NULL GROUP BY 1,2,3 HAVING count(*) > 1;

-- Reserved-domain emails that will 500 the API (fix or rewrite after import)
SELECT id, email FROM users
WHERE email ~* '@(.*\.)?(test|local|invalid|localhost)$';

-- Key table counts (compare against source)
SELECT 'users' t, count(*) FROM users
UNION ALL SELECT 'organizations', count(*) FROM org_management.organizations
UNION ALL SELECT 'roles', count(*) FROM roles
UNION ALL SELECT 'activity_logs', count(*) FROM activity_logs
UNION ALL SELECT 'emails', count(*) FROM emails
UNION ALL SELECT 'documents', count(*) FROM documents
UNION ALL SELECT 'kyc_profiles', count(*) FROM kyc_profiles
UNION ALL SELECT 'place_links', count(*) FROM geo.place_links
UNION ALL SELECT 'user_live_locations', count(*) FROM user_live_locations
ORDER BY 1;

-- Sequence reset (only if a data-only restore left sequences behind).
-- Generate the statements, then run them:
SELECT 'SELECT setval(' || quote_literal(pg_get_serial_sequence(quote_ident(c.table_schema)||'.'||quote_ident(c.table_name), c.column_name))
       || ', COALESCE((SELECT MAX(' || quote_ident(c.column_name) || ') FROM ' ||
          quote_ident(c.table_schema)||'.'||quote_ident(c.table_name) || '), 1));'
FROM information_schema.columns c
WHERE c.table_schema IN ('public','core','geo','org_management','tax','currency','sync')
  AND c.column_default LIKE 'nextval%'
  AND c.table_name NOT LIKE '%_pings';   -- partitioned tables excluded

-- Replication slot health (Debezium)
SELECT slot_name, active, restart_lsn FROM pg_replication_slots;
```

---

**Document owner:** Platform Engineering · **Last updated:** September 2026
**Companion docs:** v1 TLS/ops guide, `AUTH_CHANGES_DEPLOYMENT_GUIDE.md`,
`../../../docs/analysis-report/auth-500-error-diagnosis.md`,
`../../../docs/implementation-plan/users-update-implementation-plan.md`.
