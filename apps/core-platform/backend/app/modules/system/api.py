"""Liveness / readiness probes.

/health — liveness: process is up, no dependency checks (used by Docker).
/ready  — readiness: verifies PostgreSQL and Redis are reachable.
"""

from fastapi import APIRouter
from fastapi.responses import ORJSONResponse
from sqlalchemy import text

from app.core.conf import settings

system_router = APIRouter(include_in_schema=False)


@system_router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.VERSION}


@system_router.get("/ready")
async def ready():
    from app.database.db import engine
    from app.database.redis import redis_client

    checks: dict[str, str] = {}
    healthy = True

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:  # pragma: no cover
        checks["postgres"] = f"error: {type(e).__name__}"
        healthy = False

    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as e:  # pragma: no cover
        checks["redis"] = f"error: {type(e).__name__}"
        healthy = False

    return ORJSONResponse(status_code=200 if healthy else 503, content={"status": "ok" if healthy else "degraded", "checks": checks})
