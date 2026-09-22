"""User location: telemetry tables, the `/me/location` endpoints, and the
`primary_place_id` cache the address book maintains.

Three layers per `<testing_doctrine>`:
  unit          the WKT conversion (longitude first) and the request schema;
  integration   the live/ping write path and its isolation from `users`;
  integration   the address-book hook that keeps `users.primary_place_id` true.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.database.tenancy import tenant_scope
from app.modules.geo.schema import AddressCreate, PlaceCreate
from app.modules.users import crud, service
from app.modules.users.model import User, UserLiveLocation, UserLocationPing
from app.modules.users.schema import LocationUpdate

# Tarrina's own district — the platform's actual operating area.
GODHRA = {"latitude": 22.7772, "longitude": 73.6203}


# ── unit ────────────────────────────────────────────────────────────────────

def test_the_point_helper_puts_longitude_first():
    """PostGIS is (longitude, latitude); the wire format is the other way round.
    Getting this backwards silently places every user in the wrong hemisphere."""
    element = crud.point(**GODHRA)
    assert element.srid == 4326
    assert element.data == "POINT(73.6203 22.7772)"


def test_the_request_schema_refuses_impossible_fixes():
    for bad in (
        {"latitude": 91, "longitude": 0},
        {"latitude": 0, "longitude": 181},
        {"latitude": 0, "longitude": 0, "heading_deg": 360},
        {"latitude": 0, "longitude": 0, "accuracy_m": -1},
        {"latitude": 0, "longitude": 0, "location_source": "carrier-pigeon"},
    ):
        with pytest.raises(ValueError):
            LocationUpdate(**bad)


# ── integration ─────────────────────────────────────────────────────────────

async def test_a_fix_upserts_the_live_row_and_appends_to_the_history(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)

    first = await client.patch("/api/me/location", headers=headers,
                               json={**GODHRA, "accuracy_m": 8.5, "location_source": "gps",
                                     "tracking_active": True, "device_id": "dlp-001"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["msg"] == "Location recorded successfully."
    assert body["data"]["latitude"] == pytest.approx(GODHRA["latitude"])
    assert body["data"]["longitude"] == pytest.approx(GODHRA["longitude"])
    assert body["data"]["tracking_active"] is True

    # A second fix updates the SAME live row but adds a second ping.
    moved = {"latitude": 22.7800, "longitude": 73.6250}
    second = await client.patch("/api/me/location", headers=headers,
                                json={**moved, "speed_mps": 4.2, "location_source": "gps"})
    assert second.status_code == 200
    assert second.json()["data"]["latitude"] == pytest.approx(moved["latitude"])
    # Fields the second fix did not carry survive it.
    assert second.json()["data"]["device_id"] == "dlp-001"

    assert await db.scalar(select(func.count()).select_from(UserLiveLocation)
                           .where(UserLiveLocation.user_id == acme.member.id)) == 1
    assert await db.scalar(select(func.count()).select_from(UserLocationPing)
                           .where(UserLocationPing.user_id == acme.member.id)) == 2


async def test_telemetry_is_scoped_to_the_users_tenant_and_organization(worlds, db):
    client, acme, _ = worlds
    await client.patch("/api/me/location", headers=acme.auth(acme.member), json=GODHRA)

    live = await db.scalar(select(UserLiveLocation).where(UserLiveLocation.user_id == acme.member.id))
    assert live.tenant_id == acme.tenant.id and live.organization_id == acme.organization.id


async def test_a_fix_does_not_touch_the_users_row_beyond_the_location_flag(worlds, db):
    """The whole point of the split: GPS writes must not contend with the row
    authentication reads. `is_location_set` is the one deliberate exception."""
    client, acme, _ = worlds
    before = await db.scalar(select(User.row_version).where(User.id == acme.member.id))

    await client.patch("/api/me/location", headers=acme.auth(acme.member), json=GODHRA)
    await db.refresh(acme.member)
    assert acme.member.is_location_set is True

    # One bump for the flag, and none for the second fix.
    after_first = await db.scalar(select(User.row_version).where(User.id == acme.member.id))
    await client.patch("/api/me/location", headers=acme.auth(acme.member), json=GODHRA)
    assert await db.scalar(select(User.row_version).where(User.id == acme.member.id)) == after_first
    assert after_first == before + 1


async def test_reading_a_location_before_any_fix_is_null_not_a_404(worlds):
    client, acme, _ = worlds
    response = await client.get("/api/me/location", headers=acme.auth(acme.member))
    assert response.status_code == 200 and response.json()["data"] is None


async def test_dispatch_reads_another_users_position_but_not_another_tenants(worlds):
    client, acme, globex = worlds
    await client.patch("/api/me/location", headers=acme.auth(acme.member), json=GODHRA)

    seen = await client.get(f"/api/users/{acme.member.id}/location", headers=acme.auth(acme.admin))
    assert seen.status_code == 200
    assert seen.json()["data"]["latitude"] == pytest.approx(GODHRA["latitude"])

    # Another tenant cannot even name the user (the tenant filter makes it a 404).
    blind = await client.get(f"/api/users/{acme.member.id}/location", headers=globex.auth(globex.admin))
    assert blind.status_code == 404


# ── the primary_place_id cache ──────────────────────────────────────────────

async def _attach_home(db, world, user, *, city: str = "Godhra"):
    """The platform-wide address book is how a user gets an address — there is
    no user-specific address endpoint, by design."""
    from app.modules.geo import service as geo

    with tenant_scope(world.tenant.id, world.organization.id):
        return await geo.attach_address(db, AddressCreate(
            owner_type="user", owner_id=user.id, link_type="home", is_primary=True,
            new_place=PlaceCreate(kind="address", location_name="Home",
                                  street="12 Station Road", city=city,
                                  state="Gujarat", postal_code="389001", **GODHRA),
        ))


async def test_the_address_book_keeps_users_primary_place_id_true(worlds, db):
    _, acme, _ = worlds
    assert acme.member.primary_place_id is None

    link = await _attach_home(db, acme, acme.member)
    await db.refresh(acme.member)
    assert acme.member.primary_place_id == link.place_id

    # Detaching the only primary address clears the cache rather than stranding it.
    from app.modules.geo import service as geo

    with tenant_scope(acme.tenant.id, acme.organization.id):
        await geo.detach_address(db, str(link.uuid), reason="moved out")
    await db.refresh(acme.member)
    assert acme.member.primary_place_id is None


async def test_users_can_be_filtered_by_the_city_of_their_address(worlds, db):
    client, acme, _ = worlds
    await _attach_home(db, acme, acme.member, city="Godhra")
    await db.commit()

    hit = await client.get("/api/users", params={"city": "godhra"}, headers=acme.auth(acme.admin))
    assert hit.status_code == 200
    assert [u["id"] for u in hit.json()["data"]["items"]] == [acme.member.id]

    miss = await client.get("/api/users", params={"city": "Vadodara"}, headers=acme.auth(acme.admin))
    assert miss.json()["data"]["items"] == []


# ── organization resolution on the auth paths ───────────────────────────────

async def test_authentik_provisioning_lands_the_user_in_an_organization(db):
    """JIT provisioning runs before the request is bound to an organization, and
    `users.organization_id` is NOT NULL — so the service must resolve one."""
    sub = uuid.uuid4().hex
    user = await service.provision_from_authentik(db, {
        "sub": sub, "email": f"{sub}@authentik.local", "name": "SSO Person",
        "preferred_username": f"sso-{sub[:8]}",
    })
    assert user.organization_id is not None
    assert user.tenant_id is not None and user.user_type == "sso"


async def test_the_dev_token_user_is_organization_scoped_and_reused(db):
    first = await service.get_or_create_dev_user(db, email="dev-test@local.test")
    assert first.organization_id is not None
    second = await service.get_or_create_dev_user(db, email="dev-test@local.test")
    assert second.id == first.id          # get-or-create, never a duplicate
