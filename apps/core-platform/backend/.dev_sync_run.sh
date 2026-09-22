#!/usr/bin/env bash
# A sync run with a STUBBED Zoho transport (payloads from docs/zoho-docs-md).
# Everything else is real: engine, registry, translators, crosswalk, apply gate.
#
#   bash .dev_sync_run.sh            # the app stack (:5432)  ← default
#   bash .dev_sync_run.sh scratch    # the test containers (:55432)
#
# For a run against the REAL Zoho API use the CLI instead:
#   bash .dev_zoho.sh sync
set -u
cd "$(dirname "$0")"
# shellcheck source=.dev_target.sh
. ./.dev_target.sh
thm_select_target "${1:-}"

export LOG_LEVEL=ERROR
.venv/bin/python .sync_run.py 2>&1 | grep -v -e '^\[2026' -e 'INFO ' -e 'sqlalchemy'
