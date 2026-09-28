"""Zoho Books brand adapter — mapper, engine and scope-stamping tests.

Minimum coverage for a sync module (testing doctrine): mapper field extraction,
identity matching / no duplicates on re-sync, provenance, and the module-specific
behaviour this adapter adds — stamping the provenance pair and the slug fallback.
Zoho is always ``FakeZohoClient``; the real transport is exercised in
``tests/zoho_core/test_masters_e2e.py``.
"""

import pytest
from sqlalchemy import func, select

from app.database.tenancy import tenant_scope
from app.modules.brands import service
from app.modules.brands.model import Brand
from app.modules.brands.schema import BrandUpdate
from app.modules.brands.zoho.fields import FIELDS
from app.modules.brands.zoho.spec import BRANDS_CONFIG, BRANDS_TRANSLATOR, ZOHO_OWNED_BRAND_FIELDS
from app.modules.organizations.model import Organization
from app.modules.sync.models import SyncRecord
from app.modules.tenants.model import Tenant
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName
from app.modules.zoho.sync.engine import ZohoSyncEngine
from app.modules.zoho.sync.registry import sync_registry
from tests.zoho_sync.fake_client import FakeZohoClient

MODULE = "brands"

DABUR = {"brand_id": "954919000013118046", "name": "DABUR"}
HIMALAYA = {"brand_id": "954919000013143235", "name": "HIMALAYA"}


# ── hermetic: mapper, spec ───────────────────────────────────────────────────

def test_field_map_extracts_the_name():
    decoded = BRANDS_TRANSLATOR.decode(DABUR)
    assert decoded.values == {"name": "DABUR"}


def test_every_field_map_local_is_a_real_column():
    columns = set(Brand.__table__.c.keys())
    for spec in FIELDS:
        assert spec.local in columns, f"brands FIELDS.{spec.local} is not a column"


def test_owned_fields_are_derived_and_agree_with_the_service_guard():
    assert ZOHO_OWNED_BRAND_FIELDS == frozenset({"name"}) == frozenset(BRANDS_TRANSLATOR.readable)


def test_the_spec_declares_only_what_the_live_api_showed():
    """Each line was learned on the live, undocumented /brands endpoint (2026-09-28)."""
    cfg = BRANDS_CONFIG
    assert cfg.paginated is False and cfg.detail_required is False
    # last_modified_time is accepted but has no filtering effect live — never declare INCREMENTAL for that.
    assert cfg.strategy is SyncStrategyName.FULL and cfg.modified_since_param is None
    # only GET was verified; no push seam is offered.
    assert cfg.direction is SyncDirection.INBOUND
    assert cfg.contract.crosswalk and cfg.contract.match_on == ()   # never auto-merge on name
    assert cfg.contract.identity_echo == ("zoho_id",)
    sync_registry.validate()          # boot-time spec check (columns, codecs, echo) still passes


# ── integration: engine ─────────────────────────────────────────────────────

@pytest.fixture
async def world(db):
    tenant = Tenant(tenant_code="BRDSYNC", name="Brand Sync Ltd",
                    primary_contact_email="ops@brdsync.example", status="active")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        org = Organization(org_code="BRDSYNC-HQ", legal_name="Brand Sync HQ", tenant_id=tenant.id)
        db.add(org)
        await db.flush()
    await db.commit()
    return tenant, org


def _client(rows=None) -> FakeZohoClient:
    rows = rows if rows is not None else [DABUR, HIMALAYA]
    client = FakeZohoClient()
    client.stub_list("/brands", [rows])
    return client


async def _run_full(db, world, client: FakeZohoClient | None = None):
    tenant, org = world
    with tenant_scope(tenant.id, org.id):
        engine = ZohoSyncEngine(db, client or _client())
        report = await engine.run(MODULE, "full")
    await db.commit()
    return report


async def _brand(db, world, zoho_id: str) -> Brand:
    with tenant_scope(world[0].id, world[1].id):
        return await db.scalar(select(Brand).where(Brand.zoho_id == zoho_id)
                               .execution_options(include_deleted=True, populate_existing=True))


async def test_sync_creates_brands_with_scope_and_a_slug_fallback(db, world):
    tenant, org = world
    report = await _run_full(db, world)
    assert report.status in ("success", "partial")

    dabur = await _brand(db, world, DABUR["brand_id"])
    himalaya = await _brand(db, world, HIMALAYA["brand_id"])
    assert dabur is not None and himalaya is not None
    assert dabur.name == "DABUR" and dabur.slug == "dabur"          # slug fallback
    assert dabur.organization_id == org.id and dabur.tenant_id == tenant.id
    assert dabur.owner_type == "organization" and dabur.owner_id == org.id
    assert dabur.parent_id is None                                  # Zoho names no hierarchy

    record = await db.scalar(select(SyncRecord).where(SyncRecord.module == MODULE,
                                                       SyncRecord.external_id == DABUR["brand_id"]))
    assert record is not None and record.entity_id == dabur.id


async def test_resync_matches_identity_and_does_not_duplicate(db, world):
    await _run_full(db, world)
    first = await _brand(db, world, DABUR["brand_id"])
    first_id = first.id

    await _run_full(db, world)
    count = await db.scalar(select(func.count()).select_from(Brand).execution_options(include_deleted=True))
    assert count == 2
    again = await _brand(db, world, DABUR["brand_id"])
    assert again.id == first_id


async def test_a_zoho_side_rename_updates_the_local_row(db, world):
    await _run_full(db, world)
    renamed = _client([{**DABUR, "name": "DABUR INDIA"}, HIMALAYA])
    await _run_full(db, world, renamed)
    dabur = await _brand(db, world, DABUR["brand_id"])
    assert dabur.name == "DABUR INDIA"


async def test_a_local_brand_with_the_same_name_is_never_silently_merged(db, world):
    """match_on=() — the taxes precedent: never invent a match. A genuine name collision
    fails loudly at the partial unique index instead of merging into the local row."""
    tenant, org = world
    with tenant_scope(tenant.id, org.id):
        from app.modules.entities.enums import MasterOwnerType

        local = Brand(name="DABUR", organization_id=org.id, owner_type=MasterOwnerType.ORGANIZATION.value,
                     owner_id=org.id)
        db.add(local)
        await db.flush()
        local_id = local.id
    await db.commit()

    report = await _run_full(db, world, _client([DABUR]))
    assert report.errors == 1          # the collision failed the record, not the run

    # the local row is untouched — no zoho_id, no merge
    with tenant_scope(tenant.id, org.id):
        untouched = await db.get(Brand, local_id)
    assert untouched.zoho_id is None and untouched.name == "DABUR"
    assert await db.scalar(select(func.count()).select_from(Brand)
                           .where(Brand.zoho_id == DABUR["brand_id"])) == 0


async def test_synced_row_local_edit_to_the_name_is_refused(db, world):
    await _run_full(db, world)
    row = await _brand(db, world, DABUR["brand_id"])
    with tenant_scope(world[0].id, world[1].id):
        with pytest.raises(Exception) as excinfo:
            await service.update_brand(
                db, str(row.uuid), BrandUpdate(name="Renamed", row_version=row.row_version),
            )
    assert "owned by Zoho" in str(excinfo.value)


async def test_synced_row_local_edit_to_an_unowned_field_is_allowed(db, world):
    """Only `name` is Zoho-fed; everything else stays fully locally editable."""
    await _run_full(db, world)
    row = await _brand(db, world, DABUR["brand_id"])
    with tenant_scope(world[0].id, world[1].id):
        updated = await service.update_brand(
            db, str(row.uuid), BrandUpdate(country_code="IN", row_version=row.row_version),
        )
    assert updated.country_code == "IN"
