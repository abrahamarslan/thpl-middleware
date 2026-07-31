#!/usr/bin/env bash
# ==============================================================================
# PostgreSQL Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

PG_USER="${POSTGRES_USER:-app}"
PG_DB="${POSTGRES_DB:-app_db}"
AUTH_DB="${AUTHENTIK_DB_NAME:-authentik}"

section "PostgreSQL"

# 1. Container running
check "Container running" container_running postgres

# 2. pg_isready
check "Accepting connections (pg_isready)" \
    docker exec postgres pg_isready -h localhost -U "$PG_USER" -d "$PG_DB"

# 3. Can execute queries
check "Query execution (SELECT 1)" \
    docker exec postgres psql -h localhost -U "$PG_USER" -d "$PG_DB" -c "SELECT 1" -tA

# 4. Required extensions installed
check_extension() {
    docker exec postgres psql -h localhost -U "$PG_USER" -d "$PG_DB" \
        -tAc "SELECT 1 FROM pg_extension WHERE extname='$1'" | grep -q 1
}
check "Extension: uuid-ossp"       check_extension uuid-ossp
check "Extension: pgcrypto"        check_extension pgcrypto
check "Extension: pg_trgm"         check_extension pg_trgm
check "Extension: postgis"         check_extension postgis
check "Extension: vector"          check_extension vector
check "Extension: pgaudit"         check_extension pgaudit
check "Extension: pg_partman"      check_extension pg_partman
check "Extension: ltree"           check_extension ltree

# 5. Authentik database exists
check "Authentik database exists" \
    docker exec postgres psql -h localhost -U postgres \
        -tAc "SELECT 1 FROM pg_database WHERE datname='$AUTH_DB'" | grep -q 1

# 6. Connection count is sane (not maxed out)
check "Connection headroom (< 80%)" bash -c '
    USED=$(docker exec postgres psql -h localhost -U '"$PG_USER"' -d '"$PG_DB"' \
        -tAc "SELECT count(*) FROM pg_stat_activity")
    MAX=$(docker exec postgres psql -h localhost -U '"$PG_USER"' -d '"$PG_DB"' \
        -tAc "SHOW max_connections" | tr -d " ")
    [ "$USED" -lt $((MAX * 80 / 100)) ]
'

summary
