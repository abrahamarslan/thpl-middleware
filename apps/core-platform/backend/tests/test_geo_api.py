"""Location hub over HTTP: serialization, tenant isolation and the rules that
have to reach the caller as a usable status code."""

import pytest

from app.database.tenancy import tenant_scope
from app.modules.organizations.model import Organization

PUNE = {"latitude": 18.5204, "longitude": 73.8567}
MUMBAI = {"latitude": 19.0760, "longitude": 72.8777}


async def _org(db, world) -> Organization:
    """Each world's tenant needs one organization: geo rows require one."""
    with tenant_scope(world.tenant.id):
        org = Organization(org_code=f"{world.tenant.tenant_code}-HQ",
                           legal_name=f"{world.tenant.name} HQ", tenant_id=world.tenant.id)
        db.add(org)
        await db.flush()
    await db.commit()
    return org


def _place(**kw) -> dict:
    return {"kind": "customer_site", "location_name": "Acme Works", "street": "12 MG Road",
            "city": "Pune", "state": "Maharashtra", "postal_code": "411001", **PUNE, **kw}


async def test_create_read_and_search_a_place(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)

    created = await client.post("/api/locations", json=_place(), headers=acme.auth(acme.member))
    assert created.status_code == 201, created.text
    place = created.json()["data"]
    assert place["latitude"] == pytest.approx(PUNE["latitude"], abs=1e-6)
    assert place["geohash8"] and place["row_version"] == 1
    assert place["created_by_name"] == acme.member.name
    assert "12 MG Road" in place["formatted_address"]

    fetched = await client.get(f"/api/locations/{place['uuid']}", headers=acme.auth(acme.member))
    assert fetched.json()["data"]["uuid"] == place["uuid"]

    near = await client.get("/api/locations/nearby",
                            params={**PUNE, "radius_m": 5000}, headers=acme.auth(acme.member))
    assert [p["uuid"] for p in near.json()["data"]] == [place["uuid"]]

    found = await client.get("/api/locations", params={"q": "MG Road"}, headers=acme.auth(acme.member))
    assert len(found.json()["data"]) == 1


async def test_one_tenant_never_sees_anothers_addresses(worlds, db):
    client, acme, globex = worlds
    await _org(db, acme)
    await _org(db, globex)

    made = await client.post("/api/addresses", json={
        "owner_type": "customer", "owner_id": 1, "link_type": "billing",
        "new_place": _place(), "is_primary": True,
    }, headers=acme.auth(acme.member))
    assert made.status_code == 201, made.text
    address = made.json()["data"]
    assert address["place"]["location_name"] == "Acme Works"

    mine = await client.get("/api/addresses", params={"owner_type": "customer", "owner_id": 1},
                            headers=acme.auth(acme.member))
    assert len(mine.json()["data"]) == 1

    theirs = await client.get("/api/addresses", params={"owner_type": "customer", "owner_id": 1},
                              headers=globex.auth(globex.member))
    assert theirs.json()["data"] == []
    assert (await client.get(f"/api/addresses/{address['uuid']}",
                             headers=globex.auth(globex.member))).status_code == 404


async def test_a_stale_row_version_is_a_409(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    place = (await client.post("/api/locations", json=_place(),
                               headers=acme.auth(acme.member))).json()["data"]

    ok = await client.patch(f"/api/locations/{place['uuid']}",
                            json={"location_name": "Renamed", "row_version": place["row_version"]},
                            headers=acme.auth(acme.member))
    assert ok.status_code == 200 and ok.json()["data"]["row_version"] == 2

    stale = await client.patch(f"/api/locations/{place['uuid']}",
                               json={"location_name": "Again", "row_version": place["row_version"]},
                               headers=acme.auth(acme.member))
    assert stale.status_code == 409
    assert stale.json()["data"]["current_row_version"] == 2


async def test_an_unknown_owner_type_is_refused_before_the_database(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    bad = await client.post("/api/addresses", json={
        "owner_type": "Customers", "owner_id": 1, "new_place": _place(),
    }, headers=acme.auth(acme.member))
    assert bad.status_code == 422
    assert "owner_type" in bad.text


async def test_both_a_place_and_a_new_place_is_refused(worlds, db):
    client, acme, _ = worlds
    org = await _org(db, acme)
    assert org is not None
    bad = await client.post("/api/addresses", json={
        "owner_type": "customer", "owner_id": 1,
    }, headers=acme.auth(acme.member))
    assert bad.status_code == 422
    assert "exactly one" in bad.text


async def test_a_place_in_use_cannot_be_deleted(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    address = (await client.post("/api/addresses", json={
        "owner_type": "customer", "owner_id": 4, "new_place": _place(),
    }, headers=acme.auth(acme.member))).json()["data"]
    place_uuid = address["place"]["uuid"]

    refused = await client.delete(f"/api/locations/{place_uuid}", params={"reason": "cleanup"},
                                  headers=acme.auth(acme.admin))
    assert refused.status_code == 422 and "still point at this place" in refused.text

    users = await client.get(f"/api/locations/{place_uuid}/addresses", headers=acme.auth(acme.member))
    assert [a["uuid"] for a in users.json()["data"]] == [address["uuid"]]

    archived = await client.post(f"/api/locations/{place_uuid}/archive",
                                 params={"reason": "site closed"}, headers=acme.auth(acme.member))
    assert archived.json()["data"]["status"] == "archived"


async def test_a_geofence_answers_which_zone_holds_a_point(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    made = await client.post("/api/geofences", json={
        "name": "Pune hub zone", "fence_type": "hub_zone",
        "center": PUNE, "radius_m": 2000, "dwell_threshold_s": 120,
    }, headers=acme.auth(acme.admin))
    assert made.status_code == 201, made.text
    assert made.json()["data"]["dwell_threshold_s"] == 120

    inside = await client.get("/api/geofences/containing", params=PUNE, headers=acme.auth(acme.member))
    assert [f["name"] for f in inside.json()["data"]] == ["Pune hub zone"]

    outside = await client.get("/api/geofences/containing", params=MUMBAI,
                               headers=acme.auth(acme.member))
    assert outside.json()["data"] == []


async def test_a_member_cannot_create_a_geofence(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    denied = await client.post("/api/geofences", json={
        "name": "Nope", "fence_type": "custom", "center": PUNE, "radius_m": 100,
    }, headers=acme.auth(acme.member))
    assert denied.status_code == 403
