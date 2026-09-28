"""RBAC engine: the catalogue, grant modes, scope matching and the grant cache (docs/rbac-module.md §4)."""

import datetime as dt

import pytest
from sqlalchemy import select, update

from app.core.conf import settings
from app.modules.rbac import engine
from app.modules.rbac.catalogue import ALL_CODES, OWNER_ONLY, PERMISSIONS, expand
from app.modules.rbac.deps import Perm
from app.modules.rbac.engine import Grant, Target
from app.modules.rbac.templates import ROLE_TEMPLATES
from app.modules.roles.model import Role
from app.modules.users.model import User


# ── unit ────────────────────────────────────────────────────────────────────

def test_the_catalogue_is_well_formed():
    assert len(ALL_CODES) == len(PERMISSIONS) > 50
    assert OWNER_ONLY == {"rbac.owner:assign"}
    assert all(code.count(":") == 1 and code.count(".") == 1 for code in ALL_CODES)


def test_manage_implies_crud_but_not_the_other_actions():
    got = expand({"teams.team:manage", "teams.membership:assign"})
    assert {"teams.team:create", "teams.team:read", "teams.team:update", "teams.team:delete"} <= got
    assert "teams.membership:approve" not in got and "teams.membership:read" not in got


def test_templates_only_reference_catalogue_codes():
    for template in ROLE_TEMPLATES:
        assert template.permissions <= ALL_CODES, (template.code, template.permissions - ALL_CODES)


def test_perm_refuses_an_unknown_code_at_import_time():
    """A typo must be a startup failure, not a route that 403s forever."""
    with pytest.raises(RuntimeError, match="unknown permission"):
        Perm("orders.order:read")


def _grant(mode: str, **extra) -> Grant:
    return Grant(source="base", scope="tenant", role_id=1, role_code="x", level=1, mode=mode, **extra)


def test_grant_modes():
    assert _grant("all").has("rbac.owner:assign")
    assert not _grant("all_but_owner_only").has("rbac.owner:assign")
    assert _grant("all_but_owner_only").has("teams.team:create")
    assert not _grant("all").has("nope.nope:nope"), "an unknown code is never granted, even to an owner"
    explicit = _grant("explicit", permissions=frozenset({"teams.team:read"}))
    assert explicit.has("teams.team:read") and not explicit.has("teams.team:create")


def test_a_grant_survives_the_cache_round_trip():
    grant = _grant("explicit", permissions=frozenset({"teams.team:read"}), org_id=3, org_path="/a/",
                   descendants=True, node_ids=frozenset({4, 5}))
    assert Grant.from_json(grant.to_json()) == grant


def test_the_cache_ttl_is_clipped_to_the_next_grant_boundary(monkeypatch):
    monkeypatch.setattr(settings, "RBAC_CACHE_TTL_SECONDS", 300)
    now = dt.datetime.now(dt.UTC)
    assert engine._ttl_seconds([], now) == 300
    assert 19 <= engine._ttl_seconds([now + dt.timedelta(seconds=20)], now) <= 20
    assert engine._ttl_seconds([now + dt.timedelta(hours=1)], now) == 300     # far away: the safety-net TTL wins
    monkeypatch.setattr(settings, "RBAC_CACHE_TTL_SECONDS", 0)
    assert engine._ttl_seconds([now + dt.timedelta(seconds=20)], now) == 0     # 0 = cache off


# ── scope matching against a real organization tree ─────────────────────────

async def test_a_base_role_reaches_its_organization_and_descendants_never_siblings(tree_world, db):
    _, w = tree_world
    branch_admin = await engine.load_grants(db, w.admin_a)
    assert await branch_admin.allows(db, "teams.team:create", Target(organization_id=w.branch_a.id))
    assert not await branch_admin.allows(db, "teams.team:create", Target(organization_id=w.branch_b.id))
    assert not await branch_admin.allows(db, "teams.team:create", Target(organization_id=w.holding.id))

    holding_admin = await engine.load_grants(db, w.holding_admin)
    for org in (w.holding, w.branch_a, w.branch_b):
        assert await holding_admin.allows(db, "teams.team:create", Target(organization_id=org.id)), org.org_code


async def test_admin_is_computed_and_lacks_only_the_owner_only_permissions(tree_world, db):
    _, w = tree_world
    admin = await engine.load_grants(db, w.holding_admin)
    target = Target(organization_id=w.holding.id)
    assert await admin.allows(db, "org.organization:create", target)
    assert not await admin.allows(db, "rbac.owner:assign", target)


async def test_a_member_may_read_but_not_write(tree_world, db):
    _, w = tree_world
    member = await engine.load_grants(db, w.member_a)
    target = Target(organization_id=w.branch_a.id)
    assert await member.allows(db, "teams.team:read", target)
    assert not await member.allows(db, "teams.team:create", target)
    assert not await member.allows(db, "users.user:read", target), "the full user record is not for members"


async def test_a_tenant_level_action_needs_a_tenant_wide_grant(tree_world, db):
    from app.modules.rbac import service as rbac

    _, w = tree_world
    owner_role = await db.scalar(select(Role).where(Role.organization_id == w.holding.id, Role.code == "owner"))
    holding_admin = await engine.load_grants(db, w.holding_admin)
    creating_a_root = Target(tenant_level=True)
    assert not await holding_admin.allows(db, "org.organization:create", creating_a_root)

    await rbac.ensure_tenant_owner(db, w.holding_admin, owner_role)
    await db.commit()
    tenant_wide = await engine.load_grants(db, w.holding_admin)
    assert await tenant_wide.allows(db, "org.organization:create", creating_a_root)
    assert await tenant_wide.allows(db, "rbac.owner:assign", Target(organization_id=w.branch_b.id))


async def test_a_role_that_is_not_active_grants_nothing(tree_world, db):
    _, w = tree_world
    await db.execute(update(Role).where(Role.id == w.admin_a.role_id).values(status="inactive"))
    await db.commit()
    grants = await engine.load_grants(db, w.admin_a)
    assert grants.grants == []
    assert not await grants.allows(db, "teams.team:read", Target(organization_id=w.branch_a.id))


async def test_a_role_less_user_holds_no_grants(tree_world, db):
    _, w = tree_world
    await db.execute(update(User).where(User.id == w.member_a.id).values(role_id=None))
    await db.commit()
    await db.refresh(w.member_a)
    assert (await engine.load_grants(db, w.member_a)).grants == []


# ── the cache ───────────────────────────────────────────────────────────────

async def test_cached_grants_go_stale_until_the_tenant_epoch_is_bumped(tree_world, db, monkeypatch):
    _, w = tree_world
    monkeypatch.setattr(settings, "RBAC_CACHE_TTL_SECONDS", 60)
    await engine.bump_epoch(w.tenant.id)
    await engine.forget_user(w.tenant.id, w.admin_a.id)

    first = await engine.load_grants(db, w.admin_a)
    assert [g.role_code for g in first.grants] == ["admin"]

    member_role = await db.scalar(select(Role).where(Role.organization_id == w.branch_a.id, Role.code == "member"))
    await db.execute(update(User).where(User.id == w.admin_a.id).values(role_id=member_role.id))
    await db.commit()
    await db.refresh(w.admin_a)

    assert [g.role_code for g in (await engine.load_grants(db, w.admin_a)).grants] == ["admin"]   # served from Redis
    await engine.bump_epoch(w.tenant.id)                                                          # structural change
    assert [g.role_code for g in (await engine.load_grants(db, w.admin_a)).grants] == ["member"]

    await engine.forget_user(w.tenant.id, w.admin_a.id)
