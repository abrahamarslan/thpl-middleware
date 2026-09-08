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
| **Kafka (KRaft)** | `kafka` | 2 GB | 2.0 | CDC stream broker |
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
In development, the stack uses `mkcert` self-signed local certs via `config/traefik/dynamic/tls.yml`.  
In staging/initial production docs, an `acme-dns` container was referenced. **In production, we use pure ACME HTTP-01**.

#### Why HTTP-01:
1. Eliminates the need to run `acme-dns` on port 53 (which conflicts with Ubuntu's `systemd-resolved`).
2. Eliminates external CNAME delegation setup.
3. Automatically completes validation through Traefik on port 80.

### Configuration File Adjustments on VM

#### 1. Update `config/traefik/traefik.yml`
Configure the `letsencrypt` certResolver to use `httpChallenge` on entryPoint `web`:

```yaml
# apps/core-platform/deployment/config/traefik/traefik.yml
api:
  dashboard: true

ping: {}

entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"
  metrics:
    address: ":8082"

providers:
  docker:
    exposedByDefault: false
    network: app-frontend
  file:
    directory: /etc/traefik/dynamic
    watch: true

log:
  level: INFO
  format: json

accessLog:
  format: json
  fields:
    headers:
      names:
        X-Request-Id: keep

metrics:
  prometheus:
    entryPoint: metrics

certificatesResolvers:
  letsencrypt:
    acme:
      email: devops@tarrinahealth.com     # Replace with valid operational email
      storage: /letsencrypt/acme.json
      httpChallenge:
        entryPoint: web
```

> [!IMPORTANT]
> Traefik automatically intercepts `/.well-known/acme-challenge/` requests on port 80 **before** applying the HTTPS redirect. Never block port 80 at the GCP firewall level.

#### 2. Disable Development `tls.yml`
The file `config/traefik/dynamic/tls.yml` references `mkcert` certificates (`/etc/traefik/certs/local.pem`) which do not exist on the production VM.
Disable it so Traefik does not log file load errors:
```bash
mv config/traefik/dynamic/tls.yml config/traefik/dynamic/tls.yml.disabled
```

#### 3. Update Basic Auth in `config/traefik/dynamic/middlewares.yml`
Generate a fresh, strong password hash for the Traefik dashboard and Flower:
```bash
# Generate apr1 hash:
htpasswd -nbB admin 'YOUR_SECURE_PASSWORD'
# Output format: admin:$2y$05$... or admin:$apr1$...
```
Replace the placeholder user hash in `config/traefik/dynamic/middlewares.yml`:
```yaml
http:
  middlewares:
    dashboard-auth:
      basicAuth:
        users:
          - "admin:<GENERATED_HTPASSWD_HASH>"
```

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

### 4.1 Clone Application Repository
```bash
# Authenticate GitHub CLI
gh auth login --hostname github.com -p https -w

# Clone into user home directory
git clone https://github.com/abrahamarslan/thpl-middleware.git ~/th-middleware
cd ~/th-middleware/apps/core-platform/deployment

# Initialize local production environment file
cp .env.example .env
chmod 600 .env
```

### 4.2 Generate Cryptographic Secrets
Run the following generator to generate high-entropy tokens:

```bash
cat << 'EOF' > generate_secrets.sh
#!/usr/bin/env bash
echo "=== Production Cryptographic Keys ==="
for k in POSTGRES_PASSWORD REDIS_PASSWORD CLICKHOUSE_PASSWORD MEILISEARCH_KEY \
         JWT_SECRET_KEY SOKETI_APP_KEY SOKETI_APP_SECRET AUTHENTIK_DB_PASSWORD \
         AUTHENTIK_SERVICE_TOKEN KAFKA_UI_PASSWORD GRAFANA_ADMIN_PASSWORD; do
    echo "$k=$(openssl rand -hex 32)"
done
echo "AUTHENTIK_SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n')"
EOF
bash generate_secrets.sh
rm generate_secrets.sh
```

### 4.3 Configure Production `.env`
Edit `.env` (`nano .env`) and set the production variables:

```ini
# ==============================================================================
# CORE PLATFORM PRODUCTION CONFIGURATION
# ==============================================================================
ENVIRONMENT=production
DEBUG=false
TZ=UTC

APP_DOMAIN=dlp.tarrinahealth.com
VITE_API_URL=/api
API_PREFIX=/api

# Traefik Ports
TRAEFIK_HTTP_PORT=80
TRAEFIK_HTTPS_PORT=443

# Security & CORS (Must strictly match the domain)
CORS_ORIGINS=["https://dlp.tarrinahealth.com"]
CORS_CREDENTIALS=true

# Database Credentials (paste from secret generation)
POSTGRES_DB=app_db
POSTGRES_USER=app
POSTGRES_PASSWORD=<GENERATED_POSTGRES_PASSWORD>
REDIS_PASSWORD=<GENERATED_REDIS_PASSWORD>
CLICKHOUSE_DB=analytics
CLICKHOUSE_USER=app
CLICKHOUSE_PASSWORD=<GENERATED_CLICKHOUSE_PASSWORD>
MEILISEARCH_KEY=<GENERATED_MEILISEARCH_KEY>

# JWT Authentication
JWT_SECRET_KEY=<GENERATED_JWT_SECRET_KEY>
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24
JWT_REFRESH_EXPIRATION_DAYS=30

# WebSockets (Soketi)
SOKETI_APP_ID=app
SOKETI_APP_KEY=<GENERATED_SOKETI_APP_KEY>
SOKETI_APP_SECRET=<GENERATED_SOKETI_APP_SECRET>

# Authentik IAM
AUTHENTIK_SECRET_KEY=<GENERATED_AUTHENTIK_SECRET_KEY>
AUTHENTIK_DB_NAME=authentik
AUTHENTIK_DB_USER=authentik
AUTHENTIK_DB_PASSWORD=<GENERATED_AUTHENTIK_DB_PASSWORD>
AUTHENTIK_SERVICE_TOKEN=<GENERATED_AUTHENTIK_SERVICE_TOKEN>
AUTHENTIK_LOG_LEVEL=info
AUTHENTIK_EMAIL_HOST=smtp.sendgrid.net   # Real transactional SMTP
AUTHENTIK_EMAIL_PORT=587
AUTHENTIK_EMAIL_USE_TLS=true
AUTHENTIK_EMAIL_FROM=auth@dlp.tarrinahealth.com

# Monitoring & Kafka UI
KAFKA_UI_USERNAME=admin
KAFKA_UI_PASSWORD=<GENERATED_KAFKA_UI_PASSWORD>
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<GENERATED_GRAFANA_ADMIN_PASSWORD>

# Production TLS (ACME HTTP-01)
ACME_EMAIL=devops@tarrinahealth.com

# Zoho Integration (India Data Center: accounts.zoho.in)
ZOHO_CLIENT_ID=<ZOHO_PROD_CLIENT_ID>
ZOHO_CLIENT_SECRET=<ROTATED_ZOHO_CLIENT_SECRET>
ZOHO_REDIRECT_URL=https://dlp.tarrinahealth.com/api/zoho/auth/callback
ZOHO_ACCOUNTS_URL=https://accounts.zoho.in
ZOHO_API_BASE_URL=https://www.zohoapis.in/books/v3
ZOHO_ORGANIZATION_ID=<YOUR_ZOHO_ORG_ID>
ZOHO_REGION=in
ZOHO_BOOKS_API_URL=https://www.zohoapis.in/books/v3
ZOHO_INVENTORY_API_URL=https://www.zohoapis.in/inventory/v1
ZOHO_AUTH_REQUIRE_USER=false          # Set false during initial bootstrap
ZOHO_CALLBACK_REQUIRE_USER=false      # Zoho callback cannot send JWT Authorization header

# Transactional Email (Resend)
RESEND_API_KEY=<YOUR_RESEND_API_KEY>
RESEND_DEFAULT_FROM=DLP <noreply@tarrinahealth.com>
```

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
3. Rotate Client Secret immediately if the prior secret was ever placed in source control.
4. Update `ZOHO_CLIENT_ID` and `ZOHO_CLIENT_SECRET` in `deployment/.env`.

---

## 9. Step 6: Stack Deployment & Execution Ordering

### Important Pre-flight Warnings
> [!CAUTION]
> 1. **Do NOT run `docker-compose.dev.yml` in production.** It publishes raw database ports (5432, 6379, etc.) to the host and disables authentication mechanisms.
> 2. **Do NOT pass `--profile production`.** That profile starts `acmedns` which binds to port 53 and crashes against Ubuntu's resolver.
> 3. **Database credentials are immutable after first launch.** Docker volumes (`postgres_data`, `redis_data`, `clickhouse_data`) initialize user passwords on initial container run. Changing passwords in `.env` afterwards will break service connections unless volumes are reset.

### 9.1 Pre-flight Validation
Check that Compose parses the base and production files without errors:
```bash
cd ~/th-middleware/apps/core-platform/deployment
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
```

### 9.2 Launch the Production Stack
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
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
```

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
2. **Authentik Admin Initialization:**
   - Navigate to: `https://auth.dlp.tarrinahealth.com/if/flow/initial-setup/`
   - Default administrative username is `akadmin`.
   - Set a strong master administrative password.
3. **Traefik Dashboard:**
   - Navigate to: `https://traefik.dlp.tarrinahealth.com/dashboard/` *(Notice the trailing slash)*
   - Login with your `admin` username and the basic-auth password configured in `middlewares.yml`.
   - Verify green status on all routers and ACME TLS certificate status.
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

# 1. Rebuild application images (Docker BuildKit caches unchanged layers)
docker compose -f docker-compose.yml -f docker-compose.prod.yml build backend celery-worker frontend

# 2. Rolling update of backend & frontend without terminating databases
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps backend celery-worker celery-beat frontend

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
WorkingDirectory=/home/a2/th-middleware/apps/core-platform/deployment
ExecStart=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.prod.yml stop
TimeoutStartSec=0
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```

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

### Issue 2: Let's Encrypt Certificate Pending or Untrusted Warning
- **Cause 1:** Traefik dashboard router did not declare `traefik.http.routers.dashboard.tls.certresolver: letsencrypt`.
- **Cause 2:** Port 80 is blocked by GCP firewall, preventing Let's Encrypt HTTP-01 challenge completion.
- **Cause 3:** DNS A records do not match the public IP.
- **Check ACME Logs:**
  ```bash
  docker compose logs traefik | grep -i acme
  ```

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
