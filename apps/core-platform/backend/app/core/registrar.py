"""Application factory — wires settings, logging, middleware, routers, observability."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator import routing as _pfi_routing

_original_get_route_name = _pfi_routing.get_route_name


def _safe_get_route_name(request, **kwargs):
    try:
        return _original_get_route_name(request, **kwargs)
    except AttributeError:
        return request.url.path


_pfi_routing.get_route_name = _safe_get_route_name
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.common.exception.handlers import register_exception_handlers
from app.common.log import configure_logging
from app.core.conf import settings
from app.core.observability import setup_otel
from app.middleware.context import RequestContextMiddleware
from app.router import api_router

logger = structlog.get_logger("app.startup")

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"],
    storage_uri=settings.REDIS_URL,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.database.redis import close_redis, redis_client

    await redis_client.ping()
    logger.info("startup_complete", environment=settings.ENVIRONMENT, version=settings.VERSION)
    yield
    from app.database.db import engine

    await close_redis()
    await engine.dispose()
    logger.info("shutdown_complete")


def register_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.VERSION,
        default_response_class=ORJSONResponse,
        # API docs disabled outside development — schema is internal IP
        docs_url=f"{settings.API_PREFIX}/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url=None,
        openapi_url=f"{settings.API_PREFIX}/openapi.json" if settings.ENVIRONMENT != "production" else None,
        lifespan=lifespan,
    )

    # Middleware (order matters: CORS outermost, then request context)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    register_exception_handlers(app)

    # Routes: probes at root (no auth, no prefix), business API under /api
    from app.modules.system.api import system_router

    app.include_router(system_router)
    app.include_router(api_router, prefix=settings.API_PREFIX)

    # Prometheus /metrics — scraped over the internal network only
    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/health", "/ready", "/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    # OpenTelemetry traces -> Alloy -> Tempo
    setup_otel(app)

    return app
