#!/usr/bin/env bash
# ==============================================================================
# Frontend Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

FE_PORT="${FRONTEND_PORT:-5173}"
DOMAIN="${APP_DOMAIN:-app.local}"

section "Frontend"

# 1. Container running
check "Container running" container_running frontend

# 2. Direct access (port varies: 5173 for dev Vite, 3000/80 for prod nginx)
check "Direct HTTP response" bash -c '
    curl -sf --max-time 5 "http://localhost:'"$FE_PORT"'/" >/dev/null 2>&1 || \
    curl -sf --max-time 5 "http://localhost:3000/" >/dev/null 2>&1 || \
    curl -sf --max-time 5 "http://localhost:80/" >/dev/null 2>&1
'

# 3. Via Traefik (HTTPS)
check "Via Traefik (HTTPS)" \
    curl -sfk --max-time 10 "https://localhost:${TRAEFIK_HTTPS_PORT:-443}/" \
    --resolve "${DOMAIN}:${TRAEFIK_HTTPS_PORT:-443}:127.0.0.1" \
    -H "Host: ${DOMAIN}"

# 4. Returns HTML (not error page)
check "Returns HTML content" bash -c '
    RESP=$(curl -sfk --max-time 10 "https://localhost:'"${TRAEFIK_HTTPS_PORT:-443}"'/" \
        --resolve "'"${DOMAIN}"':'"${TRAEFIK_HTTPS_PORT:-443}"':127.0.0.1" \
        -H "Host: '"${DOMAIN}"'" 2>/dev/null || true)
    echo "$RESP" | grep -qi "html"
'

summary
