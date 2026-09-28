"""RBAC over the real API: scoping across an organization tree, users hardening, assignments and guardrails."""

from sqlalchemy import select

from app.core.conf import settings

from app.modules.rbac import service as rbac
from app.modules.roles.model import Role
from app.modules.users.model import User


async def role_of(db, org, code) -> Role:
    return await db.scalar(select(Role).where(Role.organization_id == org.id, Role.code == code))


# ── scoping across an organization tree ─────────────────────────────────────

async def test_a_branch_administrator_acts_inside_their_branch_only(tree_world):
    client, w = tree_world
    body = {"department_code": "OPS", "department_name": "Operations"}

    inside = await client.post("/api/departments", headers=w.auth(w.admin_a, w.branch_a), json=body)
    assert inside.status_code == 201, inside.text
    # The header names the ORGANIZATION the request acts on; a branch admin holds no grant over the sibling.
    outside = await client.post("/api/departments", headers=w.auth(w.admin_a, w.branch_b),
                                json={**body, "department_code": "OPS2"})
    assert outside.status_code == 403
    assert outside.json()["data"]["permission"] == "teams.department:create"

    # Acting on an EXISTING row is judged at the row's own organization, whatever the header says.
    dept = inside.json()["data"]
    stolen = await client.patch(f"/api/departments/{dept['uuid']}", headers=w.auth(w.admin_b, w.branch_b),
                                json={"department_name": "Hijacked", "row_version": dept["row_version"]})
    assert stolen.status_code == 403

    # The holding administrator reaches every branch beneath it.
    ok = await client.patch(f"/api/departments/{dept['uuid']}", headers=w.auth(w.holding_admin, w.holding),
                            json={"department_name": "Operations HQ", "row_version": dept["row_version"]})
    assert ok.status_code == 200 and ok.json()["data"]["department_name"] == "Operations HQ"
    other = await client.post("/api/departments", headers=w.auth(w.holding_admin, w.branch_b),
                              json={**body, "department_code": "OPS-B"})
    assert other.status_code == 201


async def test_creating_a_root_organization_needs_a_tenant_wide_grant(tree_world, db):
    client, w = tree_world
    payload = {"org_code": "NEWROOT", "legal_name": "New Root Ltd"}
    refused = await client.post("/api/organizations", headers=w.auth(w.holding_admin, w.holding), json=payload)
    assert refused.status_code == 403 and refused.json()["data"]["tenant_level"] is True

    under = await client.post("/api/organizations", headers=w.auth(w.holding_admin, w.holding),
                              json={"org_code": "NEWBRANCH", "legal_name": "New Branch", "org_type": "branch",
                                    "parent": str(w.holding.uuid)})
    assert under.status_code == 201, under.text

    await rbac.ensure_tenant_owner(db, w.holding_admin, await role_of(db, w.holding, "owner"))
    await db.commit()
    allowed = await client.post("/api/organizations", headers=w.auth(w.holding_admin, w.holding), json=payload)
    assert allowed.status_code == 201, allowed.text


async def test_a_branch_admin_cannot_create_beneath_a_sibling_branch(tree_world):
    client, w = tree_world
    response = await client.post(
        "/api/organizations", headers=w.auth(w.admin_a, w.branch_a),
        json={"org_code": "SNEAKY", "legal_name": "Sneaky", "org_type": "branch", "parent": str(w.branch_b.uuid)},
    )
    assert response.status_code == 403        # judged at the PARENT named in the body, not at the header


# ── the users API is no longer open ─────────────────────────────────────────

async def test_a_member_cannot_change_or_remove_other_users(tree_world):
    client, w = tree_world
    headers = w.auth(w.member_a, w.branch_a)
    assert (await client.put(f"/api/users/{w.admin_a.id}", headers=headers, json={"name": "Owned"})).status_code == 403
    assert (await client.delete(f"/api/users/{w.admin_a.id}", headers=headers)).status_code == 403
    assert (await client.post(f"/api/users/{w.admin_a.id}/ban", headers=headers,
                              json={"reason": "because"})).status_code == 403
    assert (await client.post("/api/users", headers=headers, json={
        "name": "X", "email": "x@tree.example", "password": "Abcdefg1!xyz"})).status_code == 403


async def test_a_member_sees_the_directory_not_the_record(tree_world):
    client, w = tree_world
    listed = await client.get("/api/users", headers=w.auth(w.member_a, w.branch_a))
    assert listed.status_code == 200
    items = listed.json()["data"]["items"]
    assert items and all({"id", "name"} <= item.keys() for item in items)
    for sensitive in ("medical_history", "pan", "bank_details", "payment_details", "email", "phone"):
        assert all(sensitive not in item for item in items), sensitive

    peer = await client.get(f"/api/users/{w.admin_a.id}", headers=w.auth(w.member_a, w.branch_a))
    assert "medical_history" not in peer.json()["data"]
    mine = await client.get(f"/api/users/{w.member_a.id}", headers=w.auth(w.member_a, w.branch_a))
    assert "medical_history" in mine.json()["data"], "your own record is yours"


async def test_an_administrator_sees_and_edits_the_full_record(tree_world):
    client, w = tree_world
    headers = w.auth(w.admin_a, w.branch_a)
    full = await client.get(f"/api/users/{w.member_a.id}", headers=headers)
    assert full.status_code == 200 and "medical_history" in full.json()["data"]
    edited = await client.put(f"/api/users/{w.member_a.id}", headers=headers, json={"department": "Ops"})
    assert edited.status_code == 200, edited.text


async def test_an_administrator_cannot_touch_another_branchs_user(tree_world):
    client, w = tree_world
    response = await client.put(f"/api/users/{w.admin_b.id}", headers=w.auth(w.admin_a, w.branch_a),
                                json={"department": "Sneaky"})
    assert response.status_code == 403


async def test_a_role_cannot_be_set_through_the_generic_user_update(tree_world):
    client, w = tree_world
    admin_role = await client.get("/api/roles/admin", headers=w.auth(w.admin_a, w.branch_a))
    response = await client.put(f"/api/users/{w.member_a.id}", headers=w.auth(w.admin_a, w.branch_a),
                                json={"role_id": admin_role.json()["data"]["id"]})
    assert response.status_code == 422 and "base-role" in response.text


async def test_nobody_deletes_or_bans_themselves(tree_world):
    client, w = tree_world
    headers = w.auth(w.admin_a, w.branch_a)
    assert (await client.delete(f"/api/users/{w.admin_a.id}", headers=headers)).status_code == 403
    assert (await client.post(f"/api/users/{w.admin_a.id}/ban", headers=headers,
                              json={"reason": "oops"})).status_code == 403


async def test_users_of_another_tenant_are_invisible(worlds):
    client, acme, globex = worlds
    response = await client.get(f"/api/users/{globex.member.id}", headers=acme.auth(acme.admin))
    assert response.status_code == 404


# ── assignments and their guardrails ────────────────────────────────────────

async def test_an_administrator_grants_a_contextual_role_within_their_reach(tree_world, db):
    client, w = tree_world
    manager = await role_of(db, w.branch_a, "team_manager")
    granted = await client.post(
        f"/api/users/{w.member_a.id}/roles", headers=w.auth(w.admin_a, w.branch_a),
        json={"role": str(manager.id), "scope_type": "organization", "organization": w.branch_a.org_code},
    )
    assert granted.status_code == 201, granted.text
    assert granted.json()["data"]["role_code"] == "team_manager"

    again = await client.post(
        f"/api/users/{w.member_a.id}/roles", headers=w.auth(w.admin_a, w.branch_a),
        json={"role": str(manager.id), "scope_type": "organization", "organization": w.branch_a.org_code},
    )
    assert again.status_code == 409

    listed = await client.get(f"/api/users/{w.member_a.id}/roles", headers=w.auth(w.admin_a, w.branch_a))
    assert [r["role_code"] for r in listed.json()["data"]] == ["team_manager"]

    revoked = await client.delete(
        f"/api/users/{w.member_a.id}/roles/{granted.json()['data']['uuid']}", params={"reason": "no longer needed"},
        headers=w.auth(w.admin_a, w.branch_a))
    assert revoked.status_code == 200
    assert (await client.get(f"/api/users/{w.member_a.id}/roles",
                             headers=w.auth(w.admin_a, w.branch_a))).json()["data"] == []


async def test_a_grant_can_be_time_boxed_and_an_expired_one_grants_nothing(tree_world, db):
    client, w = tree_world
    manager = await role_of(db, w.branch_a, "team_manager")
    granted = await client.post(
        f"/api/users/{w.member_a.id}/roles", headers=w.auth(w.admin_a, w.branch_a),
        json={"role": str(manager.id), "scope_type": "organization", "organization": w.branch_a.org_code,
              "valid_from": "2020-01-01T00:00:00Z", "valid_to": "2020-02-01T00:00:00Z"},
    )
    assert granted.status_code == 201, granted.text
    mine = await client.get("/api/me/permissions", headers=w.auth(w.member_a, w.branch_a))
    assert "teams.team:update" not in mine.json()["data"]["permissions"]


async def test_you_cannot_grant_beyond_your_own_reach(tree_world, db):
    client, w = tree_world
    manager_b = await role_of(db, w.branch_b, "team_manager")
    # Another branch: no authority there (and the role is owned by that branch anyway).
    other = await client.post(
        f"/api/users/{w.member_a.id}/roles", headers=w.auth(w.admin_a, w.branch_a),
        json={"role": str(manager_b.id), "scope_type": "organization", "organization": w.branch_b.org_code},
    )
    assert other.status_code == 403

    # `owner` is the owner-only permission: an administrator cannot mint owners.
    owner = await role_of(db, w.branch_a, "owner")
    escalate = await client.post(
        f"/api/users/{w.member_a.id}/roles", headers=w.auth(w.admin_a, w.branch_a),
        json={"role": str(owner.id), "scope_type": "organization", "organization": w.branch_a.org_code},
    )
    assert escalate.status_code == 403


async def test_you_cannot_change_your_own_roles(tree_world, db):
    client, w = tree_world
    manager = await role_of(db, w.branch_a, "team_manager")
    response = await client.post(
        f"/api/users/{w.admin_a.id}/roles", headers=w.auth(w.admin_a, w.branch_a),
        json={"role": str(manager.id), "scope_type": "organization", "organization": w.branch_a.org_code},
    )
    assert response.status_code == 422 and response.json()["code"] == "rbac_rule_violation"


async def test_a_role_can_only_be_used_inside_its_owners_subtree(tree_world, db):
    client, w = tree_world
    # branch A's manager role, granted at branch B: outside the role's own organization.
    manager_a = await role_of(db, w.branch_a, "team_manager")
    response = await client.post(
        f"/api/users/{w.member_a.id}/roles", headers=w.auth(w.holding_admin, w.holding),
        json={"role": str(manager_a.id), "scope_type": "organization", "organization": w.branch_b.org_code},
    )
    assert response.status_code == 422 and "subtree" in response.json()["msg"]
    # A role defined at the holding may be used in a branch beneath it.
    manager_h = await role_of(db, w.holding, "team_manager")
    inside = await client.post(
        f"/api/users/{w.member_a.id}/roles", headers=w.auth(w.holding_admin, w.holding),
        json={"role": str(manager_h.id), "scope_type": "organization", "organization": w.branch_b.org_code},
    )
    assert inside.status_code == 201, inside.text


async def test_a_tenant_wide_grant_needs_a_role_owned_by_a_root_organization(tree_world, db):
    client, w = tree_world
    manager_a = await role_of(db, w.branch_a, "team_manager")
    refused = await client.post(
        f"/api/users/{w.member_a.id}/roles", headers=w.auth(w.holding_admin, w.holding),
        json={"role": str(manager_a.id), "scope_type": "tenant"},
    )
    assert refused.status_code == 422 and "root organization" in refused.json()["msg"]


async def test_the_last_active_owner_cannot_be_demoted_deleted_or_banned(tree_world, db):
    client, w = tree_world
    owner_role = await role_of(db, w.branch_a, "owner")
    member_role = await role_of(db, w.branch_a, "member")
    sole_owner = User(name="Sole Owner", email="sole.owner@tree.example", password="x",
                      role_id=owner_role.id, organization_id=w.branch_a.id, tenant_id=w.tenant.id)
    db.add(sole_owner)
    await db.commit()

    headers = w.auth(w.holding_admin, w.holding)
    demote = await client.put(f"/api/users/{sole_owner.id}/base-role", headers=headers,
                              json={"role": str(member_role.id)})
    assert demote.status_code == 422 and "last active owner" in demote.json()["msg"]
    assert (await client.delete(f"/api/users/{sole_owner.id}", headers=headers)).status_code == 422
    assert (await client.post(f"/api/users/{sole_owner.id}/ban", headers=headers,
                              json={"reason": "test"})).status_code == 422


async def test_a_base_role_must_belong_to_the_users_own_organization(tree_world, db):
    client, w = tree_world
    other_branch_member = await role_of(db, w.branch_b, "member")
    response = await client.put(f"/api/users/{w.member_a.id}/base-role", headers=w.auth(w.holding_admin, w.holding),
                                json={"role": str(other_branch_member.id)})
    assert response.status_code == 422 and "own organization" in response.json()["msg"]


async def test_the_role_permission_editor_refuses_typos_and_system_roles(tree_world, db):
    client, w = tree_world
    headers = w.auth(w.admin_a, w.branch_a)
    created = await client.post("/api/roles", headers=headers, json={"code": "planner", "name": "Planner"})
    assert created.status_code == 201
    role = created.json()["data"]

    typo = await client.put(f"/api/roles/{role['id']}/permissions", headers=headers,
                            json={"permissions": ["teams.team:raed"], "row_version": role["row_version"]})
    assert typo.status_code == 422 and "teams.team:raed" in typo.text

    ok = await client.put(f"/api/roles/{role['id']}/permissions", headers=headers,
                          json={"permissions": ["teams.team:read", "teams.team:manage"],
                                "row_version": role["row_version"]})
    assert ok.status_code == 200, ok.text
    assert set(ok.json()["data"]["permissions"]) == {
        "teams.team:read", "teams.team:manage", "teams.team:create", "teams.team:update", "teams.team:delete"}

    system = await role_of(db, w.branch_a, "member")
    refused = await client.put(f"/api/roles/{system.id}/permissions", headers=headers,
                               json={"permissions": [], "row_version": system.row_version})
    assert refused.status_code == 422 and "system role" in refused.json()["msg"]

    cloned = await client.post(f"/api/roles/{system.id}/clone", headers=headers, json={"code": "member_plus"})
    assert cloned.status_code == 201 and cloned.json()["data"]["is_system"] is False


async def test_you_cannot_hand_out_a_permission_you_lack(tree_world, db):
    client, w = tree_world
    manager = await role_of(db, w.branch_a, "team_manager")
    # A team manager holds `teams.team:update` but not `rbac.role:manage`; they can hold roles-edit rights only if given.
    await client.post(f"/api/users/{w.member_a.id}/roles", headers=w.auth(w.admin_a, w.branch_a),
                      json={"role": str(manager.id), "scope_type": "organization",
                            "organization": w.branch_a.org_code})
    # ... and even with that role the member has no `rbac.role:create`, so cannot mint a role at all.
    refused = await client.post("/api/roles", headers=w.auth(w.member_a, w.branch_a),
                                json={"code": "mint", "name": "Mint", "permissions": ["rbac.role:manage"]})
    assert refused.status_code == 403


async def test_my_permissions_lists_what_i_hold(tree_world):
    client, w = tree_world
    mine = (await client.get("/api/me/permissions", headers=w.auth(w.member_a, w.branch_a))).json()["data"]
    assert "teams.team:read" in mine["permissions"] and "teams.team:create" not in mine["permissions"]
    assert [g["source"] for g in mine["grants"]] == ["base"]
    admin = (await client.get("/api/me/permissions", headers=w.auth(w.admin_a, w.branch_a))).json()["data"]
    assert "org.organization:create" in admin["permissions"] and "rbac.owner:assign" not in admin["permissions"]


async def test_the_permission_catalogue_is_readable_by_those_who_manage_roles(tree_world):
    client, w = tree_world
    assert (await client.get("/api/permissions", headers=w.auth(w.member_a, w.branch_a))).status_code == 403
    groups = (await client.get("/api/permissions", headers=w.auth(w.admin_a, w.branch_a))).json()["data"]
    assert {"users", "rbac", "teams", "geo"} <= {g["module"] for g in groups}


# ── everyone starts as a member ─────────────────────────────────────────────

async def test_self_registration_gives_the_member_role(db, redis_available):
    """A role-less user would hold no grants once permissions are enforced."""
    import httpx

    from app.database.db import get_db
    from app.main import app
    from app.modules.roles.service import seed_system_roles
    from app.modules.tenants.model import Tenant

    async def _db():
        yield db

    default = await db.scalar(select(Tenant).where(Tenant.tenant_code == settings.DEFAULT_TENANT_CODE))
    app.dependency_overrides[get_db] = _db
    try:
        from app.database.tenancy import tenant_scope
        from app.modules.organizations.model import Organization

        org = await db.scalar(select(Organization).where(
            Organization.tenant_id == default.id, Organization.org_code == (settings.DEFAULT_ORGANIZATION_CODE or "DEFAULT-HQ")
        ).execution_options(all_tenants=True))
        with tenant_scope(default.id):
            await seed_system_roles(db, org.id)
        await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/auth/register", json={
                "name": "New Person", "email": "new.person@example.com", "password": "Str0ng!Passw0rd#x"})
        assert response.status_code == 201, response.text
        user = await db.scalar(select(User).where(User.email == "new.person@example.com").execution_options(all_tenants=True))
        role = await db.scalar(select(Role).where(Role.id == user.role_id).execution_options(all_tenants=True))
        assert role.code == "member"
    finally:
        app.dependency_overrides.clear()


async def test_sso_users_get_the_same_default_role_up_front(db):
    """Authentik JIT users must not arrive role-less: they would be locked out of every gated endpoint on day one."""
    from app.database.tenancy import tenant_scope
    from app.modules.organizations.model import Organization
    from app.modules.roles.service import seed_system_roles
    from app.modules.tenants.model import Tenant
    from app.modules.users import service as users_service

    default = await db.scalar(select(Tenant).where(Tenant.tenant_code == settings.DEFAULT_TENANT_CODE))
    org = await db.scalar(select(Organization).where(
        Organization.tenant_id == default.id, Organization.org_code == (settings.DEFAULT_ORGANIZATION_CODE or "DEFAULT-HQ")
    ).execution_options(all_tenants=True))
    with tenant_scope(default.id):
        await seed_system_roles(db, org.id)
    await db.commit()

    user = await users_service.provision_from_authentik(db, {
        "sub": "ak-sub-1", "email": "sso.person@example.com", "name": "SSO Person", "email_verified": True})
    await db.commit()
    role = await db.scalar(select(Role).where(Role.id == user.role_id).execution_options(all_tenants=True))
    assert role is not None and role.code == "member"


async def test_users_created_by_an_administrator_start_as_members(tree_world, db):
    client, w = tree_world
    created = await client.post("/api/users", headers=w.auth(w.admin_a, w.branch_a), json={
        "name": "Fresh Hire", "email": "fresh.hire@tree.example", "password": "Str0ng!Passw0rd#x"})
    assert created.status_code == 201, created.text
    user = await db.scalar(select(User).where(User.email == "fresh.hire@tree.example"))
    role = await db.scalar(select(Role).where(Role.id == user.role_id))
    assert role.code == "member" and role.organization_id == user.organization_id

    with_role = await client.post("/api/users", headers=w.auth(w.admin_a, w.branch_a), json={
        "name": "Sneaky", "email": "sneaky@tree.example", "password": "Str0ng!Passw0rd#x", "role_id": role.id})
    assert with_role.status_code == 422


