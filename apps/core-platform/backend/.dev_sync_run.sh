#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"
export DATABASE_URL="postgresql+asyncpg://app:app_password@localhost:55432/app_db"
export REDIS_URL="redis://localhost:56379/0"
export LOG_LEVEL=ERROR
.venv/bin/python .sync_run.py 2>&1 | grep -v -e '^\[2026' -e 'INFO ' -e 'sqlalchemy'
