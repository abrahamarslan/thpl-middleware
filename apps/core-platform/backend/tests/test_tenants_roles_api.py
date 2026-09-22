"""Tenants (platform admin) and roles (tenant admin) over the real API."""

import pytest
from sqlalchemy import select

from app.modules.organizations.model import Organization
from app.modules.users.model import User


async def platform_admin(db, acme) -> User:
    """A platform admin is still a user of some organization.

    Platform-admin rights come from ``PLATFORM_ADMIN_EMAILS``, not from where
    the row lives, but ``users.organization_id`` is NOT NULL — so the root user
    sits in the world's own HQ like everyone else.
    """
    root = User(name="Platform Root", email="root@platform.example", password="x",
                tenant_id=acme.tenant.id, organization_id=acme.organization.id)
    db.add(root)
    await db.commit()
    return root


async def test_platform_admin_creates_a_tenant_with_its_root_organization(worlds, db):
    client, acme, _ = worlds
    root = await platform_admin(db, acme)
    # Never the deployment's own code: the migration seeds DEFAULT_TENANT_CODE
    # (`.env`, THPL here), so reusing it is a 409 from the fixture, not a bug.
    response = await client.post("/api/tenants", headers=acme.auth(root), json={
        "tenant_code": "NEWCO", "name": "Newco Health", "primary_contact_email": "it@newco.example",
        "root_organization_name": "Newco Health Private Limited",
    })
    assert response.status_code == 201, response.text
    tenant = response.json()["data"]
    assert tenant["status"] == "trial" and tenant["row_version"] == 1

    org = await db.scalar(select(Organization).where(Organization.tenant_id == tenant["id"])
                          .execution_options(all_tenants=True))
    assert org.org_code == "NEWCO" and org.parent_id is None and org.org_type == "legal_entity"

    dup = await client.post("/api/tenants", headers=acme.auth(root), json={
        "tenant_code": "NEWCO", "name": "x", "primary_contact_email": "x@x.example"})
    assert dup.status_code == 409


async def test_only_platform_admins_manage_tenants(worlds):
    client, acme, _ = worlds
    assert (await client.get("/api/tenants", headers=acme.auth(acme.admin))).status_code == 403
    current = await client.get("/api/tenants/current", headers=acme.auth(acme.member))
    assert current.status_code == 200 and current.json()["data"]["tenant_code"] == "ACME"


async def test_tenant_status_change_and_optimistic_update(worlds, db):
    client, acme, globex = worlds
    root = await platform_admin(db, acme)
    changed = await client.post(f"/api/tenants/{globex.tenant.tenant_code}/status", headers=acme.auth(root),
                                json={"status": "suspended", "reason": "unpaid invoice"})
    assert changed.status_code == 200 and changed.json()["data"]["status"] == "suspended"
    assert (await client.get("/api/organizations", headers=globex.auth(globex.member))).status_code == 403

    stale = await client.patch(f"/api/tenants/{acme.tenant.id}", headers=acme.auth(root),
                               json={"name": "Acme Renamed", "row_version": 99})
    assert stale.status_code == 409


async def test_roles_live_inside_their_tenant(worlds):
    client, acme, globex = worlds
    listed = (await client.get("/api/roles", headers=acme.auth(acme.member))).json()["data"]
    assert {r["code"] for r in listed} == {"owner", "admin", "member"}
    assert {r["tenant_id"] for r in listed} == {acme.tenant.id}

    created = await client.post("/api/roles", headers=acme.auth(acme.admin),
                                json={"code": "sales_rep", "name": "Sales rep", "permissions": ["orders.read"]})
    assert created.status_code == 201
    assert "sales_rep" not in {r["code"] for r in
                               (await client.get("/api/roles", headers=globex.auth(globex.member))).json()["data"]}
    # the same code in another tenant is fine
    assert (await client.post("/api/roles", headers=globex.auth(globex.admin),
                              json={"code": "sales_rep", "name": "Sales"})).status_code == 201


@pytest.mark.parametrize(("ref", "why"), [("admin", "system role"), ("member", "system role")])
async def test_system_roles_cannot_be_deleted(worlds, ref, why):
    client, acme, _ = worlds
    response = await client.delete(f"/api/roles/{ref}", params={"reason": "cleanup"}, headers=acme.auth(acme.admin))
    assert response.status_code == 422 and why in response.json()["msg"]


async def test_a_role_in_use_cannot_be_deleted(worlds, db):
    client, acme, _ = worlds
    role = (await client.post("/api/roles", headers=acme.auth(acme.admin),
                              json={"code": "picker", "name": "Picker"})).json()["data"]
    acme.member.role_id = role["id"]
    await db.commit()
    response = await client.delete("/api/roles/picker", params={"reason": "cleanup"}, headers=acme.auth(acme.admin))
    assert response.status_code == 422 and "still hold" in response.json()["msg"]


async def test_a_user_cannot_hold_another_organizations_role(worlds, db):
    """Roles are organization-scoped, so the FK is three columns wide:
    ``(tenant_id, organization_id, role_id)`` → ``roles``. Another tenant's role
    fails on it, and so would another organization's role of the same tenant."""
    from sqlalchemy.exc import IntegrityError

    from app.modules.roles.model import Role

    _, acme, globex = worlds
    globex_admin_role = await db.scalar(select(Role).where(Role.tenant_id == globex.tenant.id, Role.code == "admin")
                                        .execution_options(all_tenants=True))
    acme.member.role_id = globex_admin_role.id
    with pytest.raises(IntegrityError, match="fk_users_tenant_org_role"):
        await db.commit()
    await db.rollback()
