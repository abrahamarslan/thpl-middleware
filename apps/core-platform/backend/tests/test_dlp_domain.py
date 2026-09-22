"""Hubs, fleet partners and vehicles — route smoke + org-scoped service round-trip."""

import uuid

from sqlalchemy import select

from app.database.tenancy import tenant_scope
from app.modules.fleet_partners import service as fleet_service
from app.modules.fleet_partners.model import FleetPartner
from app.modules.fleet_partners.schema import FleetPartnerCreate
from app.modules.hubs import service as hub_service
from app.modules.hubs.model import Hub
from app.modules.hubs.schema import HubCreate
from app.modules.organizations.model import Organization
from app.modules.tenants.model import Tenant
from app.modules.vehicles import service as vehicle_service
from app.modules.vehicles.enums import VehicleOwnershipType, VehicleType
from app.modules.vehicles.model import Vehicle
from app.modules.vehicles.schema import VehicleCreate


def test_new_domain_routes_are_registered():
    from app.main import app

    paths = app.openapi()["paths"]
    for prefix in ("/api/hubs", "/api/fleet-partners", "/api/vehicles", "/api/driving-licenses"):
        assert prefix in paths, f"{prefix} not registered"


async def _tenant_with_org(db):
    code = f"DLP{uuid.uuid4().hex[:6].upper()}"
    tenant = Tenant(tenant_code=code, name=f"{code} Ltd", primary_contact_email=f"ops@{code.lower()}.example",
                    status="active")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        org = Organization(tenant_id=tenant.id, org_code=f"{code}-HQ", legal_name=f"{code} HQ",
                           org_type="solo", uuid=uuid.uuid4())
        db.add(org)
        await db.flush()
    return tenant, org


async def test_hub_fleet_partner_vehicle_create(db):
    tenant, org = await _tenant_with_org(db)
    with tenant_scope(tenant.id, org.id):
        hub = await hub_service.create_hub(db, HubCreate(code="HUB-1", name="Hub One"))
        assert hub.organization_id == org.id and hub.status == "active"

        partner = await fleet_service.create_partner(
            db, FleetPartnerCreate(code="FP-1", name="Partner One", gstin="24AAAAAAAAAAAAA")
        )
        assert partner.organization_id == org.id

        vehicle = await vehicle_service.create_vehicle(
            db,
            VehicleCreate(
                registration_number="GJ01 AB 1234",
                vehicle_type=VehicleType.TWO_WHEELER,
                ownership_type=VehicleOwnershipType.SELF_OWNED,
                fleet_partner_id=partner.id,
                hub_id=hub.id,
            ),
        )
        assert vehicle.registration_number == "GJ01AB1234"  # normalized
        assert vehicle.organization_id == org.id and vehicle.fleet_partner_id == partner.id

    assert (await db.scalar(select(Hub).where(Hub.id == hub.id))) is not None
    assert (await db.scalar(select(FleetPartner).where(FleetPartner.id == partner.id))) is not None
    assert (await db.scalar(select(Vehicle).where(Vehicle.id == vehicle.id))) is not None
