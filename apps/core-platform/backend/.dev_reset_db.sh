#!/usr/bin/env bash
# Drop every application schema and rebuild from migration zero.
# Development only — this destroys all data in the target database.
set -eu
cd "$(dirname "$0")"

PG=thm-scratch-pg
export DATABASE_URL="postgresql+asyncpg://app:app_password@localhost:55432/app_db"
export REDIS_URL="redis://localhost:56379/0"

echo "── dropping schemas ──"
# -i is required: without it docker exec does not forward stdin and psql
# silently reads nothing, leaving the database untouched.
docker exec -i -e PGPASSWORD=app_password "$PG" psql -h 127.0.0.1 -U app -d app_db -v ON_ERROR_STOP=1 <<'SQL'
-- Every schema our migrations own. Keep in step with alembic/env.py
-- _OWNED_SCHEMAS; a schema missing here survives the reset and the rebuild
-- then fails on an object that already exists.
DROP SCHEMA IF EXISTS core CASCADE;
DROP SCHEMA IF EXISTS tax CASCADE;
DROP SCHEMA IF EXISTS sync CASCADE;
DROP SCHEMA IF EXISTS currency CASCADE;
DROP SCHEMA IF EXISTS geo CASCADE;
DROP SCHEMA IF EXISTS org_management CASCADE;
-- public holds both our tables and the PostGIS extension objects, so it is
-- emptied of OUR tables rather than dropped.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_depend d ON d.objid = c.oid AND d.deptype = 'e'
    WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND d.objid IS NULL
  LOOP
    EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.relname);
  END LOOP;
END $$;
DROP TYPE IF EXISTS setting_context_enum CASCADE;
SQL

echo "── rebuilding from migration zero ──"
.venv/bin/alembic upgrade head 2>&1 | grep -E "Running upgrade|ERROR" || true

echo "── head ──"
.venv/bin/alembic current 2>&1 | tail -2
