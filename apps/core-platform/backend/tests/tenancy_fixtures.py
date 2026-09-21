"""Shared fixtures for tenancy API tests: two tenants with real users and JWTs."""

from dataclasses import dataclass

import httpx
import pytest

from app.common.security.jwt import create_access_token
from app.database.tenancy import tenant_scope
from app.main import app
from app.modules.roles.service import seed_system_roles
from app.modules.tenants.model import Tenant
from app.modules.users.model import User


@dataclass
class TenantWorld:
    tenant: Tenant
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
        roles = {r.code: r for r in await seed_system_roles(db)}
        admin = User(name=f"{code} Admin", email=f"admin@{code.lower()}.example", password="x",
                     role_id=roles["admin"].id)
        member = User(name=f"{code} Member", email=f"member@{code.lower()}.example", password="x",
                      role_id=roles["member"].id)
        db.add_all([admin, member])
        await db.flush()
    await db.commit()
    return TenantWorld(tenant, admin, member)


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
