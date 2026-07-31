#!/usr/bin/env bash
# ==============================================================================
# reset-db.sh — Backup all databases, destroy postgres_data, restart fresh
# ==============================================================================
# Usage (run from deployment/ directory, or anywhere):
#   ./scripts/reset-db.sh           # base compose
#   ./scripts/reset-db.sh --dev     # dev compose (adds pgadmin, redis-commander…)
#   ./scripts/reset-db.sh --force   # skip confirmation prompt
#
# What it does:
#   1. Starts postgres if not running (needed for backup)
#   2. pg_dump  → backups/pre-reset-<timestamp>/app_db.sql
#                  backups/pre-reset-<timestamp>/authentik.sql
#   3. docker compose down --remove-orphans
#   4. docker volume rm app_postgres_data
#   5. docker compose up -d  (fresh — init scripts re-run)
#
# Restore after reset:
#   docker compose exec -T postgres psql -U postgres -d app_db         < backups/pre-reset-<ts>/app_db.sql
#   docker compose exec -T postgres psql -U postgres -d authentik      < backups/pre-reset-<ts>/authentik.sql
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$DEPLOY_DIR"

COMPOSE_FILE="docker-compose.yml"
DEV_COMPOSE_FILE="docker-compose.dev.yml"
VOLUME_NAME="app_postgres_data"
DEV_MODE=false
FORCE=false

for arg in "$@"; do
    case "$arg" in
        --dev)   DEV_MODE=true ;;
        --force) FORCE=true ;;
    esac
done

# ── Load .env ─────────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo -e "${RED}Error: .env not found. Run from the deployment/ directory.${NC}"
    exit 1
fi
set -a
# shellcheck disable=SC1091
. ".env"
set +a

POSTGRES_DB="${POSTGRES_DB:-app_db}"
POSTGRES_USER="${POSTGRES_USER:-app}"
AUTHENTIK_DB="${AUTHENTIK_DB_NAME:-authentik}"
TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"
BACKUP_DIR="backups/pre-reset-${TIMESTAMP}"

compose_cmd() {
    if [ "$DEV_MODE" = true ]; then
        docker compose -f "$COMPOSE_FILE" -f "$DEV_COMPOSE_FILE" "$@"
    else
        docker compose -f "$COMPOSE_FILE" "$@"
    fi
}

# ── Banner ─────────────────────────────────────────────────────────────────────
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}   PostgreSQL Volume Reset Utility${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo -e "${YELLOW}This will:${NC}"
echo -e "  1. Backup '${POSTGRES_DB}' and '${AUTHENTIK_DB}' to ${BACKUP_DIR}/"
echo -e "  2. Stop all containers  (down --remove-orphans)"
echo -e "  3. Destroy volume:      ${VOLUME_NAME}"
echo -e "  4. Restart containers   (fresh init — scram-sha-256 password hashes)"
echo ""

if [ "$FORCE" = false ]; then
    read -rp "$(echo -e "${YELLOW}Type 'yes' to continue (or pass --force to skip): ${NC}")" confirm
    if [ "$confirm" != "yes" ]; then
        echo -e "${YELLOW}Aborted.${NC}"
        exit 0
    fi
fi

# ── 1. Ensure postgres is available ───────────────────────────────────────────
echo ""
echo -e "${CYAN}[1/5] Ensuring postgres is available for backup...${NC}"
POSTGRES_AVAILABLE=false

if docker compose ps --status running postgres 2>/dev/null | grep -q "postgres"; then
    echo -e "  Postgres is running."
    POSTGRES_AVAILABLE=true
else
    echo -e "  Postgres not running — starting it for backup..."
    docker compose up -d postgres
    echo -n "  Waiting for postgres"
    for i in $(seq 1 30); do
        if docker compose exec -T postgres pg_isready -q 2>/dev/null; then
            echo -e " ${GREEN}ready.${NC}"
            POSTGRES_AVAILABLE=true
            break
        fi
        echo -n "."
        sleep 2
    done
    if [ "$POSTGRES_AVAILABLE" = false ]; then
        echo -e " ${YELLOW}timed out. Skipping backup.${NC}"
    fi
fi

# ── 2. Backup databases ────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[2/5] Creating backups → ${BACKUP_DIR}/${NC}"
mkdir -p "$BACKUP_DIR"

if [ "$POSTGRES_AVAILABLE" = true ]; then
    # Backup app_db
    echo -n "  ${POSTGRES_DB} ... "
    if docker compose exec -T postgres \
        pg_dump -U postgres -d "$POSTGRES_DB" --format=plain \
        > "$BACKUP_DIR/${POSTGRES_DB}.sql" 2>/dev/null \
        && [ -s "$BACKUP_DIR/${POSTGRES_DB}.sql" ]; then
        SIZE=$(du -sh "$BACKUP_DIR/${POSTGRES_DB}.sql" | cut -f1)
        echo -e "${GREEN}✓  ${POSTGRES_DB}.sql  (${SIZE})${NC}"
    else
        rm -f "$BACKUP_DIR/${POSTGRES_DB}.sql"
        echo -e "${YELLOW}⚠  not found or empty — skipped${NC}"
    fi

    # Backup authentik
    echo -n "  ${AUTHENTIK_DB} ... "
    if docker compose exec -T postgres \
        pg_dump -U postgres -d "$AUTHENTIK_DB" --format=plain \
        > "$BACKUP_DIR/${AUTHENTIK_DB}.sql" 2>/dev/null \
        && [ -s "$BACKUP_DIR/${AUTHENTIK_DB}.sql" ]; then
        SIZE=$(du -sh "$BACKUP_DIR/${AUTHENTIK_DB}.sql" | cut -f1)
        echo -e "${GREEN}✓  ${AUTHENTIK_DB}.sql  (${SIZE})${NC}"
    else
        rm -f "$BACKUP_DIR/${AUTHENTIK_DB}.sql"
        echo -e "${YELLOW}⚠  not found or empty — skipped${NC}"
    fi
else
    echo -e "  ${YELLOW}Postgres unavailable — skipping backup.${NC}"
fi

# ── 3. Stop all containers ────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[3/5] Stopping all containers...${NC}"
# Stop both base and dev to catch --remove-orphans from either profile
docker compose -f "$COMPOSE_FILE" -f "$DEV_COMPOSE_FILE" down --remove-orphans 2>/dev/null || \
    docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
echo -e "  ${GREEN}✓ Done.${NC}"

# ── 4. Remove volume ──────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[4/5] Removing volume: ${VOLUME_NAME}...${NC}"
if docker volume ls --quiet | grep -qx "$VOLUME_NAME"; then
    docker volume rm "$VOLUME_NAME"
    echo -e "  ${GREEN}✓ Volume removed.${NC}"
else
    echo -e "  ${YELLOW}Volume not found (already removed or never created).${NC}"
fi

# ── 5. Start fresh ────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[5/5] Starting containers (init scripts will run fresh)...${NC}"
compose_cmd up -d

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   Reset complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

if ls "$BACKUP_DIR"/*.sql &>/dev/null 2>&1; then
    echo -e "Backups:  ${CYAN}${BACKUP_DIR}/${NC}"
    echo ""
    echo -e "To restore (if needed, after postgres is healthy):"
    echo -e "  ${CYAN}cat ${BACKUP_DIR}/${POSTGRES_DB}.sql | docker compose exec -T postgres psql -U postgres -d ${POSTGRES_DB}${NC}"
    echo -e "  ${CYAN}cat ${BACKUP_DIR}/${AUTHENTIK_DB}.sql | docker compose exec -T postgres psql -U postgres -d ${AUTHENTIK_DB}${NC}"
else
    echo -e "${YELLOW}No backups were taken.${NC}"
fi

echo ""
echo -e "${YELLOW}Services may take 30-60s to initialize. Watch with:${NC}"
echo -e "  ${CYAN}docker compose logs -f postgres authentik-server${NC}"
