#!/usr/bin/env bash
# ==============================================================================
# Typst (PDF Generation) Healthcheck
# ==============================================================================
# Typst renders in-process via typst-py — there is no sidecar container.
# Checks therefore run inside the celery-worker (the only allowed consumer):
#   1. typst package importable, 2. minimal markup compiles to a real PDF.
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

section "Typst (PDF Generation)"

# 1. Worker container running
check "Container running" container_running celery-worker

# 2. typst-py installed in the image
check "typst package importable" \
    docker exec celery-worker python -c "import typst; print(typst.__version__ if hasattr(typst, '__version__') else 'ok')"

# 3. Minimal markup compiles to a real PDF (%PDF magic bytes)
check "Minimal document compiles to PDF" bash -c '
    docker exec celery-worker python -c "
import typst
pdf = typst.compile(b\"= Healthcheck\n\nHello from Typst.\", format=\"pdf\")
assert pdf[:4] == b\"%PDF\", pdf[:8]
print(len(pdf))
" >/dev/null
'

summary
