#!/bin/sh
# TEMPORARY (fieldops build session): run a command inside the dev backend container against the
# isolated fieldops scratch containers (fo-scratch-pg :25432, fo-scratch-redis :26379 on the host).
export DATABASE_URL="postgresql+asyncpg://app:app_password@host.docker.internal:25432/app_db"
export REDIS_URL="redis://host.docker.internal:26379/0"
export CELERY_BROKER_URL="redis://host.docker.internal:26379/2"
export CELERY_RESULT_BACKEND="redis://host.docker.internal:26379/3"
export PYTHONDONTWRITEBYTECODE=1
export OTEL_ENABLED=false
export DB_ECHO=false
export PYTHONPATH="/app:/tmp/fodev"
export PATH="/tmp/fodev/bin:$PATH"
cd /app
exec "$@"
