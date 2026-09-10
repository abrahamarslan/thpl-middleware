"""Request context middleware: request_id propagation + structured access log.

Each request gets a request_id (from the X-Request-ID header if the caller —
Traefik or a mobile app — supplies one, otherwise generated). It is bound to
structlog contextvars so *every* log line in the request, in any module,
automatically carries it. The same id is returned in the X-Request-ID
response header, so a user-reported error can be traced end-to-end in Loki.
"""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.conf import settings

access_logger = structlog.get_logger("app.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            client_ip=request.client.host if request.client else None,
        )

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            access_logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["x-request-id"] = request_id

        # Skip noise: health probes hit every few seconds
        if request.url.path not in (
            "/health",
            "/ready",
            "/metrics",
            f"{settings.API_PREFIX}/health",
            f"{settings.API_PREFIX}/ready",
        ):
            access_logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        return response
