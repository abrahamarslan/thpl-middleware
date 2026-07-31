#!/usr/bin/env bash
# ==============================================================================
# Observability pipeline healthcheck (Loki, Tempo, Alloy)
# Checks run from inside the backend container — these services do not
# publish host ports in the base compose file.
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

section "Observability (Loki / Tempo / Alloy)"

check "Loki container running"  container_running loki
check "Tempo container running" container_running tempo
check "Alloy container running" container_running alloy

check "Loki ready" \
    docker exec backend curl -sf http://loki:3100/ready

check "Tempo ready" \
    docker exec backend curl -sf http://tempo:3200/ready

check "Alloy ready" \
    docker exec backend curl -sf http://alloy:12345/-/ready

check "Loki is receiving container logs" bash -c '
    RESULT=$(docker exec backend curl -sf -G "http://loki:3100/loki/api/v1/query" \
        --data-urlencode "query=count_over_time({container=~\".+\"}[10m])" 2>/dev/null)
    echo "$RESULT" | grep -q "\"status\":\"success\""
'

summary
