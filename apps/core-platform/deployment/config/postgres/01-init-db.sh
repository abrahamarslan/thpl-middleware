#!/usr/bin/env bash
# ==============================================================================
# One-shot DB init: create the Authentik role + database (idempotent).
# Runs in the postgres-init container after postgres is healthy.
# ==============================================================================
set -euo pipefail

: "${POSTGRES_HOST:?}" "${POSTGRES_USER:?}" "${POSTGRES_DB:?}"
: "${AUTHENTIK_DB_NAME:?}" "${AUTHENTIK_DB_USER:?}" "${AUTHENTIK_DB_PASSWORD:?}"

# Wait for Postgres to actually accept connections. Compose's service_healthy
# gate can pass during a transient window because the kartoza/postgis image
# restarts the server internally while initialising the cluster + extensions.
echo "Waiting for postgres at ${POSTGRES_HOST}:5432 ..."
for i in $(seq 1 60); do
    if pg_isready -h "$POSTGRES_HOST" -p 5432 -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
        echo "Postgres is ready."
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "ERROR: postgres did not become ready in time" >&2
        exit 1
    fi
    sleep 2
done

psql() {
    command psql -v ON_ERROR_STOP=1 -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}

echo "Creating role '${AUTHENTIK_DB_USER}' (if missing)..."
psql <<-SQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${AUTHENTIK_DB_USER}') THEN
            CREATE ROLE "${AUTHENTIK_DB_USER}" LOGIN PASSWORD '${AUTHENTIK_DB_PASSWORD}';
        ELSE
            ALTER ROLE "${AUTHENTIK_DB_USER}" WITH LOGIN PASSWORD '${AUTHENTIK_DB_PASSWORD}';
        END IF;
    END
    \$\$;
SQL

echo "Creating database '${AUTHENTIK_DB_NAME}' (if missing)..."
if ! psql -tAc "SELECT 1 FROM pg_database WHERE datname='${AUTHENTIK_DB_NAME}'" | grep -q 1; then
    psql -c "CREATE DATABASE \"${AUTHENTIK_DB_NAME}\" OWNER \"${AUTHENTIK_DB_USER}\""
fi

echo "init-db complete."
