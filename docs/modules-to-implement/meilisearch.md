

### The True Enterprise Solution: Infrastructure-Level CDC

Because your project already runs **Debezium, Kafka (KRaft), and Postgres Logical Replication**, you have access to the absolute gold standard for search syncing: **Change Data Capture (CDC)**.

Instead of the application trying to double-write to a queue, the app *only* writes to Postgres. Debezium reads the database's Write-Ahead Log (WAL) instantly, streams the exact changes to Kafka, and a dedicated micro-worker pushes those changes to Meilisearch in high-throughput batches.

Here is the full, resilient, and enterprise-grade architecture.

---

### 1. The Debezium Configuration (`config/debezium/meilisearch-connector.json`)

This configures Debezium to watch your tables and stream a flattened JSON payload to Kafka. We use the `ExtractNewRecordState` transform so Debezium natively handles translating deletes into a `__deleted: true` flag.

```json
{
  "name": "meilisearch-sync-connector",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "postgres",
    "database.port": "5432",
    "database.user": "${POSTGRES_USER}",
    "database.password": "${POSTGRES_PASSWORD}",
    "database.dbname": "${POSTGRES_DB}",
    "database.server.name": "pg",
    "table.include.list": "public.products,public.users",
    "plugin.name": "pgoutput",
    "slot.name": "meilisearch_sync_slot",
    "publication.name": "meilisearch_publication",
    
    "transforms": "unwrap",
    "transforms.unwrap.type": "io.debezium.transforms.ExtractNewRecordState",
    "transforms.unwrap.drop.tombstones": "false",
    "transforms.unwrap.delete.handling.mode": "rewrite"
  }
}

```

*Register this using your existing `./manage.sh register-debezium` flow.*

---

### 2. The Kafka Indexer Worker (`app/modules/search/indexer.py`)

We create a dedicated, asynchronous Kafka consumer. This script runs entirely independently from FastAPI. It consumes events in **batches** (for massive throughput) and syncs them to Meilisearch.

*Requires `pip install aiokafka meilisearch-python-sdk*`

```python
import asyncio
import json
import structlog
from aiokafka import AIOKafkaConsumer
from meilisearch_python_sdk import AsyncClient
from app.core.conf import settings

logger = structlog.get_logger("app.search.indexer")

async def consume_cdc_events():
    """
    Consumes Debezium CDC streams and batch-upserts them to Meilisearch.
    """
    # Subscribe to the topics Debezium is generating
    consumer = AIOKafkaConsumer(
        "pg.public.products", 
        "pg.public.users",
        bootstrap_servers=settings.KAFKA_BROKERS,
        group_id="meilisearch-indexer-group",
        auto_offset_reset="earliest",
        enable_auto_commit=False, # We commit manually after Meilisearch succeeds
        value_deserializer=lambda m: json.loads(m.decode('utf-8')) if m else None
    )
    
    meili = AsyncClient(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY)
    
    await consumer.start()
    logger.info("search_indexer_started", topics=["pg.public.products", "pg.public.users"])
    
    try:
        while True:
            # Fetch up to 500 records or wait 1 second (High Throughput Batching)
            msg_pack = await consumer.getmany(timeout_ms=1000, max_records=500)
            
            for tp, messages in msg_pack.items():
                # Map topic 'pg.public.products' -> Meilisearch index 'products'
                index_name = tp.topic.split(".")[-1]
                index = meili.index(index_name)
                
                to_upsert = []
                to_delete = []
                
                for msg in messages:
                    payload = msg.value
                    if not payload:
                        continue
                        
                    doc_id = str(payload.get("id", payload.get("uuid")))
                    
                    # Debezium 'rewrite' mode flags deletions gracefully
                    if payload.get("__deleted") == "true":
                        to_delete.append(doc_id)
                    else:
                        payload.pop("__deleted", None)
                        to_upsert.append(payload)
                
                # Push batches to Meilisearch
                if to_upsert:
                    await index.add_documents(to_upsert)
                    logger.info("search_documents_upserted", index=index_name, count=len(to_upsert))
                
                if to_delete:
                    await index.delete_documents(to_delete)
                    logger.info("search_documents_deleted", index=index_name, count=len(to_delete))
            
            if msg_pack:
                # Acknowledge the offset only AFTER Meilisearch is updated (At-Least-Once guarantee)
                await consumer.commit()

    except asyncio.CancelledError:
        logger.info("search_indexer_shutting_down")
    except Exception as e:
        logger.exception("search_indexer_failed", error=str(e))
    finally:
        await consumer.stop()

if __name__ == "__main__":
    asyncio.run(consume_cdc_events())

```

---

### 3. The Scout Query Builder (`app/modules/search/builder.py`)

While the *syncing* is moved to the infrastructure layer, the *querying* still needs to be beautiful inside your FastAPI routes. This replicates Laravel Scout's developer experience for querying.

```python
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, Type
from app.core.conf import settings
from meilisearch_python_sdk import AsyncClient

# Shared async client for API queries
meili_client = AsyncClient(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY)

class ScoutBuilder:
    """
    Elegant search builder replicating Laravel Scout.
    Usage: await ScoutBuilder(Product, "gaming").where("category", "tech").limit(10).get(db)
    """
    def __init__(self, model_class: Type, query: str = ""):
        self.model_class = model_class
        self.index_name = model_class.__tablename__
        self.query = query
        self._filters = []
        self._limit = 20
        self._offset = 0
        
    def where(self, field: str, value: Any, operator: str = "=") -> 'ScoutBuilder':
        """Applies Meilisearch filters."""
        if isinstance(value, str):
            self._filters.append(f"{field} {operator} '{value}'")
        else:
            self._filters.append(f"{field} {operator} {value}")
        return self
        
    def limit(self, limit: int) -> 'ScoutBuilder':
        self._limit = limit
        return self

    def offset(self, offset: int) -> 'ScoutBuilder':
        self._offset = offset
        return self
        
    async def raw(self) -> dict:
        """Executes the search and returns raw Meilisearch JSON"""
        index = meili_client.index(self.index_name)
        
        kwargs = {"limit": self._limit, "offset": self._offset}
        if self._filters:
            kwargs["filter"] = " AND ".join(self._filters)
            
        return await index.search(self.query, **kwargs)

    async def get(self, db: AsyncSession) -> list:
        """
        Executes the search and beautifully hydrates the results from PostgreSQL,
        maintaining Meilisearch's exact relevance sorting order.
        """
        raw_data = await self.raw()
        hits = raw_data.hits
        
        if not hits:
            return []
            
        # Extract IDs maintaining Meilisearch's relevance order
        hit_ids = [int(hit["id"]) for hit in hits]
        
        # Hydrate from Database in a single query
        query = select(self.model_class).where(self.model_class.id.in_(hit_ids))
        result = await db.execute(query)
        records = result.scalars().all()
        
        # Re-sort the DB records to match the Meilisearch ranking
        record_map = {record.id: record for record in records}
        return [record_map[hid] for hid in hit_ids if hid in record_map]

```

---

### 4. How to run this in your Architecture

Because this indexer is a standalone Python process, you don't bog down your API or Celery workers. You simply add a new service to your `docker-compose.yml` that uses the exact same `backend` image, but runs the indexer command.

```yaml
# docker-compose.yml
  search-indexer:
    build:
      context: ./apps/core-platform/backend
    command: python -m app.modules.search.indexer
    environment:
      - ENVIRONMENT=production
      - MEILISEARCH_URL=http://meilisearch:7700
      - KAFKA_BROKERS=kafka:9092
    depends_on:
      - kafka
      - meilisearch

```

### Why this is a Masterclass in Enterprise Architecture:

1. **Absolute Reliability:** If your FastAPI server crashes, or Celery goes down, Kafka retains the changes. The moment the indexer boots back up, it picks up exactly where it left off.
2. **No N+1 / No App Load:** Your API threads are entirely freed from syncing duties. A bulk update of 100,000 products via an SQL script will trigger Debezium, which pushes to Kafka, and your Python indexer will chew through it in batches of 500 automatically.
3. **Data Agnostic:** By relying on `__tablename__`, any table you add to Debezium's `table.include.list` instantly flows into a Meilisearch index of the same name with zero extra Python code required.
4. **Developer Experience Preserved:** Despite upgrading the sync mechanism to an infrastructure-level stream, the developer writing the API endpoint still just types `await ScoutBuilder(Product, "laptop").get(db)`—combining the speed of Meilisearch with the data hydration of SQLAlchemy effortlessly.


----------------


This is the exact reason this CDC (Change Data Capture) architecture is the enterprise standard—it handles updates flawlessly and automatically, completely independent of your application code.

Because Debezium listens directly to the PostgreSQL **Write-Ahead Log (WAL)**, it catches *every* data change at the database engine level, regardless of how the update was triggered.

Here is exactly how an update flows through the system:

1. **The Database Changes:** You update a product. This could be a standard ORM update, a bulk SQLAlchemy `update()` query, or even a database administrator running a raw `UPDATE products SET price = 99.99 WHERE category = 'tech';` directly inside a GUI like pgAdmin.
2. **Debezium Captures the WAL:** PostgreSQL writes the transaction to its log. Debezium instantly reads this log, identifies the `UPDATE` event, and streams the new, fresh row data into the Kafka topic (`pg.public.products`).
3. **The Indexer Upserts:** The Python Kafka consumer reads the new JSON payload and passes it to Meilisearch using `index.add_documents()`.
4. **Meilisearch Overwrites:** In Meilisearch, `add_documents()` functions as an **upsert**. Because the payload contains an `id` that already exists in the Meilisearch index, Meilisearch automatically overwrites the old record with the new updated fields.

### Why this beats Application-Level Hooks (Like Laravel Scout)

If you were using standard ORM lifecycle events (the previous approach), you would run into a massive blind spot: **Bulk Updates**.

In SQLAlchemy (and Laravel's Eloquent), if you execute a bulk update:

```python
await db.execute(update(Product).where(Product.category == 'old').values(active=False))

```

The ORM does not load the models into memory, which means the `after_update` events **never fire**. Your database would have `active=False`, but Meilisearch would still show them as active.

With the Debezium/Kafka architecture, the database engine itself tells Kafka that rows were updated. Your Python indexer will automatically receive a stream of messages for every single row affected by that bulk query, and Meilisearch will perfectly mirror the database state in seconds, with zero extra code required.