"""Organizations module — registration, config resolution, service flows."""

import pytest

from app.modules.zoho.organizations import ORGANIZATIONS_CONFIG
from app.modules.zoho.organizations import crud, service
from app.modules.zoho.organizations.model import ZohoOrganization
from app.modules.zoho.organizations.schema import OrganizationCreate, OrganizationUpdate
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName
from app.modules.zoho.sync.mixins import SyncStatus
from app.modules.zoho.sync.registry import sync_registry


def test_module_registered_with_expected_config():
    defn = sync_registry.get("organizations")
    cfg = defn.config
    assert defn.model is ZohoOrganization
    assert cfg is ORGANIZATIONS_CONFIG
    assert cfg.endpoint == "/organizations"
    assert cfg.zoho_id_attr == "organization_id"
    assert cfg.strategy is SyncStrategyName.FULL
    assert cfg.direction is SyncDirection.BIDIRECTIONAL
    assert cfg.detail_required is True
    assert cfg.detail_dispatch == "inline"
    assert cfg.modified_since_param is None  # no incremental support upstream
    # Every mapped local column actually exists on the model
    for mapping in cfg.field_map:
        assert hasattr(ZohoOrganization, mapping.local), mapping.local


def test_server_managed_fields_never_push_outbound():
    read_only = {"is_default_org", "is_org_active", "user_role", "user_status",
                 "account_created_date", "currency_id", "price_precision"}
    for mapping in ORGANIZATIONS_CONFIG.field_map:
        if mapping.local in read_only:
            assert mapping.outbound is False, mapping.local


async def test_service_create_writes_local_first_and_queues_push(db, monkeypatch):
    queued: list[tuple] = []

    async def fake_queue(db_, module, local_id, op):
        queued.append((module, local_id, op))

    monkeypatch.setattr(service, "queue_outbound", fake_queue)

    org = await service.create_organization(
        db, OrganizationCreate(name="New Org", email="a@b.co"), actor_id=None
    )
    await db.commit()

    assert org.id is not None
    assert org.zoho_id is None                       # outbox will back-fill
    assert org.sync_status == SyncStatus.QUEUED.value
    assert queued == [("organizations", org.id, "create")]


async def test_service_update_and_get_by_either_ref(db, monkeypatch):
    async def fake_queue(db_, module, local_id, op):
        pass

    monkeypatch.setattr(service, "queue_outbound", fake_queue)

    org = await service.create_organization(db, OrganizationCreate(name="Ref Org"))
    org.zoho_id = "424242"
    await db.commit()

    by_local = await service.get_organization(db, str(org.id))
    by_zoho = await service.get_organization(db, "424242")
    assert by_local.id == by_zoho.id

    updated = await service.update_organization(
        db, "424242", OrganizationUpdate(address_city="Chennai")
    )
    assert updated.address_city == "Chennai"
    assert updated.sync_status == SyncStatus.QUEUED.value


async def test_service_delete_soft_deletes_and_hides(db, monkeypatch):
    async def fake_queue(db_, module, local_id, op):
        pass

    monkeypatch.setattr(service, "queue_outbound", fake_queue)

    org = await service.create_organization(db, OrganizationCreate(name="Doomed Org"))
    await db.commit()
    await service.delete_organization(db, str(org.id))
    await db.commit()

    from app.common.exception.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await service.get_organization(db, str(org.id))
    # Still present for the sync engine (identity matching / delete push)
    ghost = await crud.get(db, org.id, include_deleted=True)
    assert ghost is not None and ghost.deleted_at is not None


async def test_list_filters_active_only(db):
    db.add(ZohoOrganization(name="Active", is_org_active=True))
    db.add(ZohoOrganization(name="Dormant", is_org_active=False))
    await db.flush()

    everyone = await crud.list_all(db)
    active = await crud.list_all(db, active_only=True)
    assert {o.name for o in everyone} == {"Active", "Dormant"}
    assert {o.name for o in active} == {"Active"}


def test_api_routes_mounted():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/zoho/organizations" in paths
    assert "/api/zoho/organizations/{ref}" in paths
    assert "/api/zoho/organizations/sync" in paths
    assert "/api/zoho/sync-engine/modules" in paths
    assert "/api/zoho/sync-engine/modules/{module}/run" in paths
