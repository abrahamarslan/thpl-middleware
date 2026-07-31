#!/usr/bin/env bash
# ==============================================================================
# Celery (worker / beat / flower) Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

section "Celery (async tasks)"

check "Worker container running"  container_running celery-worker
check "Beat container running"    container_running celery-beat
check "Flower container running"  container_running flower
check "Exporter container running" container_running celery-exporter

check "Worker responds to ping" \
    docker exec celery-worker celery -A app.tasks.celery_app inspect ping --timeout 10

check "Registered tasks include zoho sync" bash -c '
    docker exec celery-worker celery -A app.tasks.celery_app inspect registered --timeout 10 2>/dev/null \
        | grep -q "app.tasks.zoho.sync_items"
'

check "Celery exporter metrics" bash -c '
    docker exec backend curl -sf http://celery-exporter:9808/metrics | grep -q celery_
'

summary
