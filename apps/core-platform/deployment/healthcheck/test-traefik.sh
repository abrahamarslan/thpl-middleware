#!/usr/bin/env bash
# ==============================================================================
# Traefik Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

DOMAIN="${APP_DOMAIN:-app.local}"

section "Traefik Reverse Proxy"

# 1. Container running
check "Container running" container_running traefik

# 2. Traefik internal healthcheck
check "Traefik healthcheck" \
    docker exec traefik traefik healthcheck

# 3. HTTP → HTTPS redirect (port 80 → 443)
check "HTTP→HTTPS redirect" \
    curl -sf -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:${TRAEFIK_HTTP_PORT:-80}/" | grep -qE '301|302|308'

# 4. HTTPS responds on 443 (self-signed cert ok for dev)
check "HTTPS endpoint responds" \
    curl -sfk -o /dev/null --max-time 5 "https://localhost:${TRAEFIK_HTTPS_PORT:-443}/"

# 5. Dashboard accessible
check "Dashboard route exists" \
    curl -sfk -o /dev/null --max-time 5 "https://traefik.${DOMAIN}/dashboard/" \
    --resolve "traefik.${DOMAIN}:${TRAEFIK_HTTPS_PORT:-443}:127.0.0.1"

summary
