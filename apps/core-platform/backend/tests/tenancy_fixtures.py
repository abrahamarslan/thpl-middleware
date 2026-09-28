"""Shared fixtures for tenancy API tests: two tenants with real users and JWTs.

Every user is organization-scoped, so each world gets an organization and its
system roles are seeded per organization (roles are org-scoped now).
"""

import uuid
from dataclasses import dataclass

import httpx
import pytest

from app.common.security.jwt import create_access_token
from app.database.tenancy import tenant_scope
from app.main import app
from app.modules.organizations.model import Organization
from app.modules.roles.service import seed_system_roles
from app.modules.tenants.model import Tenant
from app.modules.users.model import User


@dataclass
class TenantWorld:
    tenant: Tenant
    organization: Organization
    admin: User
    member: User

    def auth(self, user: User, **headers: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}", **headers}


async def build_world(db, code: str) -> TenantWorld:
    tenant = Tenant(tenant_code=code, name=f"{code} Ltd", primary_contact_email=f"ops@{code.lower()}.example",
                    status="active")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        org = Organization(
            tenant_id=tenant.id, org_code=f"{code}-HQ", legal_name=f"{code} HQ",
            org_type="solo", uuid=uuid.uuid4(),
        )
        db.add(org)
        await db.flush()
        roles = {r.code: r for r in await seed_system_roles(db, org.id)}
        admin = User(name=f"{code} Admin", email=f"admin@{code.lower()}.example", password="x",
                     role_id=roles["admin"].id, organization_id=org.id)
        member = User(name=f"{code} Member", email=f"member@{code.lower()}.example", password="x",
                      role_id=roles["member"].id, organization_id=org.id)
        db.add_all([admin, member])
        await db.flush()
        # `org` is `solo` (root, no children — the world has exactly one organization), so its `admin` is
        # this tenant's administrator in every sense a test could mean: give them the tenant-wide grant a
        # real tenant's bootstrap admin holds (docs/rbac-module.md §12), so "acme.admin" can do anything in
        # the tenant — including creating further organizations — the way the pre-RBAC TenantAdmin check
        # (role code admin/owner, no scoping) always let a world's admin do.
        from app.modules.rbac import service as rbac_service

        await rbac_service.ensure_tenant_owner(db, admin, roles["owner"])
    await db.commit()
    return TenantWorld(tenant, org, admin, member)


@pytest.fixture
async def worlds(db, redis_available, monkeypatch):
    """ACME and GLOBEX, each with an admin and a member; an API client on the test's session."""
    from app.core.conf import settings
    from app.database.db import get_db

    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "root@platform.example")
    acme, globex = await build_world(db, "ACME"), await build_world(db, "GLOBEX")

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, acme, globex
    app.dependency_overrides.clear()


# ── a real organization TREE ────────────────────────────────────────────────

@dataclass
class TreeWorld:
    """One tenant: holding ─┬─ branch A
                             └─ branch B     — with an administrator at each level and a plain member in A.

    ``worlds`` builds one FLAT organization per tenant, which cannot express "a branch administrator cannot
    act on a sibling branch" or "the holding administrator reaches both".
    """

    tenant: Tenant
    holding: Organization
    branch_a: Organization
    branch_b: Organization
    holding_admin: User
    admin_a: User
    admin_b: User
    member_a: User

    def auth(self, user: User, org: Organization | None = None, **headers: str) -> dict[str, str]:
        extra = {"X-Organization-Code": org.org_code} if org is not None else {}
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}", **extra, **headers}


async def build_tree_world(db, code: str = "TREE") -> TreeWorld:
    from sqlalchemy import select

    from app.modules.organizations import service as org_service
    from app.modules.organizations.schema import OrganizationCreate
    from app.modules.roles.model import Role
    from app.modules.tenants.enums import OrganizationType

    tenant = Tenant(tenant_code=code, name=f"{code} Ltd", primary_contact_email=f"ops@{code.lower()}.example",
                    status="active")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        holding = await org_service.create_organization(db, OrganizationCreate(
            org_code=f"{code}-H", legal_name=f"{code} Holding", org_type=OrganizationType.HOLDING), actor_id=None)
        branch_a = await org_service.create_organization(db, OrganizationCreate(
            org_code=f"{code}-A", legal_name=f"{code} Branch A", org_type=OrganizationType.BRANCH,
            parent=holding.uuid), actor_id=None)
        branch_b = await org_service.create_organization(db, OrganizationCreate(
            org_code=f"{code}-B", legal_name=f"{code} Branch B", org_type=OrganizationType.BRANCH,
            parent=holding.uuid), actor_id=None)

        async def role(org: Organization, role_code: str) -> Role:
            return await db.scalar(select(Role).where(Role.organization_id == org.id, Role.code == role_code))

        def user(name: str, org: Organization, r: Role) -> User:
            return User(name=f"{code} {name}", email=f"{name.lower().replace(' ', '.')}@{code.lower()}.example",
                        password="x", role_id=r.id, organization_id=org.id)

        holding_admin = user("Holding Admin", holding, await role(holding, "admin"))
        admin_a = user("Admin A", branch_a, await role(branch_a, "admin"))
        admin_b = user("Admin B", branch_b, await role(branch_b, "admin"))
        member_a = user("Member A", branch_a, await role(branch_a, "member"))
        db.add_all([holding_admin, admin_a, admin_b, member_a])
        await db.flush()
    await db.commit()
    return TreeWorld(tenant, holding, branch_a, branch_b, holding_admin, admin_a, admin_b, member_a)


@pytest.fixture
async def tree_world(db, redis_available, monkeypatch):
    """A tenant with an organization tree, plus an API client on the test's session."""
    from app.core.conf import settings
    from app.database.db import get_db

    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "root@platform.example")
    world = await build_tree_world(db)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, world
    app.dependency_overrides.clear()
