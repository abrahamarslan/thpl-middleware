#!/usr/bin/env bash
# Dev helper: apply migrations + autogenerate the new revision against the
# scratch postgres (thm-scratch-pg on :55432). Usage:
#   bash .dev_migrate.sh upgrade            # alembic upgrade head
#   bash .dev_migrate.sh revision "message" # autogenerate revision
set -e
cd "$(dirname "$0")"
export DATABASE_URL="postgresql+asyncpg://app:app_password@localhost:55432/app_db"
export REDIS_URL="redis://localhost:56379/0"
case "$1" in
  upgrade)
    .venv/bin/alembic upgrade head
    ;;
  revision)
    .venv/bin/alembic revision --autogenerate -m "$2"
    ;;
  *)
    echo "usage: $0 upgrade|revision <msg>"; exit 1;;
esac
