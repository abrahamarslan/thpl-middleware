#!/usr/bin/env bash
# Which database the .dev_* helpers act on. Sourced, never run directly.
#
#   app      (DEFAULT) the running compose stack — postgres:5432 / redis:6379.
#            This is YOUR development database: what the backend container,
#            the frontend and a live Zoho sync all talk to.
#   scratch  the throwaway test containers — 55432 / 56379. This is what
#            `pytest` uses (tests/conftest.py hard-codes those ports) and the
#            ONLY thing that should ever be reset casually.
#
# The default is `app` on purpose. It used to be `scratch`, which meant every
# helper quietly operated on the test database while the real one drifted
# behind — migrations unapplied, old mirror tables still present.
#
# Usage:  bash .dev_migrate.sh upgrade            # app stack
#         bash .dev_migrate.sh upgrade scratch    # test containers
#         THM_TARGET=scratch bash .dev_check.sh test

thm_select_target() {
  local target="${1:-${THM_TARGET:-app}}"
  case "$target" in
    app)
      export DATABASE_URL="postgresql+asyncpg://app:app_password@localhost:5432/app_db"
      export REDIS_URL="redis://:de3IFvW5Y1GGxfRuLBuK0SgV@localhost:6379/0"
      export THM_TARGET_NAME="app stack (:5432)"
      ;;
    scratch)
      export DATABASE_URL="postgresql+asyncpg://app:app_password@localhost:55432/app_db"
      export REDIS_URL="redis://localhost:56379/0"
      export THM_TARGET_NAME="scratch test containers (:55432)"
      ;;
    *)
      echo "unknown target '$target' (expected: app | scratch)" >&2
      return 1
      ;;
  esac
  echo "── target: ${THM_TARGET_NAME} ──"
}
