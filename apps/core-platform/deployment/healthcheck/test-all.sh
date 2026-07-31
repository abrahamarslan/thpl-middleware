#!/usr/bin/env bash
# ==============================================================================
# Master Healthcheck Script — Run All Service Tests
# ==============================================================================
# Usage: ./healthcheck/test-all.sh
# Run from the deployment/ directory.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load .env
if [ -f "$SCRIPT_DIR/../.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$SCRIPT_DIR/../.env"
    set +a
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PASSED=0
FAILED=0
SKIPPED=0
RESULTS=()

# ── Helpers ──────────────────────────────────────────────────────────────────
run_test() {
    local name="$1"
    local script="$2"

    if [ ! -f "$script" ]; then
        echo -e "  ${YELLOW}SKIP${NC}  $name (script not found)"
        SKIPPED=$((SKIPPED + 1))
        RESULTS+=("SKIP  $name")
        return
    fi

    echo -e "\n${CYAN}━━━ $name ━━━${NC}"
    if bash "$script"; then
        PASSED=$((PASSED + 1))
        RESULTS+=("${GREEN}PASS${NC}  $name")
    else
        FAILED=$((FAILED + 1))
        RESULTS+=("${RED}FAIL${NC}  $name")
    fi
}

container_running() {
    docker inspect --format='{{.State.Running}}' "$1" 2>/dev/null | grep -q true
}

# ── Header ───────────────────────────────────────────────────────────────────
echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          Service Healthcheck Suite                      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "Domain:      ${APP_DOMAIN:-app.local}"
echo "Environment: ${ENVIRONMENT:-unknown}"
echo ""

# ── Run Tests ────────────────────────────────────────────────────────────────

# Infrastructure
run_test "Traefik (Reverse Proxy)"  "$SCRIPT_DIR/test-traefik.sh"

# Data Layer
run_test "PostgreSQL"               "$SCRIPT_DIR/test-postgres.sh"
run_test "Redis"                    "$SCRIPT_DIR/test-redis.sh"
run_test "ClickHouse"               "$SCRIPT_DIR/test-clickhouse.sh"
run_test "MeiliSearch"              "$SCRIPT_DIR/test-meilisearch.sh"

# Application
run_test "Backend (FastAPI)"        "$SCRIPT_DIR/test-backend.sh"
run_test "Frontend"                 "$SCRIPT_DIR/test-frontend.sh"

# Async Tasks
run_test "Celery (worker/beat/flower)" "$SCRIPT_DIR/test-celery.sh"

# Real-Time
run_test "Soketi (WebSocket)"       "$SCRIPT_DIR/test-soketi.sh"

# IAM
run_test "Authentik"                "$SCRIPT_DIR/test-authentik.sh"

# Event Streaming
run_test "Kafka (KRaft)"            "$SCRIPT_DIR/test-kafka.sh"

# Monitoring
run_test "Prometheus"               "$SCRIPT_DIR/test-prometheus.sh"
run_test "Loki"                     "$SCRIPT_DIR/test-loki.sh"
run_test "Grafana"                  "$SCRIPT_DIR/test-grafana.sh"
run_test "Observability pipeline"   "$SCRIPT_DIR/test-observability.sh"

# Utilities
run_test "Gotenberg (PDF)"          "$SCRIPT_DIR/test-gotenberg.sh"

# ── Summary ──────────────────────────────────────────────────────────────────
TOTAL=$((PASSED + FAILED + SKIPPED))

echo ""
echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                     Results                             ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

for result in "${RESULTS[@]}"; do
    echo -e "  $result"
done

echo ""
echo -e "  ${GREEN}Passed:${NC}  $PASSED"
echo -e "  ${RED}Failed:${NC}  $FAILED"
echo -e "  ${YELLOW}Skipped:${NC} $SKIPPED"
echo -e "  Total:   $TOTAL"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}${BOLD}$FAILED test(s) failed.${NC}"
    exit 1
fi
