"""Global soft-delete filter (integration: real Postgres).

Opted-in models (SoftDeleteFilteredMixin) are filtered on every SELECT;
include_deleted=True escapes; partial unique indexes ignore ghosts.
"""

from sqlalchemy import select

from app.modules.organizations.model import Organization


async def test_soft_deleted_rows_hidden_from_selects(db):
    org = Organization(name="Ghost Org")
    db.add(org)
    await db.flush()

    org.soft_delete()
    await db.flush()

    # Scoped to this row: a migrated database always has the deployment's own
    # organization, so "every organization" is never an empty list.
    live = (await db.scalars(select(Organization).where(Organization.id == org.id))).all()
    assert live == []
    # db.get is filtered too — once the identity map no longer short-circuits
    # the SELECT (an in-session instance is always returned as-is by the ORM).
    db.expunge_all()
    assert await db.get(Organization, org.id) is None


async def test_include_deleted_escape_hatch_and_restore(db):
    org = Organization(name="Lazarus Org")
    db.add(org)
    await db.flush()
    org.soft_delete()
    await db.flush()

    ghost = await db.scalar(
        select(Organization)
        .where(Organization.id == org.id)
        .execution_options(include_deleted=True)
    )
    assert ghost is not None

    ghost.restore()
    await db.flush()
    assert await db.get(Organization, org.id) is not None


async def test_partial_unique_index_allows_reuse_after_soft_delete(db):
    """A soft-deleted ghost must not block the same zoho_id from re-syncing
    as a new row (partial unique index WHERE deleted_at IS NULL)."""
    first = Organization(name="One", zoho_id="dup-1")
    db.add(first)
    await db.flush()
    first.soft_delete()
    await db.flush()

    second = Organization(name="Two", zoho_id="dup-1")
    db.add(second)
    await db.flush()  # would raise IntegrityError without the partial index

    live = (await db.scalars(select(Organization).where(Organization.zoho_id == "dup-1"))).all()
    assert [o.name for o in live] == ["Two"]
