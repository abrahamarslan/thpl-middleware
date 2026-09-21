"""OpenTelemetry tracing setup.

Traces flow: backend/worker -> Alloy (OTLP :4318) -> Tempo -> Grafana.
Metrics are NOT sent via OTLP; Prometheus scrapes /metrics directly
(prometheus-fastapi-instrumentator), keeping one source of truth per signal.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import structlog

from app.core.conf import settings

logger = structlog.get_logger("app.otel")

#: Query parameters that carry credentials in outbound URLs. Zoho's OAuth
#: token endpoint REQUIRES client_secret / refresh_token / code in the query
#: string (docs/zoho-docs-md/oauth-zoho.md), and the httpx instrumentation
#: records the full URL on every span — so without this hook the Zoho secret
#: and refresh token would be stored in Tempo.
_SECRET_QUERY_KEYS = frozenset(
    {"client_secret", "refresh_token", "code", "token", "access_token", "password", "api_key"}
)
#: Hosts whose query strings are dropped wholesale (every parameter is sensitive).
_SENSITIVE_HOST_MARKERS = ("accounts.zoho",)
_REDACTED = "REDACTED"


def scrub_url(url: str) -> str:
    """Remove credentials from a URL before it is attached to a span."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable-url>"
    if any(marker in (parts.hostname or "") for marker in _SENSITIVE_HOST_MARKERS):
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    if not parts.query:
        return url
    query = [
        (key, _REDACTED if key.lower() in _SECRET_QUERY_KEYS else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _httpx_request_hook(span, request) -> None:
    """Overwrite the URL attributes the httpx instrumentation just recorded."""
    if span is None or not span.is_recording():
        return
    url = request.url if hasattr(request, "url") else request[1]
    clean = scrub_url(str(url))
    span.set_attribute("http.url", clean)
    span.set_attribute("url.full", clean)


async def _httpx_async_request_hook(span, request) -> None:
    _httpx_request_hook(span, request)


def setup_otel(app=None) -> None:
    if not settings.OTEL_ENABLED:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            SERVICE_NAME: settings.OTEL_SERVICE_NAME,
            "deployment.environment": settings.ENVIRONMENT,
            "service.version": settings.VERSION,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{settings.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces")
        )
    )
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument(
        request_hook=_httpx_request_hook,
        async_request_hook=_httpx_async_request_hook,
    )
    RedisInstrumentor().instrument()

    from app.database.db import engine

    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready,metrics")

    logger.info("otel_enabled", endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)


def setup_otel_celery() -> None:
    """Called from the celery worker_process_init signal."""
    if not settings.OTEL_ENABLED:
        return
    from opentelemetry.instrumentation.celery import CeleryInstrumentor

    setup_otel(app=None)
    CeleryInstrumentor().instrument()
