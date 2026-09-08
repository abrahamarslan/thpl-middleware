#!/usr/bin/env bash
# ==============================================================================
# Docker Management Script (Linux/macOS)
# ==============================================================================
# Usage: ./manage.sh <command> [args]
# Run from the deployment/ directory.
# ==============================================================================

set -euo pipefail

COMPOSE_FILE="docker-compose.yml"
DEV_COMPOSE_FILE="docker-compose.dev.yml"
PROD_COMPOSE_FILE="docker-compose.prod.yml"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

show_help() {
    cat <<'EOF'
Docker Management
==================

BASE
  start              docker compose up -d
  stop               docker compose stop
  down               docker compose down (keeps volumes)
  restart            docker compose restart
  ps                 Show running containers
  logs [service]     Tail logs (all or specific service)
  build [service]    Rebuild image(s)

PRODUCTION  (ACME TLS via acme-dns CNAME delegation)
  prod               docker compose up with production overrides
  prod-stop          Stop production services
  prod-logs          Tail production logs
  register-acmedns   Register a domain with the acme-dns server

DEVELOPMENT  (adds pgAdmin, Redis Commander, MailHog, Vite HMR)
  dev                docker compose up with dev overrides
  dev-build          Tear down + wipe node_modules volume, rebuild images, start
  dev-prod           docker compose up (base/production, no dev overrides)
  dev-stop           Stop dev services
  dev-logs           Tail dev logs

EXEC HELPERS  (run commands inside a container)
  shell-backend      Open bash in backend container
  shell-frontend     Open sh in frontend container
  shell-postgres     Open psql in postgres container

ALEMBIC  (run inside backend container)
  migrate            alembic upgrade head
  makemig [msg]      Generate a new migration

NODE / FRONTEND
  npm [cmd]          Run npm command in frontend container

DATABASE
  db-backup          Create a SQL dump backup of app_db
  db-restore <file>  Restore database from SQL dump
  reset-db [--dev]   Backup all DBs then reset the postgres_data volume (one command)
                     Pass --dev when running in dev mode

DEBEZIUM (CDC)
  register-debezium  Register/update the zoho-mirror Postgres connector
  debezium-status    Show connector list + status

ENV SYNC (backend/.env  <->  deployment/.env)
  sync-env [args]    Sync shared env vars between the two .env files.
                     Default: dry-run report (source = backend/.env). Use
                     --apply to write, --from docker to invert the source,
                     --diff/--json for other views. See scripts/sync-env.sh.

AUTHENTIK (IAM user sync)
  authentik-backfill Link/create Authentik users for local users missing a link
                     (runs synchronously inside the backend container)

HEALTHCHECK
  healthcheck        Run full service healthcheck suite

MAINTENANCE
  clean              Remove stopped containers + dangling images
  prune              Deep clean (WARNING: removes unnamed volumes)
  fix-perms          Fix file permissions for Linux deployment

SSL
  setup-ssl          Generate mkcert dev certificates

EXAMPLES
  ./manage.sh dev
  ./manage.sh prod
  ./manage.sh logs backend
  ./manage.sh shell-backend
  ./manage.sh migrate
  ./manage.sh npm "run build"
EOF
}

compose() {
    docker compose "$@"
}

dev_compose() {
    docker compose -f "$COMPOSE_FILE" -f "$DEV_COMPOSE_FILE" "$@"
}

prod_compose() {
    # Only activate the 'production' profile if acme-dns is explicitly requested.
    # HTTP-01 challenges (default) do not require the acmedns container on port 53.
    if [ "${ACMEDNS_ENABLED:-false}" = "true" ]; then
        docker compose -f "$COMPOSE_FILE" -f "$PROD_COMPOSE_FILE" --profile production "$@"
    else
        docker compose -f "$COMPOSE_FILE" -f "$PROD_COMPOSE_FILE" "$@"
    fi
}

COMMAND="${1:-help}"
ARG1="${2:-}"

case "$COMMAND" in
    help)
        show_help
        ;;

    # -- Production ---------------------------------------------------------------
    start)
        compose up -d
        ;;
    stop)
        compose stop
        ;;
    down)
        compose down --remove-orphans
        ;;
    restart)
        compose restart
        ;;
    ps)
        compose ps
        ;;
    logs)
        if [ -n "$ARG1" ]; then
            compose logs -f --tail=100 "$ARG1"
        else
            compose logs -f --tail=100
        fi
        ;;
    build)
        if [ -n "$ARG1" ]; then
            compose build --no-cache "$ARG1"
        else
            compose build --no-cache
        fi
        ;;

    # -- Production (ACME) --------------------------------------------------------
    prod)
        prod_compose up -d
        ;;
    prod-stop)
        prod_compose stop
        ;;
    prod-logs)
        prod_compose logs -f --tail=100
        ;;

    # -- acme-dns registration ---------------------------------------------------
    register-acmedns)
        [ -f .env ] && set -a && . .env && set +a
        PORT="${ACMEDNS_API_PORT:-8053}"
        echo -e "${CYAN}Registering with acme-dns at http://localhost:$PORT ...${NC}"
        RESPONSE=$(curl -s -X POST "http://localhost:$PORT/register")
        echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
        FULLDOMAIN=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['fulldomain'])" 2>/dev/null || true)
        echo ""
        echo -e "${YELLOW}Next steps:${NC}"
        echo -e "${YELLOW}  1. Create a CNAME record in your DNS registrar:${NC}"
        echo -e "${YELLOW}       _acme-challenge.yourdomain.com  ->  $FULLDOMAIN${NC}"
        echo -e "${YELLOW}  2. Save the output to backend/traefik/acmedns/acmedns.json${NC}"
        echo -e "${YELLOW}     See Architecture.md for the exact JSON format required.${NC}"
        ;;

    # -- Development --------------------------------------------------------------
    dev)
        # --build: rebuilds only changed layers (fast via cache). Ensures the
        # correct node development image is always used — never a stale nginx.
        dev_compose up -d --build --remove-orphans
        ;;
    dev-build)
        # Nuclear reset: tear down all containers + named volumes (wipes
        # node_modules, venv, etc.) then rebuild from scratch.
        dev_compose down --remove-orphans -v 2>/dev/null || true
        dev_compose up -d --build --remove-orphans
        ;;
    dev-prod)
        # Run the base (production) compose without dev overrides.
        compose up -d --remove-orphans
        ;;
    dev-stop)
        dev_compose stop
        ;;
    dev-logs)
        dev_compose logs -f --tail=100
        ;;

    # -- Exec helpers -------------------------------------------------------------
    shell-backend)
        compose exec backend bash
        ;;
    shell-frontend)
        compose exec frontend sh
        ;;
    shell-postgres)
        # shellcheck disable=SC1091
        [ -f .env ] && set -a && . .env && set +a
        compose exec postgres psql -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-app_db}"
        ;;

    # -- Alembic ------------------------------------------------------------------
    migrate)
        echo -e "${CYAN}Running alembic upgrade head...${NC}"
        compose exec backend alembic upgrade head
        ;;
    makemig)
        msg="${ARG1:-auto_migration}"
        echo -e "${CYAN}Generating migration: $msg${NC}"
        compose exec backend alembic revision --autogenerate -m "$msg"
        ;;

    # -- Node / Frontend ----------------------------------------------------------
    npm)
        if [ -n "$ARG1" ]; then
            compose exec frontend npm $ARG1
        else
            echo -e "${YELLOW}Usage: ./manage.sh npm \"run build\"${NC}"
        fi
        ;;

    # -- Database -----------------------------------------------------------------
    reset-db)
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        bash "$SCRIPT_DIR/scripts/reset-db.sh" ${ARG1:+"$ARG1"}
        ;;
    db-backup)
        # shellcheck disable=SC1091
        [ -f .env ] && set -a && . .env && set +a
        BACKUP_FILE="backups/backup_$(date +%Y-%m-%d_%H-%M-%S).sql"
        mkdir -p backups
        echo -e "${CYAN}Creating backup: $BACKUP_FILE${NC}"
        compose exec -T postgres pg_dump -U "${POSTGRES_USER:-app}" "${POSTGRES_DB:-app_db}" > "$BACKUP_FILE"
        echo -e "${GREEN}Backup created: $BACKUP_FILE${NC}"
        ;;
    db-restore)
        if [ -z "$ARG1" ]; then
            echo -e "${RED}Usage: ./manage.sh db-restore <file>${NC}"
            exit 1
        fi
        # shellcheck disable=SC1091
        [ -f .env ] && set -a && . .env && set +a
        echo -e "${YELLOW}Restoring database from: $ARG1${NC}"
        cat "$ARG1" | compose exec -T postgres psql -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-app_db}"
        echo -e "${GREEN}Database restored!${NC}"
        ;;

    # -- Debezium (CDC) -----------------------------------------------------------
    register-debezium)
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        bash "$SCRIPT_DIR/scripts/register-debezium.sh" ${ARG1:+"$ARG1"}
        ;;
    debezium-status)
        docker exec debezium curl -s http://localhost:8083/connectors | python3 -m json.tool || true
        docker exec debezium curl -s "http://localhost:8083/connectors/${ARG1:-zoho-mirror}/status" | python3 -m json.tool || true
        ;;

    # -- Authentik (IAM user sync) ----------------------------------------------
    authentik-backfill)
        echo -e "${CYAN}Backfilling Authentik users (link or create)...${NC}"
        compose exec backend python -c "from app.tasks.authentik import backfill; print(backfill())"
        ;;

    # -- Env sync ---------------------------------------------------------------
    sync-env)
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        shift
        bash "$SCRIPT_DIR/scripts/sync-env.sh" "$@"
        ;;

    # -- Healthcheck ------------------------------------------------------------
    healthcheck)
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        bash "$SCRIPT_DIR/healthcheck/test-all.sh"
        ;;

    # -- Maintenance --------------------------------------------------------------
    # -- SSL -------------------------------------------------------------------
    setup-ssl)
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        bash "$SCRIPT_DIR/scripts/setup-ssl.sh" "${APP_DOMAIN:-app.local}"
        ;;

    fix-perms)
        echo -e "${CYAN}Fixing file permissions for Linux...${NC}"
        find . -name "*.sh" -exec chmod +x {} \;
        find ./backend -name "entrypoint.sh" -exec chmod +x {} \;
        echo -e "${GREEN}Permissions fixed.${NC}"
        ;;
    clean)
        compose down --remove-orphans
        docker image prune -f
        ;;
    prune)
        echo -e "${RED}WARNING: This removes all unnamed volumes!${NC}"
        read -rp "Type 'yes' to confirm: " confirm
        if [ "$confirm" = "yes" ]; then
            compose down -v --remove-orphans
            docker system prune -f
        else
            echo -e "${YELLOW}Aborted.${NC}"
        fi
        ;;

    *)
        echo -e "${RED}Unknown command: $COMMAND${NC}"
        show_help
        exit 1
        ;;
esac
