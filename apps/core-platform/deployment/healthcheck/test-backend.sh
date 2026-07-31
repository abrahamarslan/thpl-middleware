#!/usr/bin/env bash
# ==============================================================================
# Backend (FastAPI) Healthcheck
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

BACKEND_PORT="${BACKEND_PORT:-8000}"
DOMAIN="${APP_DOMAIN:-app.local}"

section "Backend (FastAPI)"

# 1. Container running
check "Container running" container_running backend

# 2. Health endpoint (direct)
check "Health endpoint (direct)" \
    curl -sf --max-time 10 "http://localhost:${BACKEND_PORT}/health"

# 3. API docs accessible (direct)
check "OpenAPI docs (direct)" \
    curl -sf --max-time 10 "http://localhost:${BACKEND_PORT}/docs"

# 4. Via Traefik (HTTPS /api)
check "Via Traefik (/api/health)" \
    curl -sfk --max-time 10 "https://localhost:${TRAEFIK_HTTPS_PORT:-443}/api/health" \
    --resolve "${DOMAIN}:${TRAEFIK_HTTPS_PORT:-443}:127.0.0.1" \
    -H "Host: ${DOMAIN}"

# 5. Backend can reach PostgreSQL
check "Database connectivity" \
    docker exec backend python -c "
import os, sys
try:
    from sqlalchemy import create_engine, text
    engine = create_engine(os.environ['DATABASE_URL'])
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null

# 6. Backend can reach Redis
check "Redis connectivity" \
    docker exec backend python -c "
import os, sys
try:
    import redis
    r = redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'))
    r.ping()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null

summary
