"""OpenTelemetry tracing setup.

Traces flow: backend/worker -> Alloy (OTLP :4318) -> Tempo -> Grafana.
Metrics are NOT sent via OTLP; Prometheus scrapes /metrics directly
(prometheus-fastapi-instrumentator), keeping one source of truth per signal.
"""

import structlog

from app.core.conf import settings

logger = structlog.get_logger("app.otel")


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

    HTTPXClientInstrumentor().instrument()
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
