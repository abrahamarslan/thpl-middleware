"""Global soft-delete filter (integration: real Postgres).

Opted-in models (SoftDeleteFilteredMixin) are filtered on every SELECT;
include_deleted=True escapes; partial unique indexes ignore ghosts.
"""

from sqlalchemy import select

from app.modules.zoho.organizations.model import ZohoOrganization


async def test_soft_deleted_rows_hidden_from_selects(db):
    org = ZohoOrganization(name="Ghost Org")
    db.add(org)
    await db.flush()

    org.soft_delete()
    await db.flush()

    assert (await db.scalars(select(ZohoOrganization))).all() == []
    # db.get is filtered too — once the identity map no longer short-circuits
    # the SELECT (an in-session instance is always returned as-is by the ORM).
    db.expunge_all()
    assert await db.get(ZohoOrganization, org.id) is None


async def test_include_deleted_escape_hatch_and_restore(db):
    org = ZohoOrganization(name="Lazarus Org")
    db.add(org)
    await db.flush()
    org.soft_delete()
    await db.flush()

    ghost = await db.scalar(
        select(ZohoOrganization)
        .where(ZohoOrganization.id == org.id)
        .execution_options(include_deleted=True)
    )
    assert ghost is not None

    ghost.restore()
    await db.flush()
    assert await db.get(ZohoOrganization, org.id) is not None


async def test_partial_unique_index_allows_reuse_after_soft_delete(db):
    """A soft-deleted ghost must not block the same zoho_id from re-syncing
    as a new row (partial unique index WHERE deleted_at IS NULL)."""
    first = ZohoOrganization(name="One", zoho_id="dup-1")
    db.add(first)
    await db.flush()
    first.soft_delete()
    await db.flush()

    second = ZohoOrganization(name="Two", zoho_id="dup-1")
    db.add(second)
    await db.flush()  # would raise IntegrityError without the partial index

    live = (await db.scalars(select(ZohoOrganization))).all()
    assert [o.name for o in live] == ["Two"]
