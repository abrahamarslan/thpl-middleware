"""Creating a tenant bootstraps everything it needs: root organization, roles, and an administrator
who can do anything in the tenant — including creating new organizations."""

from sqlalchemy import select

from app.modules.organizations.model import Organization
from app.modules.rbac.model import UserRole
from app.modules.roles.model import Role
from app.modules.users.model import User
from tests.test_tenants_roles_api import platform_admin


async def create_tenant(client, db, acme, **extra):
    from app.modules.users.model import User as _User

    root = await db.scalar(select(_User).where(_User.email == "root@platform.example"))
    root = root or await platform_admin(db, acme)              # one platform admin per test, however many calls
    return await client.post("/api/tenants", headers=acme.auth(root), json={
        "tenant_code": "BOOT", "name": "Boot Health", "primary_contact_email": "it@boot.example", **extra})


async def test_a_new_tenant_gets_its_organization_roles_and_administrator(worlds, db):
    client, acme, _ = worlds
    response = await create_tenant(client, db, acme)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    admin = data["initial_admin"]
    assert admin["email"] == "it@boot.example" and admin["role"] == "owner" and admin["tenant_wide"] is True
    assert admin["organization_code"] == "BOOT" and admin["temporary_password"], "generated, shown once"

    org = await db.scalar(select(Organization).where(Organization.tenant_id == data["id"])
                          .execution_options(all_tenants=True))
    assert org.org_code == "BOOT" and org.parent_id is None
    roles = (await db.scalars(select(Role.code).where(Role.organization_id == org.id)
                              .execution_options(all_tenants=True))).all()
    assert set(roles) == {"owner", "admin", "member", "department_head", "team_manager", "auditor"}

    user = await db.scalar(select(User).where(User.id == admin["user_id"]).execution_options(all_tenants=True))
    assert user.organization_id == org.id and data["primary_user_id"] == user.id
    grant = await db.scalar(select(UserRole).where(UserRole.user_id == user.id).execution_options(all_tenants=True))
    assert grant.scope_type == "tenant" and grant.organization_id is None


async def test_the_new_administrator_can_sign_in_and_create_organizations(worlds, db):
    client, acme, _ = worlds
    created = (await create_tenant(client, db, acme)).json()["data"]["initial_admin"]
    login = await client.post("/api/auth/login", json={
        "identifier": created["email"], "password": created["temporary_password"]})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    mine = (await client.get("/api/auth/me/organization", headers=headers)).json()["data"]
    child = await client.post("/api/organizations", headers=headers, json={
        "org_code": "BOOT-N", "legal_name": "Boot North", "org_type": "branch", "parent": mine["uuid"]})
    assert child.status_code == 201, child.text
    # Tenant-wide: a second ROOT organization too — "anything in the tenant".
    sibling = await client.post("/api/organizations", headers=headers, json={
        "org_code": "BOOT-2", "legal_name": "Boot Second Group"})
    assert sibling.status_code == 201, sibling.text

    permissions = (await client.get("/api/me/permissions", headers=headers)).json()["data"]
    assert "rbac.owner:assign" in permissions["permissions"] and "org.organization:create" in permissions["permissions"]


async def test_the_administrator_of_one_tenant_has_no_reach_into_another(worlds, db):
    client, acme, _ = worlds
    created = (await create_tenant(client, db, acme)).json()["data"]["initial_admin"]
    login = await client.post("/api/auth/login", json={
        "identifier": created["email"], "password": created["temporary_password"]})
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    assert (await client.get(f"/api/users/{acme.member.id}", headers=headers)).status_code == 404
    assert (await client.post("/api/organizations", headers=headers, json={
        "org_code": "X", "legal_name": "X", "org_type": "branch", "parent": str(acme.organization.uuid)}
    )).status_code in (403, 404)


async def test_a_chosen_admin_email_and_password_are_used(worlds, db):
    client, acme, _ = worlds
    response = await create_tenant(client, db, acme, admin_email="boss@boot.example", admin_name="The Boss",
                                   admin_password="Str0ng!Passw0rd#x")
    admin = response.json()["data"]["initial_admin"]
    assert admin["email"] == "boss@boot.example" and admin["temporary_password"] is None
    login = await client.post("/api/auth/login", json={"identifier": "boss@boot.example",
                                                       "password": "Str0ng!Passw0rd#x"})
    assert login.status_code == 200


async def test_a_weak_password_or_a_taken_email_creates_nothing(worlds, db):
    client, acme, _ = worlds
    weak = await create_tenant(client, db, acme, admin_password="weak")
    assert weak.status_code == 422
    taken = await create_tenant(client, db, acme, admin_email=acme.admin.email)
    assert taken.status_code == 409
    assert await db.scalar(select(Organization.id).where(Organization.org_code == "BOOT")
                           .execution_options(all_tenants=True)) is None
