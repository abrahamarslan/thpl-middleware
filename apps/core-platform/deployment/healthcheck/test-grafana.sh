#!/usr/bin/env bash
# ==============================================================================
# Grafana Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

GF_PORT="${GRAFANA_PORT:-3001}"
GF_USER="${GRAFANA_ADMIN_USER:-admin}"
GF_PASS="${GRAFANA_ADMIN_PASSWORD:-admin123}"

section "Grafana"

# 1. Container running
check "Container running" container_running grafana

# 2. API health
check "Health endpoint (/api/health)" \
    curl -sf --max-time 5 "http://localhost:${GF_PORT}/api/health"

# 3. Login works
check "Admin login (API key test)" bash -c '
    HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" --max-time 5 \
        -u "'"$GF_USER"':'"$GF_PASS"'" \
        "http://localhost:'"$GF_PORT"'/api/org" 2>/dev/null || echo "000")
    [ "$HTTP_CODE" = "200" ]
'

# 4. Datasources provisioned
check "Datasources provisioned" bash -c '
    RESP=$(curl -sf --max-time 5 \
        -u "'"$GF_USER"':'"$GF_PASS"'" \
        "http://localhost:'"$GF_PORT"'/api/datasources" 2>/dev/null)
    # Check that at least one datasource exists
    [ "$(echo "$RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)" -gt 0 ]
'

# 5. Redis datasource plugin installed
check "Redis datasource plugin" bash -c '
    RESP=$(curl -sf --max-time 5 \
        -u "'"$GF_USER"':'"$GF_PASS"'" \
        "http://localhost:'"$GF_PORT"'/api/plugins" 2>/dev/null)
    echo "$RESP" | grep -q "redis-datasource"
'

summary
