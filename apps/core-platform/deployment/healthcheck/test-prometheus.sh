#!/usr/bin/env bash
# ==============================================================================
# Prometheus Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

PROM_PORT="${PROMETHEUS_PORT:-9090}"

section "Prometheus"

# 1. Container running
check "Container running" container_running prometheus

# 2. Health endpoint
check "Healthy (/-/healthy)" \
    curl -sf --max-time 5 "http://localhost:${PROM_PORT}/-/healthy"

# 3. Ready endpoint
check "Ready (/-/ready)" \
    curl -sf --max-time 5 "http://localhost:${PROM_PORT}/-/ready"

# 4. Targets are being scraped
check "Scrape targets configured" bash -c '
    RESP=$(curl -sf --max-time 5 "http://localhost:'"$PROM_PORT"'/api/v1/targets" 2>/dev/null)
    echo "$RESP" | grep -q "activeTargets"
'

# 5. Can execute a query
check "PromQL query execution" bash -c '
    RESP=$(curl -sf --max-time 5 \
        "http://localhost:'"$PROM_PORT"'/api/v1/query?query=up" 2>/dev/null)
    echo "$RESP" | grep -q "success"
'

summary
