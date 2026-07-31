#!/usr/bin/env bash
# ==============================================================================
# MeiliSearch Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

MS_PORT="${MEILISEARCH_PORT:-7700}"
MS_KEY="${MEILISEARCH_KEY:-masterkey}"

section "MeiliSearch"

# 1. Container running
check "Container running" container_running meilisearch

# 2. Health endpoint
check "Health endpoint (/health)" \
    curl -sf --max-time 5 "http://localhost:${MS_PORT}/health"

# 3. Authentication works
check "API key authentication" bash -c '
    RESP=$(curl -sf --max-time 5 -H "Authorization: Bearer '"$MS_KEY"'" \
        "http://localhost:'"$MS_PORT"'/version")
    echo "$RESP" | grep -q "pkgVersion"
'

# 4. Can create and query a test index
check "Index CRUD (create/query/delete)" bash -c '
    # Create test index
    curl -sf --max-time 5 -X POST \
        -H "Authorization: Bearer '"$MS_KEY"'" \
        -H "Content-Type: application/json" \
        -d "{\"uid\": \"_healthcheck_test\", \"primaryKey\": \"id\"}" \
        "http://localhost:'"$MS_PORT"'/indexes" >/dev/null

    sleep 1

    # Verify index exists
    curl -sf --max-time 5 \
        -H "Authorization: Bearer '"$MS_KEY"'" \
        "http://localhost:'"$MS_PORT"'/indexes/_healthcheck_test" >/dev/null

    # Clean up
    curl -sf --max-time 5 -X DELETE \
        -H "Authorization: Bearer '"$MS_KEY"'" \
        "http://localhost:'"$MS_PORT"'/indexes/_healthcheck_test" >/dev/null
'

# 5. Stats endpoint
check "Stats endpoint" \
    curl -sf --max-time 5 -H "Authorization: Bearer ${MS_KEY}" \
    "http://localhost:${MS_PORT}/stats"

summary
