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

# Resolve DB credentials WITHOUT sourcing .env. A hand-edited .env can contain
# shell metacharacters ($, &, spaces) that break `source` and abort every
# manage.sh subcommand. Prefer the values the running postgres container
# actually received; fall back to .env only if the container is unavailable.
cd "$DEPLOY_DIR"
POSTGRES_USER="$(docker compose exec -T postgres printenv POSTGRES_USER 2>/dev/null | tr -d '\r' || true)"
POSTGRES_PASSWORD="$(docker compose exec -T postgres printenv POSTGRES_PASS 2>/dev/null | tr -d '\r' || true)"
POSTGRES_DB="$(docker compose exec -T postgres printenv POSTGRES_DBNAME 2>/dev/null | tr -d '\r' || true)"
if [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_PASSWORD" ] || [ -z "$POSTGRES_DB" ]; then
    echo "WARN: could not read DB credentials from the postgres container; using .env" >&2
    if [ -f "$DEPLOY_DIR/.env" ]; then
        set -a
        # shellcheck disable=SC1091
        . "$DEPLOY_DIR/.env"
        set +a
    fi
fi

: "${POSTGRES_USER:?POSTGRES_USER not set}" "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set}" "${POSTGRES_DB:?POSTGRES_DB not set}"

# Kafka Connect takes ~45-90s to expose its REST API after boot. Wait for it
# instead of aborting silently under `set -e` when the PUT fails.
echo "Waiting for the Debezium REST API on :8083 ..."
api_up=0
for _ in $(seq 1 30); do
    if docker exec debezium curl -sf http://localhost:8083/connectors >/dev/null 2>&1; then
        api_up=1
        break
    fi
    sleep 5
done
if [ "$api_up" -ne 1 ]; then
    echo "ERROR: Debezium REST API not reachable on :8083 after 150s." >&2
    echo "Last Debezium log lines:" >&2
    docker compose logs --tail=30 debezium >&2 || true
    exit 1
fi

# Substitute ${POSTGRES_*} placeholders in the template
PAYLOAD=$(sed \
    -e "s|\${POSTGRES_USER}|$POSTGRES_USER|g" \
    -e "s|\${POSTGRES_PASSWORD}|$POSTGRES_PASSWORD|g" \
    -e "s|\${POSTGRES_DB}|$POSTGRES_DB|g" \
    "$CONFIG_FILE")

echo "Registering connector '$NAME'..."
set +e
HTTP_CODE=$(echo "$PAYLOAD" | docker exec -i debezium curl -s -o /tmp/dbz-resp.json -w "%{http_code}" \
    -X PUT "http://localhost:8083/connectors/$NAME/config" \
    -H "Content-Type: application/json" \
    -d @-)
CURL_RC=$?
set -e

docker exec debezium cat /tmp/dbz-resp.json 2>/dev/null | python3 -m json.tool 2>/dev/null \
    || docker exec debezium cat /tmp/dbz-resp.json 2>/dev/null \
    || true
echo ""

if [ "$CURL_RC" -ne 0 ]; then
    echo "ERROR: curl to Debezium failed (rc=$CURL_RC)" >&2
    exit 1
fi
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
    echo "Connector '$NAME' registered (HTTP $HTTP_CODE)."
    echo "Check status: ./manage.sh debezium-status"
else
    echo "ERROR: registration failed (HTTP $HTTP_CODE)" >&2
    exit 1
fi
