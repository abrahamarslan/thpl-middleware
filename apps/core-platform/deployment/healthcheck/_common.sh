#!/usr/bin/env bash
# ==============================================================================
# Shared helpers for healthcheck scripts
# ==============================================================================
# Source this at the top of each test script:
#   source "$(dirname "$0")/_common.sh"
# ==============================================================================

# Load .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
NC='\033[0m'

_PASS=0
_FAIL=0

section() {
    echo -e "\n  ${YELLOW}[$1]${NC}"
}

check() {
    local label="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        echo -e "    ${GREEN}✓${NC} $label"
        _PASS=$((_PASS + 1))
    else
        echo -e "    ${RED}✗${NC} $label"
        _FAIL=$((_FAIL + 1))
    fi
}

container_running() {
    docker inspect --format='{{.State.Running}}' "$1" 2>/dev/null | grep -q true
}

summary() {
    local total=$((_PASS + _FAIL))
    if [ "$_FAIL" -eq 0 ]; then
        echo -e "    ${GREEN}All $total checks passed${NC}"
        return 0
    else
        echo -e "    ${RED}$_FAIL/$total checks failed${NC}"
        return 1
    fi
}
