#!/usr/bin/env bash
# Dev helper: apply migrations / autogenerate a revision.
#   bash .dev_migrate.sh upgrade [app|scratch]
#   bash .dev_migrate.sh revision "message" [app|scratch]
#   bash .dev_migrate.sh current [app|scratch]
# Target defaults to the running app stack (:5432) — see .dev_target.sh.
set -e
cd "$(dirname "$0")"
# shellcheck source=.dev_target.sh
. ./.dev_target.sh

case "$1" in
  upgrade)
    thm_select_target "${2:-}"
    .venv/bin/alembic upgrade head
    ;;
  revision)
    thm_select_target "${3:-}"
    .venv/bin/alembic revision --autogenerate -m "$2"
    ;;
  current)
    thm_select_target "${2:-}"
    .venv/bin/alembic current
    ;;
  *)
    echo "usage: $0 upgrade|current [app|scratch] | revision <msg> [app|scratch]"; exit 1;;
esac
