"""CDC -> Meilisearch indexer (FastStream; standalone compose service `search-indexer`).

Pipeline:  Postgres WAL -> Debezium (unwrap transform) -> Kafka topics
           `zoho-mirror.public.<table>` -> THIS consumer -> Meilisearch
           index named after the table.

Guarantees:
  - at-least-once: AckPolicy.ACK commits the offset ONLY after the handler
    returns (i.e. Meilisearch accepted the batch); upserts are idempotent by
    document id, so replays are harmless;
  - batched: FastStream groups up to SEARCH_INDEX_BATCH_SIZE records per
    topic-partition (same flush unit the old getmany() loop used);
  - delete-aware: Debezium's `rewrite` mode flags deletions as
    __deleted="true"; soft deletes (deleted_at set) are removed from the
    index too — search must only ever surface live rows;
  - self-bootstrapping: on startup the declared index settings
    (searchable/filterable/sortable — see registry.py) are pushed to
    Meilisearch, so filtered queries never hit an unconfigured index.

Configure topics via SEARCH_CDC_TOPICS (comma-separated); the topic's last
dot-segment becomes the index name (zoho-mirror.public.zoho_organizations
-> index "zoho_organizations").

Runs via `python -m app.modules.search.indexer` (kept over `faststream run`
so configure_logging() bootstraps first and no CLI extra is needed).
"""

import structlog
from faststream import AckPolicy, FastStream
from faststream.kafka import KafkaBroker

from app.common.log import configure_logging
from app.core.conf import settings

logger = structlog.get_logger("app.search.indexer")

#: Primary-key candidates, in priority order, to use as the Meili document id.
_ID_CANDIDATES = ("id", "uuid", "contact_id", "item_id")


def _document_id(payload: dict) -> str | None:
    for key in _ID_CANDIDATES:
        if payload.get(key) is not None:
            return str(payload[key])
    return None


def _is_delete(payload: dict) -> bool:
    if str(payload.get("__deleted", "")).lower() == "true":
        return True
    # Soft-deleted rows leave the search index as well.
    return payload.get("deleted_at") is not None


def _sanitise(payload: dict) -> dict:
    """Strip Debezium bookkeeping fields before indexing."""
    return {k: v for k, v in payload.items() if not k.startswith("__")}


def partition_batch(payloads: list[dict | None]) -> tuple[list[dict], list[str]]:
    """Split a CDC batch into Meilisearch upserts and deletions (pure)."""
    to_upsert: list[dict] = []
    to_delete: list[str] = []
    for payload in payloads:
        if not payload:
            continue
        # Kafka Connect's JsonConverter wraps rows in {schema, payload} when
        # schemas.enable is on — unwrap so either converter config works.
        if "payload" in payload and "schema" in payload:
            payload = payload["payload"]
            if not payload:
                continue
        doc_id = _document_id(payload)
        if doc_id is None:
            logger.warning("search_document_without_id")
            continue
        if _is_delete(payload):
            to_delete.append(doc_id)
        else:
            doc = _sanitise(payload)
            doc.setdefault("id", doc_id)
            to_upsert.append(doc)
    return to_upsert, to_delete


# ── Meilisearch client (module-level so tests can patch get_meili) ───────────

_meili = None


def get_meili():
    global _meili
    if _meili is None:
        from meilisearch_python_sdk import AsyncClient

        _meili = AsyncClient(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY)
    return _meili


async def flush_to_meili(index_name: str, payloads: list[dict | None]) -> None:
    """Upsert/delete one topic-partition batch into its Meili index."""
    to_upsert, to_delete = partition_batch(payloads)
    index = get_meili().index(index_name)
    if to_upsert:
        # add_documents == upsert by id. primary_key MUST be explicit: CDC rows
        # carry several *_id columns and Meilisearch refuses to infer one
        # (index_primary_key_multiple_candidates_found).
        await index.add_documents(to_upsert, primary_key="id")
        logger.info("search_documents_upserted", index=index_name, count=len(to_upsert))
    if to_delete:
        await index.delete_documents(to_delete)
        logger.info("search_documents_deleted", index=index_name, count=len(to_delete))


# ── Broker wiring ─────────────────────────────────────────────────────────────


def _make_handler(index_name: str):
    async def index_cdc_batch(payloads: list[dict | None]) -> None:
        await flush_to_meili(index_name, payloads)

    index_cdc_batch.__name__ = f"index_{index_name}"
    return index_cdc_batch


def build_broker(topics: list[str]) -> KafkaBroker:
    """One batch subscriber per CDC topic; the closure knows its index name.

    AckPolicy.ACK == commit after the handler returns (at-least-once).
    """
    middlewares = []
    if settings.OTEL_ENABLED:
        from faststream.kafka.opentelemetry import KafkaTelemetryMiddleware

        middlewares.append(KafkaTelemetryMiddleware())

    broker = KafkaBroker(settings.KAFKA_BOOTSTRAP_SERVERS, middlewares=middlewares)
    for topic in topics:
        index_name = topic.rsplit(".", 1)[-1]
        broker.subscriber(
            topic,
            group_id=settings.SEARCH_CDC_GROUP_ID,
            batch=True,
            max_records=settings.SEARCH_INDEX_BATCH_SIZE,
            batch_timeout_ms=1000,
            auto_offset_reset="earliest",
            ack_policy=AckPolicy.ACK,
        )(_make_handler(index_name))
    return broker


def parse_topics() -> list[str]:
    return [t.strip() for t in settings.SEARCH_CDC_TOPICS.split(",") if t.strip()]


topics = parse_topics()
broker = build_broker(topics)
app = FastStream(broker)


@app.on_startup
async def bootstrap() -> None:
    from app.modules.search.registry import ensure_index_settings

    await ensure_index_settings(get_meili())
    logger.info("search_indexer_started", topics=topics, group=settings.SEARCH_CDC_GROUP_ID)


@app.on_shutdown
async def teardown() -> None:
    global _meili
    if _meili is not None:
        await _meili.aclose()
        _meili = None
    logger.info("search_indexer_shutdown")


def _setup_otel() -> None:
    """Standalone process — needs its own TracerProvider (same OTLP -> Alloy)."""
    if not settings.OTEL_ENABLED:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({SERVICE_NAME: settings.OTEL_SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{settings.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces"))
    )
    trace.set_tracer_provider(provider)


def main() -> None:
    import asyncio

    configure_logging()
    _setup_otel()
    if not topics:
        logger.error("search_indexer_no_topics", hint="set SEARCH_CDC_TOPICS")
        raise SystemExit(1)
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
