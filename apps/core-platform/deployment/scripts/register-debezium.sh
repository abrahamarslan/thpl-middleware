#!/usr/bin/env bash
# ==============================================================================
# Register (or update) the Debezium PostgreSQL connector.
#
# Idempotent: uses PUT /connectors/<name>/config, which creates or updates.
# Runs the curl INSIDE the debezium container, so no host port is needed.
#
# Usage: ./scripts/register-debezium.sh [connector-name] [config-file]
#   defaults: zoho-mirror  config/debezium/zoho-mirror-connector.json
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$SCRIPT_DIR/.."

NAME="${1:-zoho-mirror}"
CONFIG_FILE="${2:-$DEPLOY_DIR/config/debezium/zoho-mirror-connector.json}"

# Load .env for the DB credential placeholders
if [ -f "$DEPLOY_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$DEPLOY_DIR/.env"
    set +a
fi

: "${POSTGRES_USER:?POSTGRES_USER not set}" "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set}" "${POSTGRES_DB:?POSTGRES_DB not set}"

# Substitute ${POSTGRES_*} placeholders in the template
PAYLOAD=$(sed \
    -e "s|\${POSTGRES_USER}|$POSTGRES_USER|g" \
    -e "s|\${POSTGRES_PASSWORD}|$POSTGRES_PASSWORD|g" \
    -e "s|\${POSTGRES_DB}|$POSTGRES_DB|g" \
    "$CONFIG_FILE")

echo "Registering connector '$NAME'..."
HTTP_CODE=$(echo "$PAYLOAD" | docker exec -i debezium curl -s -o /tmp/dbz-resp.json -w "%{http_code}" \
    -X PUT "http://localhost:8083/connectors/$NAME/config" \
    -H "Content-Type: application/json" \
    -d @-)

docker exec debezium cat /tmp/dbz-resp.json | python3 -m json.tool 2>/dev/null || true
echo ""

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
    echo "Connector '$NAME' registered (HTTP $HTTP_CODE)."
    echo "Check status: docker exec debezium curl -s http://localhost:8083/connectors/$NAME/status"
else
    echo "ERROR: registration failed (HTTP $HTTP_CODE)" >&2
    exit 1
fi
