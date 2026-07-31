#!/usr/bin/env bash
# ==============================================================================
# ClickHouse Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

CH_PORT="${CLICKHOUSE_HTTP_PORT:-8123}"
CH_PASS="${CLICKHOUSE_PASSWORD:-clickhouse_password}"

section "ClickHouse"

# 1. Container running
check "Container running" container_running clickhouse

# 2. HTTP ping endpoint
check "HTTP /ping responds" \
    curl -sf --max-time 5 "http://localhost:${CH_PORT}/ping"

# 3. Query execution
check "Query execution (SELECT 1)" bash -c '
    RESP=$(curl -sf --max-time 5 "http://localhost:'"$CH_PORT"'/?query=SELECT+1" \
        -u "admin:'"$CH_PASS"'")
    [ "$(echo "$RESP" | tr -d "\n ")" = "1" ]
'

# 4. Analytics database exists
check "Database 'analytics' exists" bash -c '
    RESP=$(curl -sf --max-time 5 \
        "http://localhost:'"$CH_PORT"'/?query=SELECT+name+FROM+system.databases+WHERE+name%3D%27analytics%27" \
        -u "admin:'"$CH_PASS"'")
    echo "$RESP" | grep -q "analytics"
'

# 5. Tables exist
check "Table api_request_logs exists" bash -c '
    RESP=$(curl -sf --max-time 5 \
        "http://localhost:'"$CH_PORT"'/?query=EXISTS+analytics.api_request_logs" \
        -u "admin:'"$CH_PASS"'")
    [ "$(echo "$RESP" | tr -d "\n ")" = "1" ]
'

check "Table system_events exists" bash -c '
    RESP=$(curl -sf --max-time 5 \
        "http://localhost:'"$CH_PORT"'/?query=EXISTS+analytics.system_events" \
        -u "admin:'"$CH_PASS"'")
    [ "$(echo "$RESP" | tr -d "\n ")" = "1" ]
'

# 6. System health (uptime > 0)
check "Server uptime > 0" bash -c '
    RESP=$(curl -sf --max-time 5 \
        "http://localhost:'"$CH_PORT"'/?query=SELECT+uptime()" \
        -u "admin:'"$CH_PASS"'")
    [ "${RESP:-0}" -gt 0 ]
'

summary
