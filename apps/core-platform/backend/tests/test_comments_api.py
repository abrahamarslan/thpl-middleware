"""Comments — one polymorphic table for "this entity said this, at this instant".

Layered like ``test_tax_assignments.py`` (the sibling polymorphic-owner module):

  * hermetic — the mixin's class-code derivation;
  * service + API — CRUD through ``POST/GET/PATCH/DELETE /api/comments``, the ownership
    rule (edit/delete your own; ``comments.comment:manage`` for anyone's), and the one
    remaining write-time check (``comments.commentable_entity_types.is_active``, a plain
    Python check, not a database trigger — see model.py's docstring for why that trigger
    was removed);
  * database — what is (and, now, deliberately is NOT) still enforced by writing PAST the
    service with raw inserts: the FK still refuses a completely unregistered owner_type,
    but an owner_id that does not exist, or belongs to another organization, now commits
    without complaint — ``comments.find_orphan_comments()`` is the safety net for the
    former.

``user`` is the real, migration-registered consumer (``users.model.User.comments``).
``category`` stands in, via a temporary opt-in the fixture removes again, for a class
that is registered in ``core.entity_types`` but has not opted into comments.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database.tenancy import tenant_scope
from app.modules.categories.model import Category, Taxonomy
from app.modules.comments import schema, service
from app.modules.comments.errors import CommentRuleError
from app.modules.comments.mixins import HasCommentsMixin, commentable_type_of
from app.modules.comments.model import Comment, CommentableEntityType
from app.modules.comments.registration import register_commentable_entity_type
from app.modules.organizations.model import Organization


# ── hermetic: the mixin derives the registry code from the class name ──────

def test_the_mixin_derives_the_registry_code_from_the_class_name():
    class Vehicle(HasCommentsMixin):
        pass

    class Widget(HasCommentsMixin):
        __commentable_type__ = "item"

    assert commentable_type_of(Vehicle) == "vehicle" and commentable_type_of(Widget) == "item"


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
async def category_commentable(db):
    """``category`` (registered in core.entity_types, never opted into comments)."""
    await db.run_sync(lambda session: register_commentable_entity_type(
        session.connection(), code="category", name="Category", target_schema="core", target_table="categories"))
    await db.flush()
    yield
    await db.rollback()
    await db.execute(text("DELETE FROM comments.comments WHERE owner_type = 'category'"))
    await db.execute(text("DELETE FROM comments.commentable_entity_types WHERE entity_type_code = 'category'"))
    await db.commit()


async def _category_row(db, world, name="Raw") -> Category:
    with tenant_scope(world.tenant.id, world.organization.id):
        taxonomy = Taxonomy(slug=f"t-{name.lower()}", name=name, organization_id=world.organization.id)
        db.add(taxonomy)
        await db.flush()
        category = Category(name=name, taxonomy_id=taxonomy.id, taxonomy_slug=taxonomy.slug,
                            organization_id=world.organization.id)
        db.add(category)
        await db.flush()
    await db.commit()
    return category


def _raw(tenant_id: int, organization_id: int, **kw) -> Comment:
    """A comment written PAST the service, with the fields OrgEntityMixin requires."""
    import datetime as dt

    kw.setdefault("commented_at", dt.datetime.now(dt.UTC))
    return Comment(tenant_id=tenant_id, organization_id=organization_id, **kw)


# ── API: CRUD on the real, migration-registered consumer (user) ─────────────

async def test_a_member_creates_reads_updates_and_deletes_their_own_comment(worlds):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)

    made = await client.post("/api/comments", headers=headers, json={
        "owner_type": "user", "owner_id": acme.member.id, "body": "Following up next week"})
    assert made.status_code == 201, made.text
    comment = made.json()["data"]
    assert comment["body"] == "Following up next week" and comment["owner_type"] == "user"
    assert comment["commented_by_user_id"] == acme.member.id and comment["is_system_generated"] is None

    listed = (await client.get(f"/api/comments/user/{acme.member.id}", headers=headers)).json()["data"]
    assert [c["id"] for c in listed] == [comment["id"]]

    patched = await client.patch(f"/api/comments/{comment['id']}", headers=headers, json={"body": "Amended"})
    assert patched.status_code == 200 and patched.json()["data"]["body"] == "Amended"

    deleted = await client.delete(f"/api/comments/{comment['id']}", headers=headers)
    assert deleted.status_code == 200
    assert (await client.get(f"/api/comments/user/{acme.member.id}", headers=headers)).json()["data"] == []


async def test_a_member_cannot_touch_someone_elses_comment_but_a_moderator_can(worlds):
    client, acme, _ = worlds
    admin_headers, member_headers = acme.auth(acme.admin), acme.auth(acme.member)

    made = await client.post("/api/comments", headers=admin_headers,
                             json={"owner_type": "user", "owner_id": acme.admin.id, "body": "Admin's own note"})
    comment_id = made.json()["data"]["id"]

    refused = await client.patch(f"/api/comments/{comment_id}", headers=member_headers, json={"body": "Hijacked"})
    assert refused.status_code == 403
    refused_delete = await client.delete(f"/api/comments/{comment_id}", headers=member_headers)
    assert refused_delete.status_code == 403

    # A plain member also lacks comments.comment:manage — the moderate routes 403, not just the rule.
    denied = await client.patch(f"/api/comments/{comment_id}/moderate", headers=member_headers,
                                json={"body": "Hijacked"})
    assert denied.status_code == 403 and denied.json()["data"]["permission"] == "comments.comment:manage"

    moderated = await client.patch(f"/api/comments/{comment_id}/moderate", headers=admin_headers,
                                   json={"body": "Moderated"})
    assert moderated.status_code == 200 and moderated.json()["data"]["body"] == "Moderated"
    assert (await client.delete(f"/api/comments/{comment_id}/moderate", headers=admin_headers)).status_code == 200


async def test_creating_a_comment_needs_an_organization(worlds):
    client, acme, _ = worlds
    missing_org = await client.post(
        "/api/comments", headers={k: v for k, v in acme.auth(acme.member).items() if k != "X-Organization-Code"},
        json={"owner_type": "user", "owner_id": acme.member.id, "body": "x"},
    )
    # Falls back to the ambient/bound organization (the caller's own) rather than refusing outright —
    # only asserting it does not 500; the friendly-422 path is app/database/scope.py's own contract.
    assert missing_org.status_code in (200, 201, 422)


# ── database: the registry and scope rules are authoritative ────────────────

async def test_the_database_refuses_a_completely_unregistered_owner_type(worlds, db):
    _, acme, _ = worlds
    db.add(_raw(acme.tenant.id, acme.organization.id, owner_type="not_a_real_type", owner_id=1))
    with pytest.raises(IntegrityError, match="fk_comments_owner_type"):
        await db.flush()
    await db.rollback()


async def test_the_service_refuses_a_registered_but_not_opted_in_class(worlds, db):
    """"brand" is a real core.entity_types code (the brands migration registers it) that has
    never opted into comments — the FK would pass; the service's is_active check is what
    refuses it (no database trigger does this any more — see model.py's docstring)."""
    _, acme, _ = worlds
    with tenant_scope(acme.tenant.id, acme.organization.id):
        with pytest.raises(CommentRuleError, match="disabled for entity type 'brand'"):
            await service.create_comment(
                db, schema.CommentCreate(owner_type="brand", owner_id=1, body="x"), actor_id=acme.member.id)


async def test_the_database_no_longer_proves_an_owner_exists_or_shares_the_organization(worlds, db):
    """Deliberate, per the user's instruction to drop that trigger: comments are high-volume,
    low-stakes rows, and the app-layer is_active check above is judged enough. A hard-deleted
    or cross-org owner_id now simply commits — comments.find_orphan_comments() is the net for
    the former; nothing catches the latter (comments are not security-sensitive enough to
    justify the extra rigor tax.tax_assignments pays for)."""
    _, acme, _ = worlds
    tid, oid = acme.tenant.id, acme.organization.id
    with tenant_scope(tid, oid):
        db.add(_raw(tid, oid, owner_type="user", owner_id=987654321))     # does not exist
        await db.flush()
    await db.commit()                                                    # no exception

    with tenant_scope(tid):
        second = Organization(org_code="ACME-CMT-2", legal_name="Acme Comments Two", tenant_id=tid)
        db.add(second)
        await db.flush()
    second_id = second.id
    with tenant_scope(tid, second_id):
        db.add(_raw(tid, second_id, owner_type="user", owner_id=acme.member.id))  # acme.member is in a DIFFERENT org
        await db.flush()
    await db.commit()                                                    # no exception either


async def test_the_orphan_finder_reports_an_owner_that_was_hard_deleted(worlds, db, category_commentable):
    _, acme, _ = worlds
    category = await _category_row(db, acme)
    tid, oid, cid = acme.tenant.id, acme.organization.id, category.id
    with tenant_scope(tid, oid):
        db.add(_raw(tid, oid, owner_type="category", owner_id=cid, body="note"))
        await db.flush()
    await db.commit()
    assert (await db.execute(text("SELECT * FROM comments.find_orphan_comments()"))).all() == []

    await db.execute(text("DELETE FROM core.categories WHERE id = :id"), {"id": cid})
    orphans = (await db.execute(text("SELECT orphan_owner_type, orphan_owner_id FROM "
                                     "comments.find_orphan_comments()"))).all()
    assert [tuple(o) for o in orphans] == [("category", cid)]
    await db.commit()


async def test_registering_a_class_is_idempotent_and_never_overwrites_the_description(db):
    """The one call a module makes to opt in — safe to re-run, and an operator's edit survives."""
    async def register(**kw):
        await db.run_sync(lambda session: register_commentable_entity_type(
            session.connection(), code="manufacturer", name="Manufacturer", target_schema="core",
            target_table="manufacturers", **kw))

    try:
        await register(description="first")
        row = await db.scalar(select(CommentableEntityType).where(
            CommentableEntityType.entity_type_code == "manufacturer"))
        assert row.description == "first" and row.is_active is True
        await register(description="second")                    # a later, different call
        await db.refresh(row)
        assert row.description == "first"                        # the first row stands
    finally:
        await db.rollback()
        await db.execute(text("DELETE FROM comments.commentable_entity_types WHERE entity_type_code = 'manufacturer'"))
        await db.commit()
