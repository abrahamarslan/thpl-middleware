#!/usr/bin/env bash
# ==============================================================================
# Seed countries, timezones, and country-timezone reference tables.
# Reads DATABASE_URL from .env file.
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Safely source .env if present
if [ -f "${BACKEND_DIR}/.env" ]; then
    set -a
    . "${BACKEND_DIR}/.env"
    set +a
fi

JSON_FILE="${BACKEND_DIR}/data/countries/countries.json"
if [ ! -f "${JSON_FILE}" ]; then
    JSON_FILE="${BACKEND_DIR}/data/countries.json"
fi

ZONE_FILE="${BACKEND_DIR}/data/timezones/zone1970.tab"

echo "=== Seeding Countries, Timezones, and Mappings ==="
python3 "${SCRIPT_DIR}/seed_countries_timezones.py" \
    --json-file "${JSON_FILE}" \
    --zone-file "${ZONE_FILE}" \
    ${DATABASE_URL:+--database-url "${DATABASE_URL}"}

echo "=== Seeding Completed Successfully ==="
