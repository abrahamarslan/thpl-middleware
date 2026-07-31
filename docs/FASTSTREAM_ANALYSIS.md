# FastStream vs aiokafka Analysis for `search-indexer`

This document provides a deep architectural analysis of replacing the raw `aiokafka` consumer in `app/modules/search/indexer.py` with [FastStream](https://faststream.ag2.ai/) (verified against FastStream **0.7.1**, the current release — Python 3.10–3.14, aiokafka 0.14 under the hood).

## 1. Current Architecture Context
Your project currently uses Kafka exclusively for **Change Data Capture (CDC)**. 
- PostgreSQL WAL logs are read by **Debezium**.
- Debezium pushes these changes (inserts, updates, soft-deletes) to Kafka topics (`zoho-mirror.public.*`).
- A standalone consumer (`app/modules/search/indexer.py`), running as the `search-indexer` container in `docker-compose.yml`, consumes these topics and bulk-upserts the data into **Meilisearch** to keep the search index perfectly synchronized with the database.
- It uses a raw `aiokafka.AIOKafkaConsumer` with manual `getmany()` batching and manual offset commits to guarantee at-least-once delivery.

## 2. What You Will Gain (The Pros)

Replacing `aiokafka` with `FastStream` brings the Kafka consumer up to the exact same modern enterprise standards as the rest of your FastAPI application.

1. **Massive Boilerplate Reduction:**
   You currently have to manually manage `asyncio.new_event_loop()`, signal trapping (`SIGINT/SIGTERM`), and a bare `while True:` loop. FastStream manages the entire application lifecycle automatically. You just define the application and the subscriber. Note: a wildcard topic string is **not** valid — regex subscription goes through the `pattern=` parameter, and at-least-once delivery is configured with `AckPolicy.ACK` (the old `auto_commit=False` API was replaced in 0.6+):
   ```python
   from faststream import AckPolicy

   @broker.subscriber(
       pattern="zoho-mirror.public..*",   # regex, not a topic name
       group_id="search-indexer",
       ack_policy=AckPolicy.ACK,          # commit AFTER the handler succeeds (at-least-once)
       batch=True,
       max_records=500,
   )
   async def index_cdc_event(payloads: list[dict]):
       ...
   ```

2. **Native Pydantic Validation:**
   Currently, the indexer blindly parses `json.loads(m.decode())`. With FastStream, you can define a Pydantic schema for the Debezium payload and get automatic validation. Caveats: (a) FastStream does **not** ship a built-in Kafka DLQ — a validation failure raises and the message is retried/skipped per your ack policy; DLQ routing must be implemented explicitly (e.g. republish to a `*.dlq` topic in an exception middleware). (b) For a generic CDC consumer spanning arbitrary tables, typing the body as `list[dict]` (no strict model) is the right call — strict per-table models would defeat the "new table = zero code" property.

3. **Native OpenTelemetry (OTel) Integration:**
   Your stack uses OpenTelemetry heavily (`Alloy` -> `Tempo`). Right now, the `search-indexer` is a black box because `aiokafka` traces must be instrumented manually. FastStream ships an OTel middleware (`pip install "faststream[otel]"`, then `KafkaTelemetryMiddleware` on the broker) that plugs into the TracerProvider already configured by `app.core.observability`, giving end-to-end distributed tracing across the Kafka boundary with one line.

4. **Testing Ergonomics:**
   Currently, testing `indexer.py` requires a running Kafka container. FastStream provides a `TestKafkaBroker` (similar to FastAPI's `TestClient`) that allows you to fully unit-test your consumer logic locally and instantly.

## 3. What You Will Lose (The Cons/Risks)

1. **Low-Level Batching Control:**
   The current script uses `consumer.getmany(timeout_ms=1000)` to pull messages across *multiple topics simultaneously*. FastStream's `batch=True` (with `max_records` / `batch_timeout_ms`) batches per topic-partition at the subscriber level, so you lose the single global poll loop. In practice this loss is smaller than it looks: `getmany()` already returns messages **grouped per TopicPartition**, and `_flush_topic` is already invoked once per partition batch — the flush unit is identical. The real difference is offset-commit granularity: today one `commit()` covers all partitions in a tick; with FastStream each batch is committed independently after its handler succeeds (which is actually a tighter at-least-once window).

2. **Debezium Schema Rigidity:**
   Because FastStream uses Pydantic validation, you must strictly define the shape of the Debezium payload. If Debezium's schema evolves or a column is added to Postgres without updating the Pydantic model, FastStream might reject the message unless the schema is configured with `extra="ignore"`.

## 4. What it Will Break

If we execute this migration, the following things will break and must be updated in tandem:

1. **The `search-indexer` Container Command:**
   In `apps/core-platform/deployment/docker-compose.yml`, the startup command is:
   ```yaml
   command: python -m app.modules.search.indexer
   ```
   This will break. FastStream uses its own runner (requires the `faststream[cli]` extra). It must be updated to:
   ```yaml
   command: faststream run app.modules.search.indexer:app
   ```
   Alternatively, keep `python -m` and call `await app.run()` from a small `main()` — no CLI extra needed, and custom `configure_logging()` bootstrap is preserved.

2. **The Entire `indexer.py` File:**
   The current script is procedural. It will need to be completely rewritten declaratively using `FastStream` app and broker instances.

3. **`requirements.txt`:**
   Replace the direct `aiokafka>=0.12` pin with `faststream[kafka]>=0.7.1,<0.8` (aiokafka remains as FastStream's transitive dependency — FastStream 0.7 supports aiokafka 0.14). Add the `otel` extra for tracing and `cli` only if using the `faststream run` command. Update the README "one tool per job" note accordingly.

4. **Tests:**
   New consumer tests should use `faststream.kafka.TestKafkaBroker` — no Kafka container needed. Meilisearch calls in those tests are patched with the `mocker` fixture (pytest-mock, in requirements-dev.txt).

## 5. Conclusion
**Is it worth it?** Yes. 
The current `indexer.py` is functional but lacks observability, type-safety, and graceful error handling. FastStream will make the Kafka consumer feel exactly like writing a FastAPI route, vastly improving developer experience and production tracing, provided we carefully map the batching logic to FastStream's `batch=True` capabilities.

## 6. Status: IMPLEMENTED

The migration shipped. Final shape (differs slightly from the sketch above,
for the better):

- `indexer.py` registers **one batch subscriber per topic** via a
  `build_broker(topics)` factory — each handler closure knows its index
  name, so no `Context`/raw-message inspection and the broker is directly
  unit-testable (`tests/test_search_indexer.py`, via `TestKafkaBroker` +
  pytest-mock for Meilisearch).
- Entrypoint stayed `python -m app.modules.search.indexer` (calls
  `asyncio.run(app.run())`) — `configure_logging()` runs first, no
  `faststream[cli]` extra, **no compose change was needed**.
- Startup hook bootstraps Meilisearch index settings from
  `search/registry.py` (`SearchableEntity`) — the missing piece that made
  filtered search queries actually work.
- `KafkaTelemetryMiddleware` wired behind `OTEL_ENABLED` with a
  standalone TracerProvider (same OTLP → Alloy endpoint).
- `requirements.txt`: `aiokafka>=0.12` → `faststream[kafka]>=0.7.1,<0.8`.
