"""Location hub: places, the polymorphic address book, and the guarantees
the database makes about them (docs/geo/README.md)."""

import datetime as dt

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database.tenancy import Actor, tenant_scope
from app.modules.geo import service
from app.modules.geo.enums import LinkType, PlaceKind, VerificationStatus
from app.modules.geo.model import Place, PlaceLink
from app.modules.geo.schema import AddressCreate, PlaceCreate, PlaceUpdate, PlaceVerify
from app.modules.organizations.model import Organization
from app.modules.tenants.model import Tenant

#: A real point in Pune — the generated columns are checked against it.
PUNE = (18.5204, 73.8567)


async def _world(db, code: str = "GEO") -> tuple[Tenant, Organization]:
    tenant = Tenant(tenant_code=code, name=f"Tenant {code}", primary_contact_email=f"ops@{code.lower()}.test")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        org = Organization(org_code=f"{code}-HQ", legal_name=f"{code} HQ", tenant_id=tenant.id)
        db.add(org)
        await db.flush()
    return tenant, org


def _place_body(**kw) -> PlaceCreate:
    body = {
        "kind": PlaceKind.CUSTOMER_SITE, "location_name": "Acme Works",
        "street": "12 MG Road", "city": "Pune", "state": "Maharashtra", "postal_code": "411001",
        "latitude": PUNE[0], "longitude": PUNE[1],
    }
    body.update(kw)
    return PlaceCreate(**body)


# ── the coordinate ──────────────────────────────────────────────────────────

async def test_postgres_generates_the_decimals_and_the_geohash(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id, Actor(1, "Asha")):
        place = await service.create_place(db, _place_body(), actor_id=1)
        await db.commit()
        await db.refresh(place)

    assert float(place.latitude) == pytest.approx(PUNE[0], abs=1e-6)
    assert float(place.longitude) == pytest.approx(PUNE[1], abs=1e-6)
    assert place.geohash8 and len(place.geohash8) == 8
    # The application cannot write them, so they can never disagree.
    with pytest.raises(Exception):
        await db.execute(text("UPDATE geo.places SET latitude = 0 WHERE id = :i"), {"i": place.id})
    await db.rollback()


async def test_the_address_line_is_composed_when_not_given(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        place = await service.create_place(db, _place_body())
    assert "12 MG Road" in place.formatted_address
    assert "Pune" in place.formatted_address and "411001" in place.formatted_address


async def test_a_second_place_at_the_same_doorway_is_reused(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        first = await service.create_place(db, _place_body())
        # 5 m away, spelled differently — the same door.
        again = await service.create_place(db, _place_body(
            location_name="ACME WORKS", street="12, M.G. Road",
            latitude=PUNE[0] + 0.00004, longitude=PUNE[1],
        ))
        assert again.id == first.id

        separate = await service.create_place(
            db, _place_body(location_name="Other", latitude=19.0760, longitude=72.8777),
            reuse_duplicates=False,
        )
        assert separate.id != first.id


async def test_nearby_finds_places_in_a_radius(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        await service.create_place(db, _place_body())
        await service.create_place(db, _place_body(
            location_name="Mumbai site", latitude=19.0760, longitude=72.8777), reuse_duplicates=False)
        await db.flush()

        close = await service.nearby_places(db, latitude=PUNE[0], longitude=PUNE[1], radius_m=5_000)
        assert [p.location_name for p in close] == ["Acme Works"]
        both = await service.nearby_places(db, latitude=PUNE[0], longitude=PUNE[1], radius_m=200_000)
        assert len(both) == 2


# ── tenancy ─────────────────────────────────────────────────────────────────

async def test_places_are_invisible_to_another_tenant(db):
    acme_tenant, acme_org = await _world(db, "ACME")
    globex_tenant, globex_org = await _world(db, "GLOBEX")

    with tenant_scope(acme_tenant.id, acme_org.id):
        await service.create_place(db, _place_body(location_name="Acme site"))
        await db.flush()
    with tenant_scope(globex_tenant.id, globex_org.id):
        assert await service.list_places(db) == []
        await service.create_place(db, _place_body(location_name="Globex site"))
        await db.flush()
        assert [p.location_name for p in await service.list_places(db)] == ["Globex site"]


async def test_the_database_refuses_another_tenants_organization(db):
    _, acme_org = await _world(db, "ACME")
    globex_tenant, _ = await _world(db, "GLOBEX")
    db.add(Place(kind="address", tenant_id=globex_tenant.id, organization_id=acme_org.id, country="India"))
    with pytest.raises(IntegrityError, match="fk_places_tenant_org"):
        await db.flush()
    await db.rollback()


async def test_the_single_organization_is_resolved_without_a_header(db):
    tenant, _ = await _world(db, "SOLO")
    await _world(db, "OTHER")          # another tenant's org must not be picked
    with tenant_scope(tenant.id):
        place = await service.create_place(db, _place_body())
        assert place.organization_id is not None
        assert place.tenant_id == tenant.id


async def test_with_several_organizations_the_caller_must_choose(db):
    """``organization_id`` is NOT NULL here, so the ambiguity has to surface as
    a readable error rather than an IntegrityError."""
    tenant, _ = await _world(db, "MULTI")
    with tenant_scope(tenant.id):
        db.add(Organization(org_code="MULTI-2", legal_name="Second entity", tenant_id=tenant.id))
        await db.flush()
        with pytest.raises(service.GeoRuleError, match="X-Organization-Id"):
            await service.create_place(db, _place_body())


# ── the address book ────────────────────────────────────────────────────────

async def test_attaching_an_address_creates_the_place_in_one_call(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id, Actor(7, "Ops")):
        link = await service.attach_address(db, AddressCreate(
            owner_type="customer", owner_id=42, link_type=LinkType.BILLING,
            new_place=_place_body(), is_primary=True,
        ), actor_id=7)

    assert link.owner_type == "customer" and link.owner_id == 42
    assert link.link_type == "billing" and link.is_primary
    assert link.place.location_name == "Acme Works"
    assert link.created_by == 7 and link.created_by_name == "Ops"
    assert link.snapshot is None                      # live link, not frozen


async def test_many_owners_share_one_place(db):
    """The point of a canonical place: one row, many owners."""
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        first = await service.attach_address(db, AddressCreate(
            owner_type="customer", owner_id=1, new_place=_place_body()))
        second = await service.attach_address(db, AddressCreate(
            owner_type="invoice", owner_id=99, link_type=LinkType.SHIPPING,
            place=first.place.uuid))
        assert second.place_id == first.place_id
        assert await db.scalar(select(text("count(*)")).select_from(Place)) == 1


async def test_a_frozen_address_survives_the_place_changing(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        live = await service.attach_address(db, AddressCreate(
            owner_type="customer", owner_id=1, new_place=_place_body()))
        frozen = await service.attach_address(db, AddressCreate(
            owner_type="invoice", owner_id=500, link_type=LinkType.BILLING,
            place=live.place.uuid, freeze=True))
        assert frozen.snapshot["street"] == "12 MG Road"

        place = await service.get_place(db, live.place.uuid)
        await service.update_place(db, str(place.uuid), PlaceUpdate(
            street="99 New Road", row_version=place.row_version))
        await db.flush()

        # The invoice still prints what it printed.
        reread = await service.get_address(db, frozen.uuid)
        assert reread.snapshot["street"] == "12 MG Road"
        assert reread.place.street == "99 New Road"


async def test_a_frozen_address_cannot_be_edited_or_detached(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        frozen = await service.attach_address(db, AddressCreate(
            owner_type="invoice", owner_id=7, new_place=_place_body(), freeze=True))
        with pytest.raises(service.GeoRuleError):
            await service.detach_address(db, str(frozen.uuid), reason="oops")


async def test_only_one_primary_address_per_owner_and_type(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        first = await service.attach_address(db, AddressCreate(
            owner_type="customer", owner_id=5, link_type=LinkType.SHIPPING,
            new_place=_place_body(), is_primary=True))
        second = await service.attach_address(db, AddressCreate(
            owner_type="customer", owner_id=5, link_type=LinkType.SHIPPING, is_primary=True,
            new_place=_place_body(location_name="Second dock", latitude=19.0760, longitude=72.8777)))
        await db.flush()
        await db.refresh(first)
        assert second.is_primary and not first.is_primary


async def test_a_customer_may_hold_many_shipping_addresses(db):
    """Many-valued types are not squeezed by the no-overlap rule."""
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        for n, (lat, lng) in enumerate([(18.52, 73.85), (19.07, 72.87), (12.97, 77.59)]):
            await service.attach_address(db, AddressCreate(
                owner_type="customer", owner_id=8, link_type=LinkType.SHIPPING,
                new_place=_place_body(location_name=f"Dock {n}", latitude=lat, longitude=lng)))
        await db.flush()
        rows = await service.list_addresses(db, owner_type="customer", owner_id=8)
        assert len(rows) == 3


async def test_a_new_current_address_closes_the_old_one(db):
    """Single-valued types keep a history instead of overwriting it."""
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        old = await service.attach_address(db, AddressCreate(
            owner_type="user", owner_id=3, link_type=LinkType.CURRENT, new_place=_place_body()))
        new = await service.attach_address(db, AddressCreate(
            owner_type="user", owner_id=3, link_type=LinkType.CURRENT,
            valid_from=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=1),
            new_place=_place_body(location_name="New home", latitude=19.0760, longitude=72.8777)))
        await db.flush()
        await db.refresh(old)

        assert old.valid_to is not None and new.valid_to is None
        current = await service.list_addresses(db, owner_type="user", owner_id=3)
        assert [row.id for row in current] == [new.id]
        history = await service.address_history(db, owner_type="user", owner_id=3)
        assert {row.id for row in history} == {old.id, new.id}


async def test_the_database_refuses_two_overlapping_current_addresses(db):
    """The EXCLUDE constraint, reached by going around the service."""
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        first = await service.attach_address(db, AddressCreate(
            owner_type="user", owner_id=11, link_type=LinkType.CURRENT, new_place=_place_body()))
        await db.flush()
        db.add(PlaceLink(
            tenant_id=tenant.id, organization_id=org.id, place_id=first.place_id,
            owner_type="user", owner_id=11, link_type="current",
            valid_from=dt.datetime.now(dt.UTC), purpose="x",
        ))
        with pytest.raises(IntegrityError, match="place_links_no_overlap"):
            await db.flush()
    await db.rollback()


async def test_detaching_records_who_and_why(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id, Actor(9, "Ops")):
        link = await service.attach_address(db, AddressCreate(
            owner_type="customer", owner_id=2, new_place=_place_body()))
        await service.detach_address(db, str(link.uuid), reason="moved out", actor_id=9)
        await db.flush()
    assert link.deleted_at is not None and link.deleted_by == 9
    assert link.deleted_reason == "moved out" and link.valid_to is not None


# ── verification, versions, lifecycle ───────────────────────────────────────

async def test_verifying_records_the_evidence(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        place = await service.create_place(db, _place_body())
        assert place.verification_status == VerificationStatus.UNVERIFIED.value and not place.is_verified

        await service.verify_place(db, str(place.uuid), PlaceVerify(
            verification_method="field_visit", verification_data={"photo": "f-1"},
        ), actor_id=4)
        assert place.is_verified and place.verification_status == "field_verified"
        assert place.verified_by == 4 and place.verified_at is not None


async def test_moving_a_place_drops_its_verification(db):
    """Whoever stood at the old point did not vouch for the new one."""
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        place = await service.create_place(db, _place_body())
        await service.verify_place(db, str(place.uuid), PlaceVerify(verification_method="field_visit"))
        await db.flush()

        await service.update_place(db, str(place.uuid), PlaceUpdate(
            latitude=19.0760, longitude=72.8777, row_version=place.row_version))
        assert not place.is_verified and place.verification_status == "unverified"


async def test_a_stale_row_version_is_refused(db):
    from app.common.exception.errors import ConflictError

    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        place = await service.create_place(db, _place_body())
        await db.flush()
        with pytest.raises(ConflictError, match="changed since you loaded it"):
            await service.update_place(db, str(place.uuid), PlaceUpdate(
                location_name="Renamed", row_version=place.row_version + 5))


async def test_a_place_in_use_cannot_be_deleted_but_can_be_archived(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        link = await service.attach_address(db, AddressCreate(
            owner_type="customer", owner_id=1, new_place=_place_body()))
        await db.flush()
        with pytest.raises(service.GeoRuleError, match="still point at this place"):
            await service.delete_place(db, str(link.place.uuid), reason="cleanup")

        archived = await service.archive_place(db, str(link.place.uuid), reason="site closed", actor_id=2)
        assert archived.status == "archived" and archived.deactivation_reason == "site closed"
        assert archived.deactivated_by == 2 and archived.deactivation_date is not None


async def test_zoho_owned_fields_are_read_only_on_a_zoho_place(db):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        place = await service.create_place(db, _place_body())
        place.zoho_id = "46000001"
        await db.flush()
        with pytest.raises(service.GeoRuleError, match="owned by Zoho"):
            await service.update_place(db, str(place.uuid), PlaceUpdate(
                location_name="Local rename", row_version=place.row_version))
        # Fields Zoho does not own stay editable.
        await service.update_place(db, str(place.uuid), PlaceUpdate(
            landmark="Near the tank", row_version=place.row_version))
        assert place.landmark == "Near the tank"


async def test_a_zoho_location_becomes_an_addressable_place(db):
    from app.modules.locations.model import ZohoLocation

    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        location = ZohoLocation(
            zoho_id="46000123", location_name="Head Office", zoho_status="active", is_primary=True,
            address_street1="5 Industrial Estate", address_city="Pune", address_state="Maharashtra",
            address_country="India", phone="+912012345678", email="hq@acme.test",
            organization_id=org.id,
        )
        db.add(location)
        await db.flush()

        place = await service.upsert_place_from_zoho_location(db, location)
        assert place.zoho_id == "46000123" and place.kind == PlaceKind.WAREHOUSE.value
        assert place.location_name == "Head Office" and place.is_primary
        assert "5 Industrial Estate" in place.formatted_address

        location.location_name = "Head Office (moved)"
        again = await service.upsert_place_from_zoho_location(db, location)
        assert again.id == place.id and again.location_name == "Head Office (moved)"
