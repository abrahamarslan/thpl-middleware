"""Permissions OUTSIDE an HTTP request — Celery tasks and message consumers (docs/rbac-module.md §4.9)."""

import pytest
from sqlalchemy import select, update

from app.common.exception.errors import ForbiddenError
from app.database.tenancy import current_actor, current_organization_id, current_tenant_id
from app.modules.rbac.context import acting_as, check_actor, system_scope
from app.modules.rbac.engine import Target
from app.modules.roles.model import Role
from app.modules.users.model import User


async def test_a_task_reevaluates_the_actor_at_execution_time(tree_world, db):
    _, w = tree_world
    target = Target(organization_id=w.branch_a.id)
    await check_actor(db, w.admin_a.id, "teams.team:create", target)

    with pytest.raises(ForbiddenError):
        await check_actor(db, w.member_a.id, "teams.team:create", target)

    # A grant revoked while the job waited in the queue stops the job: the payload carries the actor's id,
    # never a permission decision.
    member_role = await db.scalar(select(Role).where(Role.organization_id == w.branch_a.id, Role.code == "member"))
    await db.execute(update(User).where(User.id == w.admin_a.id).values(role_id=member_role.id))
    await db.commit()
    await db.refresh(w.admin_a)
    with pytest.raises(ForbiddenError):
        await check_actor(db, w.admin_a.id, "teams.team:create", target)


async def test_a_user_who_can_no_longer_act_cannot_be_impersonated_by_a_job(tree_world, db):
    _, w = tree_world
    await db.execute(update(User).where(User.id == w.admin_a.id).values(is_deactivated=True))
    await db.commit()
    with pytest.raises(ForbiddenError, match="can no longer act"):
        async with acting_as(db, w.admin_a.id):
            pass

    with pytest.raises(ForbiddenError):
        async with acting_as(db, 999_999_999):
            pass


async def test_acting_as_binds_the_tenancy_context_like_a_request(tree_world, db):
    _, w = tree_world
    assert current_tenant_id() is None
    async with acting_as(db, w.admin_a.id) as actor:
        assert current_tenant_id() == w.tenant.id
        assert current_organization_id() == w.branch_a.id
        assert current_actor().user_id == w.admin_a.id
        await actor.require(db, "teams.team:create", Target(organization_id=w.branch_a.id))
    assert current_tenant_id() is None and current_actor().is_system


async def test_a_job_may_act_in_another_organization_the_actor_can_reach(tree_world, db):
    _, w = tree_world
    async with acting_as(db, w.holding_admin.id, organization_id=w.branch_b.id):
        assert current_organization_id() == w.branch_b.id
    with pytest.raises(ForbiddenError):
        await check_actor(db, w.admin_a.id, "teams.team:create", Target(organization_id=w.branch_b.id))


def test_system_jobs_run_as_a_named_component_without_rbac():
    with system_scope("zoho-sync", tenant_id=7, organization_id=9):
        actor = current_actor()
        assert actor.name == "system:zoho-sync" and actor.is_system
        assert current_tenant_id() == 7 and current_organization_id() == 9
    assert current_tenant_id() is None
