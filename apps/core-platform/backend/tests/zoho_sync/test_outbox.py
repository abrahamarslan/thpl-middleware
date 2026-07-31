"""Outbox pattern integration tests (real Postgres, fake Zoho client).

Covers the three outbound flows: create (zoho_id back-fill), update, delete
— plus failure bookkeeping (sync_error / sync_attempt_count / queue log).
"""

import pytest

from app.modules.zoho.core.exceptions import ZohoApiError
from app.modules.zoho.organizations.model import ZohoOrganization
from app.modules.zoho.sync import outbox
from app.modules.zoho.sync.mixins import SyncStatus
from tests.zoho_sync.fake_client import FakeZohoClient, make_response


async def _make_local_org(db, **overrides) -> ZohoOrganization:
    org = ZohoOrganization(name="Local Born Org", email="ops@local.example", **overrides)
    db.add(org)
    await db.flush()
    return org


async def test_outbound_create_backfills_zoho_id(db):
    org = await _make_local_org(db)
    assert org.zoho_id is None

    client = FakeZohoClient()
    client.stub("POST", "/organizations", make_response({"organization_id": "999888", "name": "Local Born Org"}))

    result = await outbox.push_record(db, client, "organizations", org.id, "create")
    await db.commit()

    assert result == {"op": "create", "zoho_id": "999888"}
    assert org.zoho_id == "999888"
    assert org.sync_status == SyncStatus.SYNCED.value
    assert org.sync_error is None
    # The payload sent to Zoho came from the outbound field map
    post = next(c for c in client.calls if c["method"] == "POST")
    assert post["json"]["name"] == "Local Born Org"
    assert post["json"]["email"] == "ops@local.example"


async def test_outbound_update_puts_to_detail_path(db):
    org = await _make_local_org(db, zoho_id="777")
    client = FakeZohoClient()
    client.stub("PUT", "/organizations/777", make_response({"organization_id": "777"}))

    result = await outbox.push_record(db, client, "organizations", org.id, "update")
    assert result["zoho_id"] == "777"
    assert client.calls[-1]["method"] == "PUT"


async def test_outbound_update_without_zoho_id_escalates_to_create(db):
    """Local row updated before its create ever reached Zoho -> create."""
    org = await _make_local_org(db)
    client = FakeZohoClient()
    client.stub("POST", "/organizations", make_response({"organization_id": "555"}))

    result = await outbox.push_record(db, client, "organizations", org.id, "update")
    assert result == {"op": "create", "zoho_id": "555"}
    assert org.zoho_id == "555"


async def test_outbound_delete_marks_row_deleted_status(db):
    org = await _make_local_org(db, zoho_id="333")
    client = FakeZohoClient()
    client.stub("DELETE", "/organizations/333", make_response({}))

    result = await outbox.push_record(db, client, "organizations", org.id, "delete")
    assert result["op"] == "delete"
    assert org.sync_status == SyncStatus.DELETED.value


async def test_outbound_failure_records_error_and_reraises(db):
    org = await _make_local_org(db)
    client = FakeZohoClient()
    client.stub("POST", "/organizations", ZohoApiError("Zoho exploded", http_status=502))

    with pytest.raises(ZohoApiError):
        await outbox.push_record(db, client, "organizations", org.id, "create")

    assert org.sync_status == SyncStatus.ERROR.value
    assert "Zoho exploded" in (org.sync_error or "")
    assert org.sync_attempt_count == 1
    assert org.zoho_id is None  # unchanged — retry will try again


async def test_queue_outbound_rejects_inbound_only_modules(db, monkeypatch):
    """Direction guard: a module configured inbound-only cannot enqueue pushes."""
    from app.common.exception.errors import ConflictError
    from app.modules.zoho.sync.config import SyncDirection
    from app.modules.zoho.sync.registry import sync_registry

    defn = sync_registry.get("organizations")
    monkeypatch.setattr(defn.config, "direction", SyncDirection.INBOUND)
    with pytest.raises(ConflictError):
        await outbox.queue_outbound(db, "organizations", 1, "update")
