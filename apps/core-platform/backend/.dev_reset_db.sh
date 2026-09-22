#!/usr/bin/env bash
# Drop every application schema and rebuild from migration zero.
# Development only — this destroys all data in the target database.
#
#   bash .dev_reset_db.sh            # the app stack (:5432)  ← default
#   bash .dev_reset_db.sh scratch    # the test containers (:55432)
set -eu
cd "$(dirname "$0")"
# shellcheck source=.dev_target.sh
. ./.dev_target.sh
thm_select_target "${1:-}"

.venv/bin/python scripts/drop_schemas.py --yes

echo "── rebuilding from migration zero ──"
.venv/bin/alembic upgrade head 2>&1 | grep -E "Running upgrade|ERROR" || true

echo "── head ──"
.venv/bin/alembic current 2>&1 | tail -2
