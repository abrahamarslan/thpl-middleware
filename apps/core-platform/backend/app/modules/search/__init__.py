"""Search module — Meilisearch fed by infrastructure-level CDC.

Indexing: the app only writes Postgres. Debezium reads the WAL, streams row
changes to Kafka, and the standalone indexer (python -m
app.modules.search.indexer — its own compose service) batch-upserts them
into Meilisearch. Bulk SQL updates, admin edits, sync-engine upserts — all
indexed identically, because the database itself is the event source.

Querying: ScoutBuilder (builder.py) gives Laravel-Scout ergonomics —
Meilisearch ranks, Postgres hydrates, relevance order preserved.
"""
