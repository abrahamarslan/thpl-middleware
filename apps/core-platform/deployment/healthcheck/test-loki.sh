#!/usr/bin/env bash
# ==============================================================================
# Loki Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

LOKI_PORT="${LOKI_PORT:-3100}"

section "Loki"

# 1. Container running
check "Container running" container_running loki

# 2. Ready endpoint
check "Ready (/ready)" \
    curl -sf --max-time 5 "http://localhost:${LOKI_PORT}/ready"

# 3. Can query labels
check "Label query (/loki/api/v1/labels)" bash -c '
    HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" --max-time 5 \
        "http://localhost:'"$LOKI_PORT"'/loki/api/v1/labels" 2>/dev/null || echo "000")
    [ "$HTTP_CODE" = "200" ]
'

# 4. Build info
check "Build info endpoint" \
    curl -sf --max-time 5 "http://localhost:${LOKI_PORT}/loki/api/v1/status/buildinfo"

summary
