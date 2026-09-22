#!/usr/bin/env bash
# The Zoho sync CLI against a chosen database, talking to the REAL Zoho API.
#
#   bash .dev_zoho.sh check              # credentials + connectivity
#   bash .dev_zoho.sh sync               # every registered module
#   bash .dev_zoho.sh sync taxes         # one module
#   bash .dev_zoho.sh status             # rows + last run per module
#   bash .dev_zoho.sh runs                # recent runs
#   bash .dev_zoho.sh sync taxes scratch  # ...against the test containers
#
# Target defaults to the running app stack (:5432) — see .dev_target.sh.
# Unlike .dev_sync_run.sh (stubbed transport), this spends real Zoho quota.
set -u
cd "$(dirname "$0")"
# shellcheck source=.dev_target.sh
. ./.dev_target.sh

# The target is the LAST argument when it names one; otherwise the default.
args=("$@")
last="${args[${#args[@]}-1]:-}"
if [ "$last" = "app" ] || [ "$last" = "scratch" ]; then
  unset 'args[${#args[@]}-1]'
  thm_select_target "$last"
else
  thm_select_target
fi

.venv/bin/python -m app.modules.zoho.cli "${args[@]}"
