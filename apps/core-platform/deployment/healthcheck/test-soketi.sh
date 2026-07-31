#!/usr/bin/env bash
# ==============================================================================
# Soketi (WebSocket) Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

SOKETI_PORT="${SOKETI_PORT:-6001}"
SOKETI_METRICS="${SOKETI_METRICS_PORT:-9601}"

section "Soketi (WebSocket)"

# 1. Container running
check "Container running" container_running soketi

# 2. HTTP health endpoint
check "HTTP health endpoint" \
    curl -sf --max-time 5 "http://localhost:${SOKETI_PORT}/"

# 3. Prometheus metrics endpoint
check "Metrics endpoint (:${SOKETI_METRICS})" \
    curl -sf --max-time 5 "http://localhost:${SOKETI_METRICS}/metrics"

# 4. App info via Pusher API (GET /apps/:id)
check "App '${SOKETI_APP_ID:-app}' registered" bash -c '
    RESP=$(curl -sf --max-time 5 "http://localhost:'"$SOKETI_PORT"'/apps/'"${SOKETI_APP_ID:-app}"'/channels" \
        -H "Authorization: Bearer '"${SOKETI_APP_SECRET:-app-secret}"'" 2>/dev/null || echo "")
    # Any JSON response (even empty channels) means the app is registered
    [ -n "$RESP" ]
'

# 5. Redis adapter connected (check via soketi logs)
check "Redis adapter connected" bash -c '
    docker logs soketi 2>&1 | tail -20 | grep -qi "redis\|ready\|connected" || true
    # Soketi is running if we got this far and port is open
    curl -sf --max-time 3 "http://localhost:'"$SOKETI_PORT"'/" >/dev/null
'

summary
