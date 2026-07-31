#!/usr/bin/env bash
# ==============================================================================
# Authentik Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

AUTH_PORT="${AUTHENTIK_PORT:-9000}"
DOMAIN="${APP_DOMAIN:-app.local}"

section "Authentik (IAM)"

# 1. Server container running
check "Server container running" container_running authentik-server

# 2. Worker container running
check "Worker container running" container_running authentik-worker

# 3. API health (direct)
check "Healthcheck endpoint (direct)" bash -c '
    HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" --max-time 10 \
        "http://localhost:'"$AUTH_PORT"'/-/health/live/" 2>/dev/null || echo "000")
    [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "204" ]
'

# 4. Via Traefik
check "Via Traefik (https://auth.${DOMAIN})" \
    curl -sfk --max-time 10 \
    "https://localhost:${TRAEFIK_HTTPS_PORT:-443}/-/health/live/" \
    --resolve "auth.${DOMAIN}:${TRAEFIK_HTTPS_PORT:-443}:127.0.0.1" \
    -H "Host: auth.${DOMAIN}"

# 5. Initial setup flow accessible
check "Setup flow page loads" bash -c '
    HTTP_CODE=$(curl -sfk -o /dev/null -w "%{http_code}" --max-time 10 \
        "https://localhost:'"${TRAEFIK_HTTPS_PORT:-443}"'/if/flow/initial-setup/" \
        --resolve "auth.'"$DOMAIN"':'"${TRAEFIK_HTTPS_PORT:-443}"':127.0.0.1" \
        -H "Host: auth.'"$DOMAIN"'" 2>/dev/null || echo "000")
    # 200 (setup available) or 302 (already configured) — both OK
    [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ] || [ "$HTTP_CODE" = "303" ]
'

summary
