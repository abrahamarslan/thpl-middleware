#!/usr/bin/env bash
# ==============================================================================
# Docker Management Script (Linux/macOS)
# ==============================================================================
# Usage: ./manage.sh <command> [args]
# Run from the deployment/ directory.
# ==============================================================================

set -euo pipefail

# Internal names — deliberately NOT "COMPOSE_FILE", which is Compose's own env
# var and may be set inside .env (some subcommands `source` .env).
BASE_COMPOSE="docker-compose.yml"
DEV_COMPOSE="docker-compose.dev.yml"
PROD_COMPOSE="docker-compose.prod.yml"
PROD_ENV_FILE=".env.prod"

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

PRODUCTION  (base + docker-compose.prod.yml; Let's Encrypt HTTP-01)
  prod               Build + up -d with the production overrides
  prod-stop          Stop production services
  prod-logs [svc]    Tail production logs
  prod-migrate       alembic upgrade head (production env)
  prod-build [svc]   Build image(s) with the production overrides
  prod-config [svc]  Render the fully-interpolated production compose config
  prod-ssl           Diagnose Let's Encrypt / TLS (DNS, :80, acme.json, live cert)
  register-acmedns   Register a domain with the acme-dns server (DNS-01 only)

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
    docker compose -f "$BASE_COMPOSE" -f "$DEV_COMPOSE" "$@"
}

prod_compose() {
    # Production ALWAYS layers base + prod overrides. The prod override is what
    # supplies the Let's Encrypt HTTP-01 resolver and the tls.certresolver
    # labels — deploy without it and Traefik only serves a self-signed cert
    # ("your connection is not private" / "site does not support HTTPS").
    #
    # Env file: prefer .env.prod, else the default .env. (On the VM the simplest
    # setup is to name the prod env file `.env` — then bare `docker compose`
    # commands also pick up COMPOSE_FILE and work without any -f flags.)
    local env_args=()
    if [ -f "$PROD_ENV_FILE" ]; then
        env_args=(--env-file "$PROD_ENV_FILE")
    elif [ ! -f ".env" ]; then
        echo -e "${RED}No $PROD_ENV_FILE and no .env found. Run: cp .env.prod.example .env && nano .env${NC}" >&2
        exit 1
    fi
    # Only activate the 'production' profile if acme-dns (DNS-01) is explicitly
    # requested. HTTP-01 (the default) does not need the acmedns container.
    local profile_args=()
    [ "${ACMEDNS_ENABLED:-false}" = "true" ] && profile_args=(--profile production)
    docker compose "${env_args[@]}" -f "$BASE_COMPOSE" -f "$PROD_COMPOSE" "${profile_args[@]}" "$@"
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
        prod_compose up -d --build --remove-orphans
        echo ""
        echo -e "${CYAN}Stack is up. TLS certificates are issued automatically by"
        echo -e "Traefik on the first HTTPS request to each host — no manual step."
        echo -e "Check progress:${NC}  ./manage.sh prod-ssl"
        ;;
    prod-stop)
        prod_compose stop
        ;;
    prod-logs)
        if [ -n "$ARG1" ]; then
            prod_compose logs -f --tail=100 "$ARG1"
        else
            prod_compose logs -f --tail=100
        fi
        ;;
    prod-migrate)
        echo -e "${CYAN}Running alembic upgrade head (production)...${NC}"
        prod_compose exec backend alembic upgrade head
        ;;
    prod-build)
        if [ -n "$ARG1" ]; then
            prod_compose build "$ARG1"
        else
            prod_compose build
        fi
        ;;
    prod-config)
        # Render the fully-interpolated production config (preflight check).
        if [ -n "$ARG1" ]; then prod_compose config "$ARG1"; else prod_compose config; fi
        ;;
    prod-ssl)
        # Diagnose Let's Encrypt / TLS state for the production domain.
        set +e +o pipefail   # diagnostic: never abort on a failing probe
        ENVF=".env.prod"; [ -f "$ENVF" ] || ENVF=".env"
        DOMAIN="$(grep -E '^APP_DOMAIN=' "$ENVF" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'\'' ')"
        [ -n "$DOMAIN" ] || { echo -e "${RED}APP_DOMAIN not found in $ENVF${NC}"; exit 1; }
        echo -e "${CYAN}Domain: $DOMAIN  (from $ENVF)${NC}"
        echo -e "${CYAN}== DNS ==${NC}"
        for h in "$DOMAIN" "auth.$DOMAIN" "ws.$DOMAIN" "traefik.$DOMAIN"; do
            ip="$(getent hosts "$h" 2>/dev/null | awk '{print $1}' | head -1)"
            printf '  %-34s %b\n' "$h" "${ip:-${RED}UNRESOLVED${NC}}"
        done
        echo -e "${CYAN}== Port 80 ACME challenge path (want HTTP 404 from Traefik) ==${NC}"
        curl -s -o /dev/null -m 5 -w '  HTTP %{http_code} from %{remote_ip}\n' \
            "http://$DOMAIN/.well-known/acme-challenge/probe" || echo "  unreachable on :80"
        echo -e "${CYAN}== Issued certificates (acme.json) ==${NC}"
        docker exec traefik cat /letsencrypt/acme.json 2>/dev/null \
            | jq -r '.letsencrypt.Certificates[]? | "  " + (.domain.main) + (if .domain.sans then " " + (.domain.sans|join(",")) else "" end)' 2>/dev/null \
            || echo "  none yet (or traefik not running / jq missing)"
        echo -e "${CYAN}== Live certificate on :443 ==${NC}"
        echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null \
            | openssl x509 -noout -issuer -subject -dates 2>/dev/null | sed 's/^/  /' \
            || echo "  handshake failed"
        echo -e "${CYAN}== Recent Traefik ACME log lines ==${NC}"
        prod_compose logs --tail=200 traefik 2>/dev/null \
            | grep -iE 'acme|certificate|challenge|unable|error' | tail -20 | sed 's/^/  /' || true
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
