"""Organizations: the tenant's tree over the real API (real JWTs, real tenant binding)."""

import pytest

# `worlds` (ACME + GLOBEX with real users/JWTs) comes from tests/tenancy_fixtures.py via conftest.


async def create(client, world, **body):
    response = await client.post("/api/organizations", json=body, headers=world.auth(world.admin))
    return response


async def node(client, world, **body) -> dict:
    response = await create(client, world, **body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_building_a_tree_and_reading_it_back(worlds):
    client, acme, _ = worlds
    holding = await node(client, acme, org_code="ACME-H", legal_name="Acme Holdings", org_type="holding")
    entity = await node(client, acme, org_code="ACME-IN", legal_name="Acme India Pvt Ltd", org_type="legal_entity",
                        parent=holding["uuid"], fiscal_year_start_month="april", tax_id="24AAACA1234A1Z5")
    branch = await node(client, acme, org_code="ACME-AMD", legal_name="Acme Ahmedabad", org_type="branch",
                        parent=entity["uuid"])
    await node(client, acme, org_code="ACME-AMD-2", legal_name="Acme Ahmedabad East", org_type="branch",
               parent=branch["uuid"])

    assert entity["depth"] == 1 and entity["fiscal_year_start_month"] == 3        # "april" accepted
    assert entity["hierarchy_path"] == f"/{holding['uuid']}/{entity['uuid']}/"
    assert entity["parent_uuid"] == holding["uuid"] and entity["created_by_name"] == "ACME Admin"

    tree = (await client.get("/api/organizations/tree", headers=acme.auth(acme.member))).json()["data"]
    assert [n["org_code"] for n in tree] == ["ACME-H"]
    assert tree[0]["children"][0]["children"][0]["children"][0]["org_code"] == "ACME-AMD-2"

    ancestors = (await client.get(f"/api/organizations/{branch['uuid']}/ancestors",
                                  headers=acme.auth(acme.member))).json()["data"]
    assert [a["org_code"] for a in ancestors] == ["ACME-H", "ACME-IN"]


@pytest.mark.parametrize(("body", "why"), [
    ({"org_code": "B", "legal_name": "Rootless branch", "org_type": "branch"}, "cannot be placed under the root"),
    ({"org_code": "S", "legal_name": "Solo child", "org_type": "solo", "parent": "PARENT"}, "cannot be placed under"),
])
async def test_placement_rules(worlds, body, why):
    client, acme, _ = worlds
    parent = await node(client, acme, org_code="P", legal_name="Parent", org_type="holding")
    body = {**body, **({"parent": parent["uuid"]} if body.get("parent") else {})}
    response = await create(client, acme, **body)
    assert response.status_code == 422 and why in response.json()["msg"]


async def test_codes_are_unique_per_tenant_not_globally(worlds):
    client, acme, globex = worlds
    await node(client, acme, org_code="HQ", legal_name="Acme HQ")
    assert (await create(client, acme, org_code="hq", legal_name="Again")).status_code == 409
    await node(client, globex, org_code="HQ", legal_name="Globex HQ")                # other tenant: fine


async def test_moving_a_subtree_rewrites_paths_and_refuses_cycles(worlds):
    client, acme, _ = worlds
    h1 = await node(client, acme, org_code="H1", legal_name="H1", org_type="holding")
    h2 = await node(client, acme, org_code="H2", legal_name="H2", org_type="holding")
    ent = await node(client, acme, org_code="E", legal_name="E", parent=h1["uuid"])
    br = await node(client, acme, org_code="B", legal_name="B", org_type="branch", parent=ent["uuid"])

    moved = await client.post(f"/api/organizations/{ent['uuid']}/move", headers=acme.auth(acme.admin),
                              json={"parent": h2["uuid"], "row_version": ent["row_version"]})
    assert moved.status_code == 200, moved.text
    branch = (await client.get(f"/api/organizations/{br['uuid']}", headers=acme.auth(acme.member))).json()["data"]
    assert branch["hierarchy_path"] == f"/{h2['uuid']}/{ent['uuid']}/{br['uuid']}/" and branch["depth"] == 2

    cycle = await client.post(f"/api/organizations/{h2['uuid']}/move", headers=acme.auth(acme.admin),
                              json={"parent": br["uuid"], "row_version": 1})
    assert cycle.status_code == 422


async def test_status_lifecycle_and_deactivation_fields(worlds):
    client, acme, _ = worlds
    ent = await node(client, acme, org_code="E", legal_name="E")
    br = await node(client, acme, org_code="B", legal_name="B", org_type="branch", parent=ent["uuid"])
    admin = acme.auth(acme.admin)

    blocked = await client.post(f"/api/organizations/{ent['uuid']}/status", headers=admin,
                                json={"status": "archived", "reason": "closing"})
    assert blocked.status_code == 422 and "child" in blocked.json()["msg"]
    no_reason = await client.post(f"/api/organizations/{br['uuid']}/status", headers=admin, json={"status": "suspended"})
    assert no_reason.status_code == 422

    suspended = (await client.post(f"/api/organizations/{br['uuid']}/status", headers=admin,
                                   json={"status": "suspended", "reason": "audit"})).json()["data"]
    assert suspended["deactivation_reason"] == "audit" and suspended["deactivation_date"]
    active = (await client.post(f"/api/organizations/{br['uuid']}/status", headers=admin,
                                json={"status": "active"})).json()["data"]
    assert active["deactivation_date"] is None


async def test_delete_only_leaves_with_a_reason(worlds):
    client, acme, _ = worlds
    ent = await node(client, acme, org_code="E", legal_name="E")
    br = await node(client, acme, org_code="B", legal_name="B", org_type="branch", parent=ent["uuid"])
    admin = acme.auth(acme.admin)
    assert (await client.delete(f"/api/organizations/{ent['uuid']}", params={"reason": "gone"},
                                headers=admin)).status_code == 422
    assert (await client.delete(f"/api/organizations/{br['uuid']}", params={"reason": "closed"},
                                headers=admin)).status_code == 200
    assert (await client.get(f"/api/organizations/{br['uuid']}", headers=admin)).status_code == 404


async def test_optimistic_lock_on_update(worlds):
    client, acme, _ = worlds
    ent = await node(client, acme, org_code="E", legal_name="E")
    admin = acme.auth(acme.admin)
    first = await client.patch(f"/api/organizations/{ent['uuid']}", headers=admin,
                               json={"trading_name": "Acme", "row_version": 1})
    assert first.status_code == 200 and first.json()["data"]["row_version"] == 2
    stale = await client.patch(f"/api/organizations/{ent['uuid']}", headers=admin,
                               json={"trading_name": "Stale", "row_version": 1})
    assert stale.status_code == 409 and stale.json()["data"]["current_row_version"] == 2


async def test_zoho_owned_fields_are_read_only_on_zoho_linked_nodes(worlds, db):
    from sqlalchemy import update

    from app.modules.organizations.model import Organization

    client, acme, _ = worlds
    ent = await node(client, acme, org_code="ZOHO-1", legal_name="Zoho Org")
    await db.execute(update(Organization).where(Organization.org_code == "ZOHO-1")
                     .values(zoho_id="600155", row_version=Organization.row_version)
                     .execution_options(all_tenants=True))
    await db.commit()
    admin = acme.auth(acme.admin)
    refused = await client.patch(f"/api/organizations/{ent['uuid']}", headers=admin,
                                 json={"name": "Renamed", "row_version": 1})
    assert refused.status_code == 422 and refused.json()["data"]["zoho_owned"] == ["name"]
    allowed = await client.patch(f"/api/organizations/{ent['uuid']}", headers=admin,
                                 json={"trading_name": "Tarrina", "row_version": 1})
    assert allowed.status_code == 200


async def test_tenants_are_isolated(worlds):
    client, acme, globex = worlds
    acme_org = await node(client, acme, org_code="SECRET", legal_name="Acme Secret")
    seen = (await client.get("/api/organizations", headers=globex.auth(globex.member))).json()["data"]
    assert seen == []
    assert (await client.get(f"/api/organizations/{acme_org['uuid']}",
                             headers=globex.auth(globex.member))).status_code == 404
    header = globex.auth(globex.member, **{"X-Organization-Id": acme_org["uuid"]})
    assert (await client.get("/api/organizations", headers=header)).status_code == 403


async def test_members_read_admins_write(worlds):
    client, acme, _ = worlds
    response = await client.post("/api/organizations", headers=acme.auth(acme.member),
                                 json={"org_code": "X", "legal_name": "X"})
    assert response.status_code == 403


async def test_a_suspended_tenant_is_locked_out(worlds, db):
    from app.modules.tenants import service as tenants

    client, acme, _ = worlds
    acme.tenant.status = "suspended"
    await db.commit()
    tenants._forget_status(acme.tenant.id)
    response = await client.get("/api/organizations", headers=acme.auth(acme.member))
    assert response.status_code == 403 and "suspended" in response.json()["msg"]
