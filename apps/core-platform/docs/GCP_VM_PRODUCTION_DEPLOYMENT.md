# Production Deployment Guide: Google Cloud GCE VM
**Target Domain:** `dlp.tarrinahealth.com`  
**Target Infrastructure:** Single Hardened GCE VM (`e2-standard-8`, Ubuntu 24.04 LTS, `asia-south1`)  
**Application Stack:** Traefik v3, FastAPI, Celery, PostgreSQL 18 + PostGIS, Redis 7.4, Kafka (KRaft), Debezium Connect, ClickHouse, Meilisearch, Authentik IAM, Soketi, Grafana LGTM Observability Suite.

---

## Table of Contents
1. [Architecture & Resource Allocation](#1-architecture--resource-allocation)
2. [Domain & Routing Architecture](#2-domain--routing-architecture)
3. [Traefik & TLS Configuration](#3-traefik--tls-configuration)
4. [Step 1: Local Prep & GCP Infrastructure Provisioning](#4-step-1-local-prep--gcp-infrastructure-provisioning)
5. [Step 2: VM Operating System Hardening & Kernel Tuning](#5-step-2-vm-operating-system-hardening--kernel-tuning)
6. [Step 3: Docker & Systemd Daemon Configuration](#6-step-3-docker--systemd-daemon-configuration)
7. [Step 4: Repository Clone & Secrets Generation](#7-step-4-repository-clone--secrets-generation)
8. [Step 5: Zoho Developer Console Setup](#8-step-5-zoho-developer-console-setup)
9. [Step 6: Stack Deployment & Execution Ordering](#9-step-6-stack-deployment--execution-ordering)
10. [Step 7: Verification & Smoke Testing](#10-step-7-verification--smoke-testing)
11. [Step 8: Automated Backups, GCS Offsite Archival & DR](#11-step-8-automated-backups-gcs-offsite-archival--dr)
12. [Day-2 Operations & Update Playbook](#12-day-2-operations--update-playbook)
13. [Troubleshooting & Common Pitfalls](#13-troubleshooting--common-pitfalls)

---

## 1. Architecture & Resource Allocation

### Machine Sizing Rationale
- **Machine Type:** `e2-standard-8` (8 vCPU, 32 GB RAM)
- **Region & Zone:** `asia-south1-a` (Mumbai) — matches Indian users and Zoho India DC (`accounts.zoho.in`).
- **Disk:** `200 GB pd-balanced` (Persistent Disk Balanced SSD)

The stack runs 18 containerized services. The configured Docker container memory limits total ~16 GB under peak load:

| Service | Container Name | Memory Limit | CPU Limit | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **ClickHouse** | `clickhouse` | 4 GB | 2.0 | High-throughput analytics ingestion |
| **Kafka (KRaft)** | `kafka` | 3 GB | 2.0 | CDC stream broker (base 2 GB; prod override raises to 3 GB for broker heap + page cache) |
| **PostgreSQL** | `postgres` | 2 GB | 2.0 | PostGIS + 12 extensions + WAL replication |
| **Debezium** | `debezium` | 1.5 GB | 1.0 | Kafka Connect CDC for zoho-mirror tables |
| **Authentik Server** | `authentik-server` | 1 GB | 1.0 | IAM, OIDC core server |
| **Authentik Worker** | `authentik-worker` | 1 GB | 1.0 | Background IAM sync & cleanup |
| **Backend API** | `backend` | 1 GB | 2.0 | FastAPI + Uvicorn (4 workers) |
| **Celery Worker** | `celery-worker` | 1 GB | 2.0 | Concurrency 4 (default, integrations, docs) |
| **Celery Beat** | `celery-beat` | 256 MB | 0.25 | Task scheduler |
| **Flower** | `flower` | 256 MB | 0.25 | Celery task dashboard |
| **Search Indexer** | `search-indexer` | 512 MB | 0.50 | CDC to Meilisearch indexing worker |
| **Meilisearch** | `meilisearch` | 512 MB | 0.50 | Full-text product & contact search |
| **Redis** | `redis` | 512 MB | 0.50 | Broker, cache, session store |
| **Soketi** | `soketi` | 256 MB | 0.50 | Pusher WebSocket server |
| **Frontend** | `frontend` | 256 MB | 0.50 | Nginx serving compiled React SPA |
| **Traefik** | `traefik` | 256 MB | 0.50 | Edge router & Let's Encrypt TLS termination |
| **Kafbat UI** | `kafbat-ui` | 512 MB | 0.50 | Internal Kafka management UI |
| **Observability** | `prometheus`, `loki`, `tempo`, `alloy`, `grafana` | ~2.5 GB | ~1.5 | LGTM telemetry pipeline |
| **Backups** | `postgres-backup`, `backup` | 512 MB | 0.50 | Nightly & scheduled archive dumpers |

### Why 32 GB RAM is required (not 16 GB):
1. **Initial Compilation & Builds:** Building `backend` (pip wheels) and `frontend` (`npm run build`) in parallel takes 4–6 GB of memory burst.
2. **OS Page Cache:** PostgreSQL and ClickHouse rely heavily on Linux kernel filesystem caching for index and table lookups.
3. **Debezium Initial Snapshot:** On initial connector registration, Debezium streams complete snapshots of mirrored tables into Kafka, causing temporary memory spikes in JVM heaps.
4. **OOM Safety Buffer:** A mandatory 8 GB swapfile protects against Linux OOM-killer termination of critical databases.

---

## 2. Domain & Routing Architecture

All ingress traffic enters through Traefik on static ports `80` (HTTP) and `443` (HTTPS). Internal service ports (8000, 5432, 6379, 9092, etc.) are **never** published to the public internet or VM host interface in production.

### Hostnames & Ingress Routing

| External URL | Host Header Rule | Path / Service | Authentication |
| :--- | :--- | :--- | :--- |
| `https://dlp.tarrinahealth.com` | `Host(dlp.tarrinahealth.com)` | Frontend SPA (Nginx) | Public / Client SPA |
| `https://dlp.tarrinahealth.com/api` | `Host(dlp.tarrinahealth.com) && PathPrefix(/api)` | Backend API (FastAPI) | JWT / Bearer / Public Probes |
| `https://dlp.tarrinahealth.com/flower` | `Host(dlp.tarrinahealth.com) && PathPrefix(/flower)` | Celery Flower Dashboard | HTTP Basic Auth (`dashboard-auth`) |
| `https://dlp.tarrinahealth.com/grafana` | `Host(dlp.tarrinahealth.com) && PathPrefix(/grafana)` | Grafana Observability UI | Grafana Admin Auth |
| `https://ws.dlp.tarrinahealth.com` | `Host(ws.dlp.tarrinahealth.com)` | Soketi WebSocket Server | Soketi App Key |
| `https://auth.dlp.tarrinahealth.com` | `Host(auth.dlp.tarrinahealth.com)` | Authentik IAM Server | Authentik Flow / OIDC |
| `https://traefik.dlp.tarrinahealth.com/dashboard/` | `Host(traefik.dlp.tarrinahealth.com)` | Traefik Proxy Dashboard | HTTP Basic Auth (`dashboard-auth`) |

### DNS Configuration Requirements
Configure the following 4 `A` records in your DNS registrar pointing to the static external IP assigned to the VM:

```dns
dlp.tarrinahealth.com.         300  IN  A  <VM_STATIC_IP>
ws.dlp.tarrinahealth.com.      300  IN  A  <VM_STATIC_IP>
auth.dlp.tarrinahealth.com.    300  IN  A  <VM_STATIC_IP>
traefik.dlp.tarrinahealth.com. 300  IN  A  <VM_STATIC_IP>
```

> [!NOTE]
> Setting TTL to 300s (5 minutes) initially ensures fast propagation and avoids cached misconfigurations.
> While a wildcard `*.dlp.tarrinahealth.com A <VM_STATIC_IP>` record will route DNS, **Let's Encrypt HTTP-01 challenge cannot issue a wildcard TLS certificate**; Traefik requests explicit certificates for each individual SAN. 4 distinct A records are recommended for security hygiene.

---

## 3. Traefik & TLS Configuration

### Production TLS Strategy: ACME HTTP-01 Challenge
- **Development** uses `mkcert` file certs via `config/traefik/dynamic/tls.yml.disabled` and the base `config/traefik/traefik.yml`.
- **Production** uses **pure ACME HTTP-01**. The production override swaps in dedicated config files so you never hand-edit the dev ones.

#### Why HTTP-01:
1. No `acme-dns` container on port 53 (conflicts with Ubuntu's `systemd-resolved`).
2. No external CNAME delegation.
3. Validation completes automatically through Traefik on port 80.

### How the production override wires TLS (nothing to hand-edit)

`docker-compose.prod.yml` mounts **production-only** files over the container paths:

| Container path | Dev (base) | Production (`docker-compose.prod.yml`) |
| :--- | :--- | :--- |
| `/etc/traefik/traefik.yml` | `config/traefik/traefik.yml` (mkcert / placeholder acme-dns) | **`config/traefik/traefik.prod.yml`** — HTTP-01 on entryPoint `web` |
| `/etc/traefik/dynamic/` | `config/traefik/dynamic/` (shared "changeme" basic-auth) | **`config/traefik/dynamic-prod/`** — real basic-auth hash |
| ACME email | — | `${ACME_EMAIL}` from `.env`, injected as `TRAEFIK_CERTIFICATESRESOLVERS_LETSENCRYPT_ACME_EMAIL` |

Every public router already carries `tls.certresolver=letsencrypt` in the prod override (api, frontend, flower, grafana, soketi, authentik, dashboard). ACME state persists in the `traefik_certs` named volume (`/letsencrypt/acme.json`).

The production override is pulled in **automatically**: `.env.prod.example` (which
you copy to `.env`) sets `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`,
so every `docker compose` command run from `deployment/` layers it without any
`-f` flags. Verify with `docker compose config | grep -c certresolver` (expect ≥ 6).

> [!WARNING]
> The **base** `config/traefik/traefik.yml` defines a `dnsChallenge` (acme-dns) resolver only — it has **no `httpChallenge`**. If the prod override is not applied (no `COMPOSE_FILE` in `.env`, deployed with `-f docker-compose.yml` only, or `git pull` predates it), **Traefik serves a self-signed cert and every browser reports "not secure" — no error is logged**. This is the #1 cause of "HTTPS not working".

`config/traefik/traefik.prod.yml` (already in the repo — shown for reference):

```yaml
# apps/core-platform/deployment/config/traefik/traefik.prod.yml
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint: { to: websecure, scheme: https }
  websecure:
    address: ":443"
  metrics:
    address: ":8082"

certificatesResolvers:
  letsencrypt:
    acme:
      email: tech@tarrinahealth.com          # overridden by ${ACME_EMAIL} at runtime
      storage: /letsencrypt/acme.json
      httpChallenge:
        entryPoint: web
```

> [!IMPORTANT]
> Traefik intercepts `/.well-known/acme-challenge/` on port 80 **before** the HTTPS redirect. Never block port 80 at the GCP firewall.

### The only manual TLS step: rotate the dashboard / Flower password

`config/traefik/dynamic-prod/middlewares.yml` ships with a working bcrypt hash, but rotate it before go-live:

```bash
cd ~/th-middleware/apps/core-platform/deployment
docker run --rm httpd:2.4-alpine htpasswd -nbB admin 'YOUR_SECURE_PASSWORD'
# -> admin:$2y$05$....  paste into config/traefik/dynamic-prod/middlewares.yml
```
```yaml
# config/traefik/dynamic-prod/middlewares.yml
http:
  middlewares:
    dashboard-auth:
      basicAuth:
        users:
          - "admin:<GENERATED_BCRYPT_HASH>"     # $ chars are fine here — file provider does not interpolate
```
Record the plaintext in `.env` as a comment, then `docker compose up -d --force-recreate traefik`.

> [!NOTE]
> Do **not** `mv` or edit `config/traefik/dynamic/tls.yml.disabled` or `config/traefik/traefik.yml` on the VM — production does not mount them.

---

## 4. Step 1: Local Prep & GCP Infrastructure Provisioning

### 1.1 Local Machine Setup (WSL / Linux)
```bash
# Ensure gcloud and GitHub CLI are authenticated
gcloud auth login
gcloud config set project <YOUR_GCP_PROJECT_ID>

# Enable required Google Cloud APIs
gcloud services enable \
  compute.googleapis.com \
  oslogin.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  storage.googleapis.com \
  iap.googleapis.com
```

### 1.2 Reserve Static Regional External IP
```bash
REGION="asia-south1"
ZONE="asia-south1-a"

gcloud compute addresses create dlp-vm-ip --region=$REGION
STATIC_IP=$(gcloud compute addresses describe dlp-vm-ip --region=$REGION --format='value(address)')
echo "Reserved Static IP: $STATIC_IP"
```
*Configure your 4 DNS A records (`dlp`, `ws.dlp`, `auth.dlp`, `traefik.dlp`) to point to `$STATIC_IP` now.*

### 1.3 Configure Firewall Rules (Hardened Bastion via IAP)
**Do not expose SSH (port 22) to `0.0.0.0/0`**. Ingress SSH is restricted strictly to Google Cloud's Identity-Aware Proxy (IAP) netblock `35.235.240.0/20`.

```bash
# 1. Allow HTTP (80) and HTTPS (443) for Traefik
gcloud compute firewall-rules create allow-dlp-web \
  --allow=tcp:80,tcp:443 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=dlp-web \
  --description="Allow HTTP and HTTPS to Traefik edge proxy"

# 2. Allow SSH only through Google Cloud IAP Tunnel
gcloud compute firewall-rules create allow-dlp-ssh-iap \
  --allow=tcp:22 \
  --source-ranges=35.235.240.0/20 \
  --target-tags=dlp-ssh \
  --description="Allow SSH access exclusively through GCP IAP"

# 3. CRITICAL: Check and delete the default 0.0.0.0/0 SSH rule if present in the VPC
gcloud compute firewall-rules delete default-allow-ssh --quiet 2>/dev/null || true
```

> [!WARNING]
> Your GCP IAM user or service account must have the role `roles/iap.tunnelResourceAccessor` to connect through IAP. Verify with:
> `gcloud projects add-iam-policy-binding <PROJECT_ID> --member="user:you@domain.com" --role="roles/iap.tunnelResourceAccessor"`

### 1.4 Create the Hardened GCE Virtual Machine
```bash
gcloud compute instances create dlp-prod \
  --zone=$ZONE \
  --machine-type=e2-standard-8 \
  --image-family=ubuntu-2404-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=200GB \
  --boot-disk-type=pd-balanced \
  --address=$STATIC_IP \
  --tags=dlp-web,dlp-ssh \
  --shielded-secure-boot \
  --shielded-vtpm \
  --shielded-integrity-monitoring \
  --metadata=enable-oslogin=TRUE \
  --scopes=logging-write,monitoring-write,storage-rw
```

---

## 5. Step 2: VM Operating System Hardening & Kernel Tuning

Connect to the VM via the secure IAP tunnel:
```bash
gcloud compute ssh dlp-prod --zone=asia-south1-a --tunnel-through-iap
```

Once inside the VM, execute host hardening:

### 2.1 Update System Packages & Install Utilities
```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  git \
  openssl \
  jq \
  apache2-utils \
  ufw \
  unattended-upgrades
```

### 2.2 Configure 8 GB Swapfile
To safeguard database buffers and Celery worker bursts from triggering OOM-kills:
```bash
sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 2.3 Kernel Sysctl Tuning (`/etc/sysctl.d/99-dlp.conf`)
Redis, Kafka, ClickHouse, and PostGIS require specific memory allocation and descriptor limits:
```bash
sudo tee /etc/sysctl.d/99-dlp.conf << 'EOF'
# Required by Redis to avoid background save failures under memory pressure
vm.overcommit_memory = 1

# Required by Kafka and ClickHouse memory-mapped file allocations
vm.max_map_count = 262144

# System-wide file descriptor limit
fs.file-max = 1000000

# Low swappiness to prefer RAM over swap
vm.swappiness = 10
EOF

sudo sysctl --system
```

### 2.4 Configure Unattended Upgrades (Automated Security Patches)
```bash
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## 6. Step 3: Docker & Systemd Daemon Configuration

### 3.1 Install Docker CE (Official Upstream Repository)
```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Grant current user docker group membership
sudo usermod -aG docker $USER
```
*(Logout of SSH session and reconnect via `gcloud compute ssh ...` for group change to take effect).*

### 3.2 Configure Docker Daemon with Log Rotation (`/etc/docker/daemon.json`)
Without log rotation, 18 microservices running 24/7 will rapidly exhaust the 200 GB disk.
```bash
sudo tee /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  },
  "live-restore": true
}
EOF

sudo systemctl restart docker
docker compose version
```

---

## 7. Step 4: Repository Clone & Secrets Generation

### 4.1 Clone Application Repository & Create the Env File
```bash
# Authenticate GitHub CLI
gh auth login --hostname github.com -p https -w

# Clone (the repo directory name does not matter — this guide assumes ~/th-middleware)
git clone https://github.com/abrahamarslan/thpl-middleware.git ~/th-middleware
cd ~/th-middleware/apps/core-platform/deployment

# Create the production env file FROM THE PRODUCTION TEMPLATE, named .env.
cp .env.prod.example .env
chmod 600 .env
```

> [!IMPORTANT]
> Use **`.env.prod.example`**, not `.env.example` (that one is dev-flavoured),
> and name the copy **`.env`**. The template's first line is
> `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`, so from now on a
> bare `docker compose <cmd>` in this directory **always** layers the production
> override automatically — no `-f` flags, no `manage.sh` required. `.env` is
> git-ignored; never commit it.
>
> (`manage.sh prod` / `prod-migrate` / `prod-ssl` also work and are equivalent.)

### 4.2 Generate Cryptographic Secrets
Generate **hex-only** tokens — hex has no shell/compose metacharacters (`$ & " ' <space>`), so nothing has to be quoted or `$$`-escaped in `.env`.

```bash
cat << 'EOF' > generate_secrets.sh
#!/usr/bin/env bash
echo "=== Production Cryptographic Keys (paste into .env) ==="
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
echo
echo "# Traefik dashboard / Flower basic-auth:"
DASH_PW=$(openssl rand -hex 12)
echo "#   plaintext: $DASH_PW"
docker run --rm httpd:2.4-alpine htpasswd -nbB admin "$DASH_PW" 2>/dev/null \
  | sed 's/^/#   hash:      /'
EOF
bash generate_secrets.sh
rm generate_secrets.sh
```

> [!NOTE]
> `AUTHENTIK_SERVICE_TOKEN` is **not** a random string — it is a service-account
> API token you create later in the Authentik admin UI (Directory → Tokens).
> Leave it blank with `AUTHENTIK_SYNC_ENABLED=false` until then.
>
> If any value contains a literal `$`, single-quote it in `.env`
> (`FOO='a$b'`) or double the dollar (`FOO=a$$b`) — otherwise `docker compose`
> treats `$b` as a variable and warns *"The \"b\" variable is not set"*. Do not
> copy `AUTHENTIK_ADMIN_PASSWORD` from the dev `.env` — it is dev-only, unused in
> production, and its `$` was the source of that warning.

### 4.3 Configure the Production `.env`
`.env.prod.example` already contains every key with the correct production
defaults for `dlp.tarrinahealth.com` (domain, CORS, TLS wiring, Kafka cluster id,
Authentik/Zoho URLs, tuning). Open `.env` and change only these:

| Key(s) | Value |
| :--- | :--- |
| `POSTGRES_PASSWORD` `REDIS_PASSWORD` `CLICKHOUSE_PASSWORD` `MEILISEARCH_KEY` `JWT_SECRET_KEY` `SOKETI_APP_ID` `SOKETI_APP_KEY` `SOKETI_APP_SECRET` `AUTHENTIK_SECRET_KEY` `AUTHENTIK_DB_PASSWORD` `AUTHENTIK_BOOTSTRAP_PASSWORD` `AUTHENTIK_BOOTSTRAP_TOKEN` `KAFKA_UI_PASSWORD` `GRAFANA_ADMIN_PASSWORD` | paste from §4.2 |
| `ACME_EMAIL` | a real mailbox you monitor (Let's Encrypt expiry notices) |
| `AUTHENTIK_BOOTSTRAP_EMAIL` | your admin email |
| `AUTHENTIK_EMAIL_PASSWORD` | SMTP password / API key (or leave blank + reset via UI) |
| `ZOHO_CLIENT_ID` `ZOHO_CLIENT_SECRET` `ZOHO_ORGANIZATION_ID` `ZOHO_REFRESH_TOKEN` `ZOHO_WEBHOOK_KEY_INCOMING` | from the Zoho console (§5) — **rotate the secret** |
| `RESEND_API_KEY` `RESEND_WEBHOOK_SECRET` | from the Resend dashboard |

Leave `AUTHENTIK_SERVICE_TOKEN`, `AUTHENTIK_OIDC_CLIENT_ID` blank for now
(post-boot setup). Do **not** add `COMPOSE_FILE`, `APP_DOMAIN`, `CORS_ORIGINS`,
`ZOHO_REDIRECT_URL` — the template already has them right.

> [!TIP]
> Sanity-check before launching — both must be silent:
> ```bash
> docker compose config -q
> docker compose config 2>&1 | grep -i 'variable is not set'
> ```

---

## 8. Step 5: Zoho Developer Console Setup

Zoho is strictly partitioned by geographical datacenter.

1. Navigate to **[Zoho API Console (India)](https://api-console.zoho.in/)** (Ensure you are on `.in`, not `.com`).
2. Select your Client (or create a `Server-based Application`):
   - **Client Name:** `DLP Core Platform Prod`
   - **Homepage URL:** `https://dlp.tarrinahealth.com`
   - **Authorized Redirect URIs:**
     ```
     https://dlp.tarrinahealth.com/api/zoho/auth/callback
     ```
3. Rotate Client Secret immediately if the prior secret was ever placed in source control. **The secret carried in the repo's dev `.env` is compromised — rotate it.**
4. Update `ZOHO_CLIENT_ID` and `ZOHO_CLIENT_SECRET` in `deployment/.env`.

---

## 9. Step 6: Stack Deployment & Execution Ordering

### Important Pre-flight Warnings
> [!CAUTION]
> 1. **The production override must be active.** Because `.env` sets
>    `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`, a bare
>    `docker compose ...` from `deployment/` already layers it. Verify once with
>    `docker compose config | grep -c certresolver` → must be **≥ 6**. If it
>    prints `0`, your `.env` is wrong (missing `COMPOSE_FILE`) and HTTPS will
>    only ever serve a self-signed cert.
> 2. **Do NOT run `docker-compose.dev.yml` in production.** It publishes raw DB ports to the host.
> 3. **Do NOT set `ACMEDNS_ENABLED=true`.** That adds `--profile production` → the `acmedns` container on port 53, which clashes with `systemd-resolved`. It is only for DNS-01 wildcard certs.
> 4. **Database credentials are immutable after first launch.** `postgres_data`, `redis_data`, `clickhouse_data` bake in the password on first run. Changing it in `.env` later breaks connections unless you `docker compose down -v` those volumes.

### 9.1 Pre-flight Validation
```bash
cd ~/th-middleware/apps/core-platform/deployment
docker compose config -q                                  # parses cleanly
docker compose config 2>&1 | grep -i 'variable is not set' # (no output)
docker compose config | grep -c certresolver              # >= 6  -> prod override IS active
docker compose config | grep -oE 'Host\(`[^`]+`\)' | sort -u
#   -> must show dlp.tarrinahealth.com / auth.dlp… / ws.dlp… / traefik.dlp…
#      If it shows app.local, your .env has the wrong APP_DOMAIN.
```

### 9.2 Launch the Production Stack
```bash
docker compose up -d --build --remove-orphans
# equivalently: ./manage.sh prod
```

### 9.3 Wait for Core Data Infrastructure
PostgreSQL initializes PostGIS, and Kafka establishes KRaft metadata consensus:
```bash
echo "Waiting for PostgreSQL cluster readiness..."
until docker compose exec -T postgres pg_isready -U app -d app_db >/dev/null 2>&1; do
    sleep 3
done
echo "PostgreSQL is accepting connections."
```

### 9.4 Execute Database Migrations
Run Alembic migrations inside the baked backend container:
```bash
docker compose exec backend alembic upgrade head
# equivalently: ./manage.sh prod-migrate
```
> [!NOTE]
> If this fails with `ModuleNotFoundError: No module named 'app.modules.media'`,
> your checkout predates the `.gitignore` fix that stopped `media/` from hiding
> the `app/modules/media/` package — `git pull` and rebuild the backend image.

### 9.5 Register Debezium CDC Connector
Debezium takes ~45 seconds to boot its embedded Kafka Connect REST API on port 8083. Wait for the API before registering:
```bash
echo "Waiting for Debezium REST engine..."
until docker exec debezium curl -sf http://localhost:8083/connectors >/dev/null 2>&1; do
    sleep 5
done

# Register the zoho-mirror connector
./manage.sh register-debezium

# Verify connector status
./manage.sh debezium-status
```
*Expected response: `"state": "RUNNING"` for both connector and tasks.*

### 9.6 Confirm TLS Certificates
**There is no "request a certificate" command.** With HTTP-01, Traefik obtains a
cert from Let's Encrypt automatically the first time each hostname is requested
over HTTPS, then renews it ~30 days before expiry. It just needs, per host:
DNS → this VM, inbound port 80 open, and a router carrying `tls.certresolver`
(the prod override does this).

```bash
./manage.sh prod-ssl              # DNS + :80 reachability + acme.json + live cert + ACME logs

# or trigger issuance by hitting each host and watch the log:
docker compose logs -f traefik | grep -iE 'acme|certificate|challenge'
for h in "" auth. ws. traefik.; do curl -sI "https://${h}dlp.tarrinahealth.com/" -o /dev/null; done
```
A healthy result: `acme.json` lists all four hostnames, and
`openssl s_client -connect dlp.tarrinahealth.com:443` shows issuer
`C=US, O=Let's Encrypt`. If you see `CN=TRAEFIK DEFAULT CERT`, jump to
[§13 Issue 2](#issue-2-https-broken--lets-encrypt-certificate-never-issued-your-connection-is-not-private-self-signed-traefik-default-cert).

---

## 10. Step 7: Verification & Smoke Testing

### 10.1 Command-Line Verification (From Your Laptop)

```bash
# 1. Verify Backend API Probe via Traefik HTTPS
curl -fsS https://dlp.tarrinahealth.com/api/health
# Output: {"status":"ok","service":"core-platform","version":"0.1.0"}

# 2. Verify Backend Deep Readiness Probe (PostgreSQL & Redis check)
curl -fsS https://dlp.tarrinahealth.com/api/ready
# Output: {"status":"ok","checks":{"postgres":"ok","redis":"ok"}}

# 3. Verify Frontend Static SPA Serving
curl -sI https://dlp.tarrinahealth.com/ | grep -E 'HTTP|content-type'

# 4. Verify /api/docs is disabled (404 expected in production)
curl -s -o /dev/null -w "%{http_code}\n" https://dlp.tarrinahealth.com/api/docs
# Output: 404

# 5. Verify Soketi WebSocket endpoint
curl -sI https://ws.dlp.tarrinahealth.com/ | head -n 1
# Output: HTTP/2 200

# 6. Verify Authentik Live Probe
curl -fsS https://auth.dlp.tarrinahealth.com/-/health/live/
```

### 10.2 Web Browser Verification & Initial Admin Setups

1. **Frontend App:** Open `https://dlp.tarrinahealth.com/`
2. **Authentik Admin:**
   - The `akadmin` user is already created from `AUTHENTIK_BOOTSTRAP_EMAIL` /
     `AUTHENTIK_BOOTSTRAP_PASSWORD` in `.env` — log in at
     `https://auth.dlp.tarrinahealth.com/`.
   - If those were left blank, run the setup flow instead:
     `https://auth.dlp.tarrinahealth.com/if/flow/initial-setup/`.
3. **Traefik Dashboard:**
   - Navigate to: `https://traefik.dlp.tarrinahealth.com/dashboard/` *(trailing slash required)*
   - Login `admin` / the password recorded in `.env` (hash in `config/traefik/dynamic-prod/middlewares.yml`).
   - Verify green routers and a valid ACME certificate on each.
4. **Celery Flower Dashboard:**
   - Navigate to: `https://dlp.tarrinahealth.com/flower`
   - Verify Celery worker `celery@core-platform-worker` is online with queues `default`, `integrations`, `documents`.
5. **Grafana Observability:**
   - Navigate to: `https://dlp.tarrinahealth.com/grafana`
   - Login with `admin` and `$GRAFANA_ADMIN_PASSWORD`.
6. **Kafbat UI Access (Secure IAP Tunnel):**
   Kafbat UI is deliberately bound to loopback `127.0.0.1:8088`. Open an encrypted SSH tunnel from your local machine:
   ```bash
   gcloud compute ssh dlp-prod --zone=asia-south1-a --tunnel-through-iap -- -L 8088:localhost:8088
   ```
   Open `http://localhost:8088` on your laptop to inspect Kafka topics and Debezium CDC consumer lag.

---

## 11. Step 8: Automated Backups, GCS Offsite Archival & DR

The deployment employs a 3-tier backup strategy:
1. **Containerized Database Dumps (`postgres-backup`):** `kartoza/pg-backup` creates automated compressed SQL dumps of `app_db` and `authentik` into `./backups` every 2 days.
2. **Containerized Volume Backups (`backup`):** `offen/docker-volume-backup` creates compressed tarballs of Meilisearch, Authentik media, and Grafana into `./backups` every 2 days.
3. **Automated GCS Offsite Sync:** Nightly push from `./backups` to an offsite Google Cloud Storage bucket with object lifecycle rules.
4. **Native GCE Disk Snapshots:** Crash-consistent daily block-level snapshots.

### 11.1 Create GCS Backup Bucket with Lifecycle Policy
Execute on your local machine or VM with storage permissions:

```bash
BUCKET_NAME="gs://dlp-prod-backups"
REGION="asia-south1"

# 1. Create uniform access bucket
gcloud storage buckets create $BUCKET_NAME --location=$REGION --uniform-bucket-level-access

# 2. Configure 60-day auto-purge lifecycle policy
cat << 'EOF' > gcs-lifecycle.json
{
  "rule": [
    {
      "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
      "condition": {"age": 14}
    },
    {
      "action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
      "condition": {"age": 30}
    },
    {
      "action": {"type": "Delete"},
      "condition": {"age": 90}
    }
  ]
}
EOF

gcloud storage buckets update $BUCKET_NAME --lifecycle-file=gcs-lifecycle.json
rm gcs-lifecycle.json
```

### 11.2 Configure Nightly GCS Backup Sync Script on VM
The script `deployment/scripts/sync-backups-gcs.sh` handles timestamp resolution, path resolution, and error reporting.

Add to the VM's root crontab (root privileges required because PostgreSQL backup dumps are created with root ownership):

```bash
sudo crontab -l 2>/dev/null | grep -v 'sync-backups-gcs' | sudo crontab -
(sudo crontab -l 2>/dev/null; echo "30 3 * * * /bin/bash /home/$USER/th-middleware/apps/core-platform/deployment/scripts/sync-backups-gcs.sh gs://dlp-prod-backups >> /var/log/gcs-backup.log 2>&1") | sudo crontab -
```

### 11.3 Enable Native GCP Daily Persistent Disk Snapshots
Independent of application scripts, GCP block-level disk snapshots provide instant full-disk recovery:

```bash
# Create daily snapshot schedule retaining 14 days
gcloud compute resource-policies create snapshot-schedule dlp-daily-disk-snapshot \
  --region=asia-south1 \
  --max-retention-days=14 \
  --daily-schedule \
  --start-time=04:00

# Attach policy to VM boot disk
gcloud compute disks add-resource-policies dlp-prod \
  --zone=asia-south1-a \
  --resource-policies=dlp-daily-disk-snapshot
```

### 11.4 Disaster Recovery & Restoration Procedures

#### Restoring PostgreSQL from Backup:
```bash
cd ~/th-middleware/apps/core-platform/deployment
# Check available local dumps
ls -la backups/
# Restore specific dump file
./manage.sh db-restore backups/PG_app_db_YYYYMMDD_HHMMSS.sql.gz
```

#### Restoring State Volumes (Meilisearch / Authentik Media):
```bash
# 1. Stop write services
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop meilisearch authentik-server authentik-worker
# 2. Restore tarball to named volume
docker run --rm -v app_meilisearch_data:/target -v ~/th-middleware/apps/core-platform/deployment/backups:/backup alpine \
  tar -xzf /backup/volumes-YYYY-MM-DDTHH-MM-SS.tar.gz -C /target
# 3. Restart services
docker compose -f docker-compose.yml -f docker-compose.prod.yml start meilisearch authentik-server authentik-worker
```

---

## 12. Day-2 Operations & Update Playbook

### 12.1 Deploying Application Updates (Zero Data Loss)
When new commits land on `main`:

```bash
cd ~/th-middleware
git checkout main
git pull origin main

cd apps/core-platform/deployment
# (.env sets COMPOSE_FILE, so bare `docker compose` already layers the prod override)

# 1. Rebuild application images (BuildKit caches unchanged layers)
docker compose build backend frontend

# 2. Rolling update of app services without terminating databases
docker compose up -d --no-deps backend celery-worker celery-beat search-indexer frontend

# 3. Apply any newly added database migrations
docker compose exec backend alembic upgrade head
```

### 12.2 Systemd Managed Auto-Restart on VM Reboot
To ensure the entire stack restarts cleanly if Google performs host maintenance:

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
# Adjust to the cloning user's home (e.g. /home/abraham_arsalan_.../th-middleware/...).
WorkingDirectory=/home/<VM_USER>/th-middleware/apps/core-platform/deployment
# .env in that dir sets COMPOSE_FILE, so no -f flags are needed here.
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose stop
TimeoutStartSec=0
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```
> [!NOTE]
> `restart: unless-stopped` / `always` on the containers already survives daemon
> restarts and `live-restore`. This unit only covers a full VM reboot.

Enable the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable dlp-platform.service
```

---

## 13. Troubleshooting & Common Pitfalls

### Issue 1: `curl: (22) The requested URL returned error: 404` on `/api/health`
- **Cause:** FastAPI registered `system_router` only at `/health`, but Traefik only routes requests with `PathPrefix(/api)` to the backend container.
- **Resolution:** In `backend/app/core/registrar.py`, `system_router` must be mounted at both `/` and `settings.API_PREFIX`. *(This has been fixed in the codebase).*

### Issue 2: HTTPS broken / Let's Encrypt certificate never issued ("your connection is not private", self-signed `TRAEFIK DEFAULT CERT`)
Run `./manage.sh prod-ssl` first — it checks every cause below at once.

- **Cause 1 (most common): the production override is not active.** A bare
  `docker compose up -d` uses only `docker-compose.yml` unless `.env` sets
  `COMPOSE_FILE`. The base `traefik.yml` has only a `dnsChallenge` (acme-dns)
  resolver and the base routers have no `certresolver`, so Traefik serves a
  self-signed cert. **Check:** `docker compose config | grep -c certresolver`
  — `0` means broken; `≥ 6` means active.
  **Fix:**
  ```bash
  cd ~/th-middleware/apps/core-platform/deployment
  cp .env.prod.example .env && nano .env          # re-add your secrets
  # (or just prepend the COMPOSE_FILE=... line to your existing .env)
  docker compose config | grep -c certresolver    # expect >= 6
  docker compose up -d                            # recreates traefik + all routed
                                                  # containers so their labels pick
                                                  # up tls.certresolver
  docker compose logs -f traefik | grep -i acme
  ```
- **Cause 1b:** you ran `./manage.sh prod` once (correct), then a bare
  `docker compose up -d` **before** `.env` had `COMPOSE_FILE` — that recreated the
  containers off the base file and stripped the resolver labels. Same fix.
- **Cause 2:** you hand-edited `config/traefik/traefik.yml` or `config/traefik/dynamic/middlewares.yml` — production mounts `traefik.prod.yml` / `dynamic-prod/` instead. Edit those.
- **Cause 3:** port 80 blocked at the GCP firewall (`allow-dlp-web` rule, §1.3). HTTP-01 needs it even though browsers get redirected to 443.
- **Cause 4:** DNS. `./manage.sh prod-ssl` shows which of `dlp` / `auth.dlp` / `ws.dlp` / `traefik.dlp` are `UNRESOLVED`. Traefik requests one cert per hostname; a missing A record fails only that host (and the whole site if it's the apex).
- **Cause 5:** Let's Encrypt rate limit after repeated failures (5/hostname/hour, 50 certs/domain/week). Add `caServer: https://acme-staging-v02.api.letsencrypt.org/directory` under `acme:` in `traefik.prod.yml` while debugging, then remove it and `docker compose exec traefik rm /letsencrypt/acme.json && docker compose restart traefik` for the real cert.
- **Manual verification:**
  ```bash
  docker exec traefik cat /etc/traefik/traefik.yml | grep -A2 Challenge    # httpChallenge?
  docker compose logs traefik | grep -iE 'acme|certificate|challenge|error'
  docker exec traefik sh -c 'cat /letsencrypt/acme.json' | jq '.letsencrypt.Certificates[].domain'
  curl -I http://dlp.tarrinahealth.com/.well-known/acme-challenge/test      # HTTP/1.1 404 from traefik = port 80 reachable
  ```

### Issue 2b: `WARN[0000] The "XXXX" variable is not set. Defaulting to a blank string.`
- **Cause:** a value in `.env` contains a literal `$` that `docker compose` reads as a variable reference (the dev `.env` had `AUTHENTIK_ADMIN_PASSWORD=8Osc&YM$RJ8MlPJ&` → compose expanded `$RJ8MlPJ`).
- **Resolution:** single-quote the value (`FOO='...$RJ8MlPJ...'`) or double the dollar (`$$`). `AUTHENTIK_ADMIN_PASSWORD` is **not used in production** — remove it from `.env`. The hex secrets in §4.2 have no `$`.

### Issue 3: Debezium Connector Shows `FAILED` State
- **Cause:** Debezium attempted snapshotting before Alembic created PostgreSQL mirror tables, or logical replication slot was interrupted.
- **Resolution:**
  ```bash
  # Check failure stacktrace
  docker exec debezium curl -s http://localhost:8083/connectors/zoho-mirror/status | jq .
  # Re-register connector
  ./manage.sh register-debezium
  ```

### Issue 4: Out-Of-Memory (OOM) Container Exits
- **Check OOM events in kernel buffer:**
  ```bash
  sudo dmesg -T | grep -i oom
  ```
- **Resolution:** Verify the 8 GB swapfile is active with `free -h`. Adjust concurrency in `.env`: reduce `CELERY_CONCURRENCY=2` and `WORKERS=2` if necessary.

### Issue 5: `dependency failed to start: container kafka is unhealthy` (but the broker logs say "Kafka Server started")
- **Cause:** the healthcheck runs `kafka-broker-api-versions.sh`, a full JVM that inherits the broker's `KAFKA_HEAP_OPTS=-Xmx1G` — so each probe tries to start a second 1 GB-heap JVM inside the same cgroup and is OOM-killed. The broker itself is fine.
- **Resolution:** already fixed in `docker-compose.yml` — the healthcheck command now prefixes `KAFKA_HEAP_OPTS='-Xmx128m -Xms64m'` and uses `timeout: 20s / retries: 12 / start_period: 90s`. If you see this on an old checkout, `git pull`. Confirm health with:
  ```bash
  docker inspect --format '{{.State.Health.Status}}' kafka
  docker exec kafka bash -c "KAFKA_HEAP_OPTS='-Xmx128m' /opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092" | head -1
  ```

### Issue 6: Frontend loads but every API call is CORS-blocked
- **Cause:** `CORS_ORIGINS` in `.env` doesn't exactly match the browser origin (scheme + host, no trailing slash), or is empty. It is a JSON array.
- **Resolution:** `CORS_ORIGINS=["https://dlp.tarrinahealth.com"]`, then `docker compose up -d backend`.
