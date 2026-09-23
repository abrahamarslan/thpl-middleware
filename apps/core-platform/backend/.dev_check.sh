#!/usr/bin/env bash
# Dev helper: import smoke test + test suite. Usage: bash .dev_check.sh [pytest args]
#
# No target argument, deliberately: pytest ALWAYS runs against the scratch test
# containers (:55432 / :56379), which tests/conftest.py hard-codes. Pointing it
# at the app database would break ~56 unrelated tests — the suite's contract is
# a MIGRATED database, not a SEEDED one. Start the containers first:
#   docker run -d --rm --name thm-scratch-pg ...   (see tests/conftest.py)
#   bash .dev_migrate.sh upgrade scratch
set -e
cd "$(dirname "$0")"
.venv/bin/pip install -q 'meilisearch-python-sdk>=4.0'
.venv/bin/python - <<'PY'
from app.main import app
print("IMPORT_OK", len(app.routes))
PY
if [ "$1" = "test" ]; then
  shift
  .venv/bin/python -m pytest "$@"
fi
