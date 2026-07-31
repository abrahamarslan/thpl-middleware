#!/usr/bin/env bash
# ==============================================================================
# Redis Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

REDIS_PASS="${REDIS_PASSWORD:-}"

# Build auth flag
AUTH_FLAG=""
if [ -n "$REDIS_PASS" ]; then
    AUTH_FLAG="-a $REDIS_PASS --no-auth-warning"
fi

redis_cli() {
    # shellcheck disable=SC2086
    docker exec redis redis-cli $AUTH_FLAG "$@"
}

section "Redis"

# 1. Container running
check "Container running" container_running redis

# 2. PING → PONG
check "PING → PONG" bash -c '
    RESP=$(docker exec redis redis-cli '"$AUTH_FLAG"' PING 2>/dev/null)
    [ "$RESP" = "PONG" ]
'

# 3. SET / GET round-trip on DB 0 (application)
check "DB 0 SET/GET round-trip" bash -c '
    docker exec redis redis-cli '"$AUTH_FLAG"' -n 0 SET _healthcheck_test "ok" EX 10 >/dev/null 2>&1
    RESP=$(docker exec redis redis-cli '"$AUTH_FLAG"' -n 0 GET _healthcheck_test 2>/dev/null)
    docker exec redis redis-cli '"$AUTH_FLAG"' -n 0 DEL _healthcheck_test >/dev/null 2>&1
    [ "$RESP" = "ok" ]
'

# 4. DB 1 is accessible (Authentik uses it)
check "DB 1 accessible (Authentik)" bash -c '
    docker exec redis redis-cli '"$AUTH_FLAG"' -n 1 SET _healthcheck_test "ok" EX 10 >/dev/null 2>&1
    RESP=$(docker exec redis redis-cli '"$AUTH_FLAG"' -n 1 GET _healthcheck_test 2>/dev/null)
    docker exec redis redis-cli '"$AUTH_FLAG"' -n 1 DEL _healthcheck_test >/dev/null 2>&1
    [ "$RESP" = "ok" ]
'

# 5. Memory usage is sane (< 80% of maxmemory if set)
check "Memory usage sane" bash -c '
    INFO=$(docker exec redis redis-cli '"$AUTH_FLAG"' INFO memory 2>/dev/null)
    USED=$(echo "$INFO" | grep "used_memory:" | tr -d "\r" | cut -d: -f2)
    MAX=$(echo "$INFO" | grep "maxmemory:" | tr -d "\r" | cut -d: -f2)
    if [ "${MAX:-0}" -eq 0 ]; then exit 0; fi  # no limit set
    [ "$USED" -lt $((MAX * 80 / 100)) ]
'

# 6. Connected clients count
check "Client connections < 100" bash -c '
    CLIENTS=$(docker exec redis redis-cli '"$AUTH_FLAG"' INFO clients 2>/dev/null | grep "connected_clients:" | tr -d "\r" | cut -d: -f2)
    [ "${CLIENTS:-0}" -lt 100 ]
'

summary
