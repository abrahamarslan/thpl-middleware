#!/usr/bin/env bash
# Dev helper: import smoke test + test suite. Usage: bash .dev_check.sh [pytest args]
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
