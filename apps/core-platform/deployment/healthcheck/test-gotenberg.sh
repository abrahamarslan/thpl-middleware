#!/usr/bin/env bash
# ==============================================================================
# Gotenberg (PDF Generation) Healthcheck
# ==============================================================================
# Gotenberg publishes NO host port — it lives on the isolated app-pdf network.
# All checks therefore run from inside the backend container, and we also
# verify the isolation itself (no published ports on the gotenberg container).
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

section "Gotenberg (PDF Generation)"

# 1. Container running
check "Container running" container_running gotenberg

# 2. Isolation: no host ports published
check "No host ports published (isolation)" bash -c '
    PORTS=$(docker inspect --format "{{json .NetworkSettings.Ports}}" gotenberg)
    ! echo "$PORTS" | grep -q "HostPort"
'

# 3. Reachable from the backend (the only allowed consumer)
check "Health endpoint reachable from backend" \
    docker exec backend curl -sf --max-time 5 "http://gotenberg:3000/health"

# 4. Chromium module renders
check "Chromium module responsive" bash -c '
    HTTP_CODE=$(docker exec backend sh -c "
        echo \"<h1>healthcheck</h1>\" > /tmp/index.html &&
        curl -s -o /dev/null -w \"%{http_code}\" --max-time 15 \
            -X POST http://gotenberg:3000/forms/chromium/convert/html \
            -F files=@/tmp/index.html
    " 2>/dev/null || echo "000")
    [ "$HTTP_CODE" = "200" ]
'

summary
