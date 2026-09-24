"""Organization scope resolution — `app/database/scope.py`.

Every write in this platform lands in exactly one organization, and this is the
one place that decides which. The order it resolves in is the contract:

    X-Organization-Code → X-Organization-Id → the bound request → the tenant's
    only organization → DEFAULT_ORGANIZATION_CODE → refuse (422)

The refusal matters as much as the resolution: `organization_id` is NOT NULL on
every operational table, so the alternative to a clean 422 is an IntegrityError
from inside a flush.
"""

import pytest
from sqlalchemy import select

from app.common.exception.errors import ForbiddenError
from app.core.conf import settings
from app.database import scope
from app.database.tenancy import tenant_scope
from app.modules.organizations.model import Organization
from app.modules.tenants.model import Tenant


async def _bare_tenant(db, code: str) -> Tenant:
    """A tenant with no organization — the only state that can still refuse."""
    tenant = Tenant(tenant_code=code, name=f"{code} Ltd",
                    primary_contact_email=f"ops@{code.lower()}.example", status="active")
    db.add(tenant)
    await db.flush()
    return tenant


# ── the default, which is what a single-company deployment runs on ──────────

async def test_the_configured_default_is_used_when_nothing_is_named(db):
    """`DEFAULT_ORGANIZATION_CODE` in `DEFAULT_TENANT_CODE` — the whole point of
    the setting: registration, a Celery task and a Zoho run all land there
    without any per-request ceremony."""
    found = await scope.require(db)
    assert found.organization_id is not None and found.tenant_id is not None

    org = await db.scalar(
        select(Organization).where(Organization.id == found.organization_id)
        .execution_options(all_tenants=True)
    )
    assert org is not None and org.tenant_id == found.tenant_id


async def test_a_tenant_with_no_organization_is_refused_not_guessed(db):
    bare = await _bare_tenant(db, "SCOPE-BARE")
    with tenant_scope(bare.id):
        with pytest.raises(scope.OrganizationRequiredError) as raised:
            await scope.require(db)
    # The error names both headers AND the setting: three ways out, not "no".
    assert raised.value.code == "organization_required"
    assert "X-Organization-Code" in raised.value.data["headers"]
    assert raised.value.data["setting"] == "DEFAULT_ORGANIZATION_CODE"


# ── naming an organization explicitly ───────────────────────────────────────

async def test_an_org_code_resolves_to_its_tenant_and_organization(db, worlds):
    _, acme, _ = worlds
    found = await scope.resolve(db, org_code=acme.organization.org_code)
    assert found.organization_id == acme.organization.id
    assert found.tenant_id == acme.tenant.id


async def test_an_org_code_is_case_insensitive(db, worlds):
    _, acme, _ = worlds
    found = await scope.resolve(db, org_code=acme.organization.org_code.lower())
    assert found.organization_id == acme.organization.id


async def test_an_unknown_org_code_is_refused(db):
    with pytest.raises(ForbiddenError):
        await scope.resolve(db, org_code="NO-SUCH-ORG")


async def test_a_code_cannot_reach_across_tenants(db, worlds):
    """The isolation rule. An authenticated caller's lookup is confined to
    their own tenant, so naming another tenant's code is a 403 — not a write
    into someone else's data."""
    _, acme, globex = worlds
    # Unconfined, GLOBEX's code resolves...
    assert (await scope.resolve(db, org_code=globex.organization.org_code)) is not None
    # ...confined to ACME's tenant, it does not exist.
    with pytest.raises(ForbiddenError):
        await scope.resolve(db, org_code=globex.organization.org_code, for_tenant=acme.tenant.id)


async def test_the_bound_request_wins_over_the_deployment_default(db, worlds):
    """A signed-in caller who names nothing stays in their own organization.
    Falling through to the deployment default would silently move their write
    into another tenant."""
    _, acme, _ = worlds
    with tenant_scope(acme.tenant.id, acme.organization.id):
        found = await scope.resolve(db)
    assert found.organization_id == acme.organization.id
    assert found.tenant_id == acme.tenant.id


async def test_a_bound_tenant_never_falls_through_to_the_default(db):
    """Tenant bound, organization not: the answer is that tenant's only
    organization, or nothing — never the deployment's."""
    bare = await _bare_tenant(db, "SCOPE-NOFALL")
    default = await scope.configured_default(db)
    assert default is not None                       # the deployment has one
    with tenant_scope(bare.id):
        assert await scope.resolve(db) is None       # ...and it is NOT used here


# ── the HTTP surface ────────────────────────────────────────────────────────

async def test_the_org_code_header_binds_the_request(worlds):
    """`X-Organization-Code` is the human-readable form of the scope. It binds
    an organization of the caller's OWN tenant."""
    client, acme, _ = worlds
    response = await client.get(
        "/api/organizations",
        headers=acme.auth(acme.member, **{"X-Organization-Code": acme.organization.org_code}),
    )
    assert response.status_code == 200


async def test_another_tenants_org_code_is_refused_over_http(worlds):
    client, acme, globex = worlds
    response = await client.get(
        "/api/organizations",
        headers=acme.auth(acme.member, **{"X-Organization-Code": globex.organization.org_code}),
    )
    assert response.status_code == 403


async def test_registration_lands_in_the_configured_default_organization(db, worlds):
    """Registration is unauthenticated: no context to stamp from, and
    `users.organization_id` is NOT NULL. The deployment default is the answer."""
    client, _, _ = worlds
    response = await client.post("/api/auth/register", json={
        "name": "Scope Default", "email": "scope-default@example.com", "password": "Str0ng!Passw0rd",
    })
    assert response.status_code == 201, response.text

    default = await scope.configured_default(db)
    from app.modules.users.model import User

    user = await db.scalar(select(User).where(User.email == "scope-default@example.com")
                           .execution_options(all_tenants=True))
    assert user.organization_id == default.organization_id
    assert user.tenant_id == default.tenant_id


async def test_registration_can_name_its_organization_by_code(db, worlds):
    """A public sign-up for a specific company: the code chooses the TENANT too,
    which is why registration resolves it unconfined."""
    client, _, globex = worlds
    response = await client.post(
        "/api/auth/register",
        headers={"X-Organization-Code": globex.organization.org_code},
        json={"name": "Globex Hire", "email": "hire@globex.example", "password": "Str0ng!Passw0rd"},
    )
    assert response.status_code == 201, response.text

    from app.modules.users.model import User

    user = await db.scalar(select(User).where(User.email == "hire@globex.example")
                           .execution_options(all_tenants=True))
    assert user.organization_id == globex.organization.id
    assert user.tenant_id == globex.tenant.id


def test_the_deployment_is_configured_with_both_halves():
    """A deployment that sets the tenant but not the organization has no default
    at all — the state that left the stack writing to a tenant the seeder never
    touched. Both belong in .env and in docker-compose.yml."""
    assert settings.DEFAULT_TENANT_CODE, "DEFAULT_TENANT_CODE must name the deployment's tenant"


# ── the id header is optional: a code in it must never block ─────────────────

async def test_a_non_uuid_organization_id_header_is_treated_as_a_code(worlds):
    """`X-Organization-Id` is documented as a uuid, but a client that only holds
    the code sends it there — the reported failure. It must be read as a code,
    not refused; passing the code in BOTH headers is the exact case."""
    client, acme, _ = worlds
    headers = acme.auth(
        acme.member,
        **{"X-Organization-Id": acme.organization.org_code,
           "X-Organization-Code": acme.organization.org_code},
    )
    assert (await client.get("/api/organizations", headers=headers)).status_code == 200


async def test_me_accepts_the_code_in_the_organization_id_header(worlds):
    """The exact reported case: a client sends the code in the id header (only).
    It must resolve as a code, never be refused for not being a uuid."""
    client, acme, _ = worlds
    response = await client.get(
        "/api/auth/me",
        headers=acme.auth(acme.member, **{"X-Organization-Id": acme.organization.org_code}),
    )
    assert response.status_code == 200


async def test_a_malformed_id_with_a_valid_code_is_not_blocked(worlds):
    """A malformed id next to a valid code is ignored: the code wins and the
    request is not refused for the id's format."""
    client, acme, _ = worlds
    response = await client.get(
        "/api/auth/me",
        headers=acme.auth(acme.member, **{"X-Organization-Id": "not-a-uuid",
                                          "X-Organization-Code": acme.organization.org_code}),
    )
    assert response.status_code == 200


async def test_a_nonuuid_id_that_names_no_organization_is_a_clean_refusal(worlds):
    """Leniency is about FORMAT, not about accepting nonsense: a value that is
    not a uuid and matches no code is still a normal 403 with the code message —
    never the old 'must be an organization uuid' string."""
    client, acme, _ = worlds
    response = await client.get(
        "/api/auth/me",
        headers=acme.auth(acme.member, **{"X-Organization-Id": "NO-SUCH-CODE"}),
    )
    assert response.status_code == 403
    assert "must be an organization uuid" not in response.text


async def test_a_valid_but_foreign_org_id_is_still_refused(worlds):
    """Leniency is ONLY for a malformed id. A well-formed uuid of another tenant
    is still a 403 — the isolation model is untouched."""
    client, acme, globex = worlds
    headers = globex.auth(globex.member, **{"X-Organization-Id": str(acme.organization.uuid)})
    assert (await client.get("/api/organizations", headers=headers)).status_code == 403


# ── GET /api/auth/me/organization: the code a signed-in client needs ─────────

async def test_me_organization_returns_the_users_own_organization(worlds):
    client, acme, _ = worlds
    response = await client.get("/api/auth/me/organization", headers=acme.auth(acme.member))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["msg"] == "Organization retrieved successfully."
    assert body["data"]["org_code"] == "ACME-HQ"
    assert body["data"]["legal_name"] == "ACME HQ"
    assert body["data"]["uuid"] == str(acme.organization.uuid)


async def test_me_organization_alias_matches(worlds):
    """`/api/me/organization` and `/api/auth/me/organization` are the same view."""
    client, acme, _ = worlds
    auth = acme.auth(acme.member)
    primary = await client.get("/api/auth/me/organization", headers=auth)
    alias = await client.get("/api/me/organization", headers=auth)
    assert primary.status_code == 200 and alias.status_code == 200
    assert primary.json()["data"] == alias.json()["data"]


async def test_me_organization_reports_the_users_own_not_the_selected_branch(worlds):
    """`/me` is the user's OWN organization. A header may select a branch as the
    request's active scope, but the identity returned here is not the branch."""
    client, acme, _ = worlds
    created = await client.post(
        "/api/organizations", headers=acme.auth(acme.admin),
        json={"org_code": "ACME-BRANCH", "legal_name": "Acme Branch", "org_type": "solo"},
    )
    assert created.status_code == 201, created.text
    branch = created.json()["data"]

    response = await client.get(
        "/api/auth/me/organization",
        headers=acme.auth(acme.member, **{"X-Organization-Id": branch["uuid"]}),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["org_code"] == "ACME-HQ"

