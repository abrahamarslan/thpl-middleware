#!/usr/bin/env bash
# Dev helper: start (idempotently) the scratch Postgres + Redis containers the
# integration tests expect, wait until Postgres accepts connections, and apply
# migrations. Safe to re-run. Usage (from WSL):
#   bash .dev_scratch.sh          # start + migrate
#   bash .dev_scratch.sh stop     # remove both containers
set -e
cd "$(dirname "$0")"

PG=thm-scratch-pg
REDIS=thm-scratch-redis

if [ "$1" = "stop" ]; then
  docker rm -f "$PG" "$REDIS" >/dev/null 2>&1 || true
  echo "scratch containers removed"
  exit 0
fi

running() { docker ps --format '{{.Names}}' | grep -qx "$1"; }

if ! running "$REDIS"; then
  docker run -d --rm --name "$REDIS" -p 56379:6379 redis:7.4-alpine >/dev/null
  echo "started $REDIS"
fi

if ! running "$PG"; then
  docker run -d --rm --name "$PG" -p 55432:5432 \
    -e POSTGRES_USER=app -e POSTGRES_PASS=app_password -e POSTGRES_DBNAME=app_db \
    -e POSTGRES_MULTIPLE_EXTENSIONS=postgis,hstore,postgis_topology,pgrouting,pg_trgm,pgcrypto \
    kartoza/postgis:18-3.6--v2025.11.24 >/dev/null
  echo "started $PG"
fi

# kartoza restarts Postgres once after creating extensions: wait for two
# consecutive successful probes, a few seconds apart, before migrating.
ok=0
for _ in $(seq 1 60); do
  if docker exec -e PGPASSWORD=app_password "$PG" psql -h 127.0.0.1 -U app -d app_db -c 'select 1' >/dev/null 2>&1; then
    ok=$((ok + 1))
    [ "$ok" -ge 2 ] && break
    sleep 4
  else
    ok=0
    sleep 2
  fi
done
[ "$ok" -ge 2 ] || { echo "postgres did not become ready"; exit 1; }

bash .dev_migrate.sh upgrade
echo "scratch environment ready (pg :55432, redis :56379)"
