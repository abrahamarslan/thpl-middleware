"""Search indexer (FastStream) + registry tests.

The consumer is exercised through TestKafkaBroker — no Kafka container
needed; Meilisearch is mocked with pytest-mock's `mocker` fixture (the
house pattern for external systems below the FastAPI DI boundary).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from faststream.kafka import TestKafkaBroker

from app.modules.search import indexer
from app.modules.search.registry import SEARCHABLE_ENTITIES, ensure_index_settings

TOPIC = "zoho-mirror.public.zoho_organizations"


# ── Pure helpers ──────────────────────────────────────────────────────────────


def test_document_id_priority_order():
    assert indexer._document_id({"id": 7, "contact_id": 9}) == "7"
    assert indexer._document_id({"contact_id": 9}) == "9"
    assert indexer._document_id({"name": "no pk"}) is None


def test_is_delete_flags():
    assert indexer._is_delete({"__deleted": "true"}) is True
    assert indexer._is_delete({"__deleted": "false"}) is False
    assert indexer._is_delete({"deleted_at": "2026-01-01T00:00:00Z"}) is True  # soft delete
    assert indexer._is_delete({"deleted_at": None}) is False


def test_sanitise_strips_debezium_fields():
    doc = indexer._sanitise({"id": 1, "__deleted": "false", "__op": "u", "name": "x"})
    assert doc == {"id": 1, "name": "x"}


def test_partition_batch_unwraps_connect_schema_envelope():
    """JsonConverter with schemas.enable wraps rows in {schema, payload}."""
    upserts, deletes = indexer.partition_batch(
        [
            {"schema": {"type": "struct"}, "payload": {"id": 9, "name": "Enveloped"}},
            {"schema": {"type": "struct"}, "payload": None},  # enveloped tombstone
        ]
    )
    assert [d["id"] for d in upserts] == [9]
    assert deletes == []


def test_partition_batch_splits_upserts_and_deletes():
    upserts, deletes = indexer.partition_batch(
        [
            {"id": 1, "name": "Acme", "__deleted": "false"},
            {"id": 2, "__deleted": "true"},
            {"id": 3, "deleted_at": "2026-01-01"},  # soft delete -> removal
            None,  # tombstone -> skipped
            {"name": "no pk"},  # unidentifiable -> skipped
        ]
    )
    assert [d["id"] for d in upserts] == [1]
    assert deletes == ["2", "3"]


# ── Consumer pipeline via TestKafkaBroker ─────────────────────────────────────


@pytest.fixture
def meili_index(mocker):
    """Patch the module-level Meilisearch client; return the index mock."""
    index = MagicMock()
    index.add_documents = AsyncMock()
    index.delete_documents = AsyncMock()
    client = MagicMock()
    client.index.return_value = index
    mocker.patch.object(indexer, "get_meili", return_value=client)
    return index


async def test_consumer_upserts_and_deletes(meili_index):
    broker = indexer.build_broker([TOPIC])
    async with TestKafkaBroker(broker) as br:
        await br.publish_batch(
            {"id": 1, "name": "Acme Corp", "__deleted": "false"},
            {"id": 2, "__deleted": "true"},
            topic=TOPIC,
        )

    meili_index.add_documents.assert_awaited_once()
    (docs,) = meili_index.add_documents.await_args.args
    assert docs == [{"id": 1, "name": "Acme Corp"}]
    # Explicit primary key — Meili can't infer one from CDC rows full of *_id columns.
    assert meili_index.add_documents.await_args.kwargs["primary_key"] == "id"

    meili_index.delete_documents.assert_awaited_once()
    (ids,) = meili_index.delete_documents.await_args.args
    assert ids == ["2"]


async def test_consumer_index_name_derived_from_topic(meili_index, mocker):
    broker = indexer.build_broker([TOPIC])
    client = indexer.get_meili()
    async with TestKafkaBroker(broker) as br:
        await br.publish_batch({"id": 5, "name": "X"}, topic=TOPIC)
    client.index.assert_called_with("zoho_organizations")


# ── Registry / index-settings bootstrap ───────────────────────────────────────


def test_registry_entities_resolve():
    entity = SEARCHABLE_ENTITIES["zoho_organizations"]
    model = entity.resolve_model()
    schema = entity.resolve_schema()
    assert model.__tablename__ == "zoho_organizations"
    assert hasattr(schema, "model_validate")
    # Every filterable/searchable attribute must exist on the model — a typo
    # here would surface as an opaque Meilisearch error in production.
    for attr in [*entity.filterable, *entity.searchable, *entity.sortable]:
        assert hasattr(model, attr), f"{attr} not on {model.__name__}"


async def test_ensure_index_settings_applies_all(mocker):
    index = MagicMock()
    index.update_searchable_attributes = AsyncMock()
    index.update_filterable_attributes = AsyncMock()
    index.update_sortable_attributes = AsyncMock()
    client = MagicMock()
    client.index.return_value = index

    await ensure_index_settings(client)

    entity = SEARCHABLE_ENTITIES["zoho_organizations"]
    index.update_searchable_attributes.assert_awaited_with(entity.searchable)
    index.update_filterable_attributes.assert_awaited_with(entity.filterable)
    index.update_sortable_attributes.assert_awaited_with(entity.sortable)
