"""Tax assignments — one polymorphic table for "this entity carries these taxes".

Three layers, tested as three layers:

  * hermetic — context resolution (:func:`select_applicable`), the write model's
    identity, the snapshot, the input schema, the mixin's class-code derivation;
  * service + API — the clean 4xx a caller gets (policy, grants, one tax per
    context, exemptions) through ``PUT/GET /api/taxes/assignments`` and through
    the categories resource that embeds the same input;
  * database — the same rules asserted by writing PAST the service with raw
    inserts and committing, because the deferred triggers fire at COMMIT and the
    database, not the service, is authoritative.

``category`` is the real consumer. ``brand`` (registered in ``core.entity_types``, not
opted in) stands in for the classes that do not exist yet — an invoice line that
takes several taxes and an exemption — via a temporary policy row that the fixture
removes again, because ``tax.taxable_entity_types`` is seeded data the suite never truncates.
"""

from dataclasses import dataclass
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database.tenancy import tenant_scope
from app.modules.brands.model import Brand
from app.modules.categories.model import Category, Taxonomy
from app.modules.organizations.model import Organization
from app.modules.sync.crosswalk import upsert_record
from app.modules.sync.models import LinkState, PendingReference
from app.modules.sync.reconcile import drain_pending_references
from app.modules.taxes import assignment_crud as crud
from app.modules.taxes import assignment_service as service
from app.modules.taxes.assignment import TaxableEntityType, TaxAssignment
from app.modules.taxes.assignment_schema import TaxAssignmentItem
from app.modules.taxes.assignment_service import AssignmentSpec, TaxRuleError
from app.modules.taxes.component import TaxComponent, TaxGroupMember
from app.modules.taxes.exemption import TaxExemption
from app.modules.taxes.mixins import HasTaxesMixin, taxable_type_of
from app.modules.taxes.org_tax import OrganizationTaxComponent
from app.modules.taxes.preference import OrgDefaultTaxPreference
from app.modules.taxes.registration import register_taxable_entity_type


# ── hermetic: context resolution ────────────────────────────────────────────

@dataclass
class Row:
    """Anything with the four attributes ``select_applicable`` reads."""

    id: int
    tax_specification: str | None = None
    transaction_type: str | None = None
    position: int = 0


def _ids(rows):
    return [row.id for row in rows]


def test_an_any_context_row_applies_everywhere():
    rows = [Row(1)]
    for spec in ("inter", "intra", None):
        for txn in ("sales", "purchase", None):
            assert _ids(service.select_applicable(rows, specification=spec, transaction_type=txn)) == [1]


def test_the_most_specific_level_wins_instead_of_stacking():
    """An owner's inter tax OVERRIDES its any-context tax for an inter-state sale."""
    rows = [Row(1), Row(2, "inter"), Row(3, "inter", "sales")]
    pick = lambda spec, txn: _ids(service.select_applicable(rows, specification=spec, transaction_type=txn))  # noqa: E731
    assert pick("inter", "sales") == [3]            # both columns match: most specific
    assert pick("inter", "purchase") == [2]         # the sales-only row does not match a purchase
    assert pick("intra", "sales") == [1]            # falls back to the any-context row


def test_asking_with_no_specification_never_matches_a_row_that_names_one():
    """"I do not know" is not "any": it must not pick an inter tax by accident."""
    rows = [Row(1, "inter"), Row(2, "intra")]
    assert service.select_applicable(rows, specification=None, transaction_type=None) == []
    assert _ids(service.select_applicable(rows + [Row(3)], specification=None, transaction_type=None)) == [3]


def test_taxes_at_one_level_apply_together_in_position_order():
    rows = [Row(1, "inter", position=2), Row(2, "inter", position=0), Row(3, "inter", position=1)]
    assert _ids(service.select_applicable(rows, specification="inter", transaction_type=None)) == [2, 3, 1]


def test_an_assignments_identity_is_what_it_names_and_where():
    a = AssignmentSpec(tax_component_id=5, tax_specification="inter")
    assert a.key == ("component", 5, "inter", None) and a.context == ("inter", None)
    assert AssignmentSpec(tax_exemption_id=5).key[0] == "exemption"
    assert AssignmentSpec(external_ref="Z1", tax_specification="intra").key == ("pending", "Z1", "intra", None)


def test_the_input_names_exactly_one_target():
    assert TaxAssignmentItem(tax="5").tax == "5"
    assert TaxAssignmentItem(tax_exemption="7").tax_exemption == "7"
    for bad in ({}, {"tax": "5", "tax_exemption": "7"}):
        with pytest.raises(ValidationError):
            TaxAssignmentItem(**bad)
    with pytest.raises(ValidationError):
        TaxAssignmentItem(tax="5", tax_specification="sideways")


def test_a_snapshot_keeps_a_groups_members_so_the_split_survives():
    def leaf(id_, name, pct, kind):
        return TaxComponent(id=id_, tax_name=name, tax_percentage=Decimal(pct), tax_type="tax",
                            tax_specific_type=kind)

    group = TaxComponent(id=1, tax_name="GST18", tax_percentage=Decimal("18"), tax_type="tax_group")
    group.__dict__["members"] = [
        TaxGroupMember(tax_group_id=1, member_tax_id=2, position=0),
        TaxGroupMember(tax_group_id=1, member_tax_id=3, position=1),
    ]
    group.members[0].__dict__["member_tax"] = leaf(2, "CGST9", "9", "cgst")
    group.members[1].__dict__["member_tax"] = leaf(3, "SGST9", "9", "sgst")
    snap = service.build_snapshot(group, None)
    assert snap["tax_name"] == "GST18" and snap["tax_percentage"] == "18"
    assert [m["tax_name"] for m in snap["members"]] == ["CGST9", "SGST9"]
    assert service.build_snapshot(None, TaxExemption(id=9, exemption_type="exempt")) == {
        "kind": "exemption", "tax_exemption_id": 9, "exemption_type": "exempt"}


def test_the_mixin_derives_the_registry_code_from_the_class_name():
    class InvoiceLine(HasTaxesMixin):
        pass

    class Widget(HasTaxesMixin):
        __taxable_type__ = "item"

    assert taxable_type_of(InvoiceLine) == "invoice_line" and taxable_type_of(Widget) == "item"
    assert taxable_type_of(Category) == "category"


def test_the_indexes_that_carry_the_rules_are_partial_and_null_safe():
    """"Any context" is NULL; without NULLS NOT DISTINCT two any-context rows would not collide."""
    indexes = {i.name: i for i in TaxAssignment.__table__.indexes}
    for name in ("uq_tax_assignments_component", "uq_tax_assignments_exemption", "uq_tax_assignments_pending"):
        opts = indexes[name].dialect_options["postgresql"]
        assert indexes[name].unique and opts["nulls_not_distinct"] is True and opts["where"] is not None, name
    assert {"fk_tax_assignments_owner_type", "fk_tax_assignments_component", "fk_tax_assignments_exemption"} <= {
        fk.name for fk in TaxAssignment.__table__.foreign_key_constraints}


# ── integration helpers ─────────────────────────────────────────────────────

async def _tax(db, world, name="IGST18", pct="18", *, grant=True, **kw) -> TaxComponent:
    kw.setdefault("tax_type", "tax")
    with tenant_scope(world.tenant.id, world.organization.id):
        component = TaxComponent(tenant_id=world.tenant.id, tax_name=name, tax_percentage=Decimal(pct), **kw)
        db.add(component)
        await db.flush()
        if grant:
            db.add(OrganizationTaxComponent(tenant_id=world.tenant.id, organization_id=world.organization.id,
                                            tax_component_id=component.id))
            await db.flush()
    return component


async def _taxonomy(client, headers, slug="grocery") -> dict:
    response = await client.post("/api/taxonomies", json={"slug": slug, "name": slug.title()}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _category(client, headers, taxonomy_id, name="Soap", **extra) -> dict:
    response = await client.post("/api/categories", json={"taxonomy_id": taxonomy_id, "name": name, **extra},
                                 headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _codes(response) -> tuple[int, str | None]:
    return response.status_code, response.json().get("code")


@pytest.fixture
async def brand_policy(db):
    """``brand`` as a class that takes several taxes AND an exemption (an invoice line's shape)."""
    await db.run_sync(lambda session: register_taxable_entity_type(
        session.connection(), code="brand", name="Brand", target_schema="core", target_table="brands",
        allows_multiple=True, allows_exemption=True))
    await db.flush()
    yield
    await db.rollback()
    await db.execute(text("DELETE FROM tax.tax_assignments WHERE owner_type_code = 'brand'"))
    await db.execute(text("DELETE FROM tax.taxable_entity_types WHERE entity_type_code = 'brand'"))
    await db.commit()


async def _brand(db, world, name="Line 1") -> Brand:
    with tenant_scope(world.tenant.id, world.organization.id):
        brand = Brand(name=name, organization_id=world.organization.id, owner_type="organization",
                      owner_id=world.organization.id)
        db.add(brand)
        await db.flush()
    return brand


# ── the categories resource: a category carries its taxes ───────────────────

async def test_a_category_carries_one_tax_per_context_through_its_own_resource(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    igst = await _tax(db, acme, "IGST18")
    gst = await _tax(db, acme, "GST18", tax_type="tax_group")
    taxonomy = await _taxonomy(client, headers)

    made = await _category(client, headers, taxonomy["id"], tax_preferences=[
        {"tax": str(igst.id), "tax_specification": "inter"},
        {"tax": str(gst.id), "tax_specification": "intra"},
    ])
    by_context = {p["tax_specification"]: p for p in made["tax_preferences"]}
    assert set(by_context) == {"inter", "intra"}
    assert by_context["inter"]["tax"]["tax_name"] == "IGST18" and by_context["intra"]["tax"]["tax_type"] == "tax_group"
    assert all(p["source_system"] is None and p["owner_type_code"] == "category" for p in made["tax_preferences"])

    detail = (await client.get(f"/api/categories/{made['id']}", headers=headers)).json()["data"]
    assert {p["tax"]["tax_name"] for p in detail["tax_preferences"]} == {"IGST18", "GST18"}


async def test_updating_replaces_the_local_taxes_and_an_empty_list_clears_them(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    igst, cgst = await _tax(db, acme, "IGST18"), await _tax(db, acme, "CGST9")
    made = await _category(client, headers, (await _taxonomy(client, headers))["id"],
                           tax_preferences=[{"tax": str(igst.id), "tax_specification": "inter"}])

    patched = await client.patch(f"/api/categories/{made['id']}", headers=headers, json={
        "row_version": made["row_version"], "tax_preferences": [{"tax": str(cgst.id), "tax_specification": "inter"}]})
    assert patched.status_code == 200, patched.text
    assert [p["tax"]["tax_name"] for p in patched.json()["data"]["tax_preferences"]] == ["CGST9"]

    cleared = await client.patch(f"/api/categories/{made['id']}", headers=headers, json={
        "row_version": patched.json()["data"]["row_version"], "tax_preferences": []})
    assert cleared.json()["data"]["tax_preferences"] == []

    untouched = await client.patch(f"/api/categories/{made['id']}", headers=headers, json={
        "row_version": cleared.json()["data"]["row_version"], "tax_preferences": [
            {"tax": str(cgst.id)}]})
    kept = await client.patch(f"/api/categories/{made['id']}", headers=headers, json={
        "row_version": untouched.json()["data"]["row_version"], "title": "Renamed"})
    assert [p["tax"]["tax_name"] for p in kept.json()["data"]["tax_preferences"]] == ["CGST9"]   # not sent = kept


async def test_a_category_takes_one_tax_per_context_and_no_exemptions(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    igst, other = await _tax(db, acme, "IGST18"), await _tax(db, acme, "IGST5", "5")
    taxonomy = await _taxonomy(client, headers)

    two = await client.post("/api/categories", headers=headers, json={
        "taxonomy_id": taxonomy["id"], "name": "Two", "tax_preferences": [
            {"tax": str(igst.id), "tax_specification": "inter"}, {"tax": str(other.id), "tax_specification": "inter"}]})
    assert _codes(two) == (422, "tax_rule_violation") and "one tax per context" in two.json()["msg"]

    with tenant_scope(acme.tenant.id, acme.organization.id):
        exemption = TaxExemption(tenant_id=acme.tenant.id, tax_exemption_code="BILL OF SUPPLY")
        db.add(exemption)
        await db.flush()
    made = await client.post("/api/categories", headers=headers, json={
        "taxonomy_id": taxonomy["id"], "name": "Exempt", "tax_preferences": [{"tax_exemption": str(exemption.id)}]})
    assert _codes(made) == (422, "tax_rule_violation") and "cannot carry a tax exemption" in made.json()["msg"]


async def test_an_organization_may_only_assign_a_tax_it_has_been_granted(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    ungranted = await _tax(db, acme, "SECRET", grant=False)
    made = await client.post("/api/categories", headers=headers, json={
        "taxonomy_id": (await _taxonomy(client, headers))["id"], "name": "X",
        "tax_preferences": [{"tax": str(ungranted.id)}]})
    assert _codes(made) == (422, "tax_rule_violation") and "not enabled for this organization" in made.json()["msg"]


async def test_another_tenants_tax_does_not_exist_for_me(worlds, db):
    client, acme, globex = worlds
    theirs = await _tax(db, globex, "THEIRS")
    made = await client.post("/api/categories", headers=acme.auth(acme.admin), json={
        "taxonomy_id": (await _taxonomy(client, acme.auth(acme.admin)))["id"], "name": "X",
        "tax_preferences": [{"tax": str(theirs.id)}]})
    assert _codes(made) == (422, "tax_rule_violation") and "not found" in made.json()["msg"]


async def test_deleting_a_category_takes_its_taxes_with_it(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    igst = await _tax(db, acme)
    made = await _category(client, headers, (await _taxonomy(client, headers))["id"],
                           tax_preferences=[{"tax": str(igst.id), "tax_specification": "inter"}])
    assert (await client.delete(f"/api/categories/{made['id']}?reason=cleanup", headers=headers)).status_code == 200
    assert await crud.usage_of_component(db, igst.id) == 0


# ── the generic resource: any owner class ───────────────────────────────────

async def test_the_generic_resource_lists_and_replaces_any_owners_taxes(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    igst = await _tax(db, acme)
    category = await _category(client, headers, (await _taxonomy(client, headers))["id"])

    types = (await client.get("/api/taxes/assignments/taxable-types", headers=headers)).json()["data"]
    policy = next(t for t in types if t["entity_type_code"] == "category")
    assert (policy["allows_multiple"], policy["allows_exemption"], policy["is_enabled"]) == (False, False, True)

    put = await client.put(f"/api/taxes/assignments/category/{category['id']}", headers=headers, json={
        "items": [{"tax": str(igst.id), "tax_specification": "inter", "transaction_type": "sales"}]})
    assert put.status_code == 200, put.text
    got = (await client.get(f"/api/taxes/assignments/category/{category['id']}", headers=headers)).json()["data"]
    assert [(g["tax"]["tax_name"], g["tax_specification"], g["transaction_type"]) for g in got] == [
        ("IGST18", "inter", "sales")]

    # A class that has not opted in cannot carry taxes; an owner that does not exist is a 404.
    nope = await client.get("/api/taxes/assignments/brand/1", headers=headers)
    assert _codes(nope) == (422, "tax_rule_violation")
    missing = await client.put("/api/taxes/assignments/category/999999", headers=headers, json={"items": []})
    assert missing.status_code == 404


async def test_removing_one_local_assignment_by_reference(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    igst = await _tax(db, acme)
    category = await _category(client, headers, (await _taxonomy(client, headers))["id"],
                               tax_preferences=[{"tax": str(igst.id)}])
    ref = category["tax_preferences"][0]["uuid"]
    assert (await client.delete(f"/api/taxes/assignments/{ref}?reason=mistake", headers=headers)).status_code == 200
    assert await crud.usage_of_component(db, igst.id) == 0


# ── service: a class that takes several taxes and an exemption ──────────────

async def test_a_class_that_allows_several_taxes_and_an_exemption(worlds, db, brand_policy):
    _, acme, _ = worlds
    line = await _brand(db, acme)
    igst, cess = await _tax(db, acme, "IGST18"), await _tax(db, acme, "CESS1", "1")
    with tenant_scope(acme.tenant.id, acme.organization.id):
        exemption = TaxExemption(tenant_id=acme.tenant.id, tax_exemption_code="SEZ", exemption_type="exempt")
        db.add(exemption)
        await db.flush()
        rows = await service.replace_assignments(db, "brand", line.id, [
            AssignmentSpec(tax_component_id=igst.id, tax_specification="inter", position=0),
            AssignmentSpec(tax_component_id=cess.id, tax_specification="inter", position=1),
            AssignmentSpec(tax_exemption_id=exemption.id, position=2),
        ])
    await db.commit()
    assert [(r.tax_component_id, r.tax_exemption_id) for r in rows] == [
        (igst.id, None), (cess.id, None), (None, exemption.id)]


async def test_replace_is_a_diff_it_keeps_what_stays_and_only_touches_its_own_source(worlds, db, brand_policy):
    _, acme, _ = worlds
    line = await _brand(db, acme)
    a, b, c = [await _tax(db, acme, name, "1") for name in ("A", "B", "C")]
    with tenant_scope(acme.tenant.id, acme.organization.id):
        first = await service.replace_assignments(db, "brand", line.id, [
            AssignmentSpec(tax_component_id=a.id), AssignmentSpec(tax_component_id=b.id, position=1)])
        kept_id = next(r.id for r in first if r.tax_component_id == a.id)
        # the sync feeds one; a person's replace must not delete it, nor the sync's replace delete theirs
        await service.replace_assignments(db, "brand", line.id, [AssignmentSpec(tax_component_id=c.id,
                                          tax_specification="inter")], source_system="zoho")
        again = await service.replace_assignments(db, "brand", line.id, [AssignmentSpec(tax_component_id=a.id)])
    assert {(r.tax_component_id, r.source_system) for r in again} == {(a.id, None), (c.id, "zoho")}
    assert next(r.id for r in again if r.tax_component_id == a.id) == kept_id          # kept, not recreated


async def test_a_local_write_cannot_take_a_context_a_source_already_holds(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    igst, other = await _tax(db, acme, "IGST18"), await _tax(db, acme, "IGST5", "5")
    category = await _category(client, headers, (await _taxonomy(client, headers))["id"])
    with tenant_scope(acme.tenant.id, acme.organization.id):
        await service.replace_assignments(db, "category", category["id"], [
            AssignmentSpec(tax_component_id=igst.id, tax_specification="inter")], source_system="zoho")
        with pytest.raises(TaxRuleError, match="maintained by zoho"):
            await service.replace_assignments(db, "category", category["id"], [
                AssignmentSpec(tax_component_id=other.id, tax_specification="inter")])
    put = await client.delete(f"/api/taxes/assignments/{(await crud.list_for_owner(db, 'category', category['id']))[0].uuid}?reason=nope", headers=headers)
    assert _codes(put) == (422, "tax_rule_violation") and "maintained by zoho" in put.json()["msg"]


# ── resolution: which tax applies here? ─────────────────────────────────────

async def test_resolution_walks_the_chain_then_falls_back_to_the_organization_default(worlds, db, brand_policy):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    igst, gst5, org_default = await _tax(db, acme, "IGST18"), await _tax(db, acme, "IGST5", "5"), \
        await _tax(db, acme, "ORGDEF", "12")
    category = await _category(client, headers, (await _taxonomy(client, headers))["id"],
                               tax_preferences=[{"tax": str(igst.id), "tax_specification": "inter"}])
    line = await _brand(db, acme)
    with tenant_scope(acme.tenant.id, acme.organization.id):
        db.add(OrgDefaultTaxPreference(tenant_id=acme.tenant.id, organization_id=acme.organization.id,
                                       tax_specification="intra", default_tax_id=org_default.id))
        await db.flush()

        # the category answers when the line says nothing
        hit = await service.resolve_taxes(db, [("brand", line.id), ("category", category["id"])],
                                          specification="inter")
        assert hit.via == "owner" and hit.resolved_from == ("category", category["id"])
        assert [c.tax_name for c in hit.components] == ["IGST18"]

        # the more specific owner wins the moment it carries something
        await service.replace_assignments(db, "brand", line.id, [
            AssignmentSpec(tax_component_id=gst5.id, tax_specification="inter")])
        hit = await service.resolve_taxes(db, [("brand", line.id), ("category", category["id"])],
                                          specification="inter")
        assert hit.resolved_from == ("brand", line.id) and [c.tax_name for c in hit.components] == ["IGST5"]

        # nobody carries an intra tax: the organization's default answers
        fallback = await service.resolve_taxes(db, [("brand", line.id), ("category", category["id"])],
                                               specification="intra", organization_id=acme.organization.id)
        assert fallback.via == "organization_default" and [c.tax_name for c in fallback.components] == ["ORGDEF"]
        # and with no context there is nothing to fall back to
        assert (await service.resolve_taxes(db, [("category", category["id"])])).via == "none"

    api = await client.get("/api/taxes/assignments/resolve", headers=headers,
                           params=[("owner", f"category:{category['id']}"), ("specification", "inter")])
    assert api.json()["data"]["via"] == "owner" and api.json()["data"]["taxes"][0]["tax_name"] == "IGST18"


# ── freezing: an issued document keeps the tax as it was ────────────────────

async def test_freezing_snapshots_a_group_and_makes_the_row_immutable(worlds, db, brand_policy):
    _, acme, _ = worlds
    line = await _brand(db, acme)
    group = await _tax(db, acme, "GST18", tax_type="tax_group")
    cgst, sgst = await _tax(db, acme, "CGST9", "9"), await _tax(db, acme, "SGST9", "9")
    with tenant_scope(acme.tenant.id, acme.organization.id):
        db.add_all([TaxGroupMember(tenant_id=acme.tenant.id, tax_group_id=group.id, member_tax_id=cgst.id, position=0),
                    TaxGroupMember(tenant_id=acme.tenant.id, tax_group_id=group.id, member_tax_id=sgst.id, position=1)])
        await db.flush()
        await service.replace_assignments(db, "brand", line.id, [AssignmentSpec(tax_component_id=group.id)])
        assert await service.freeze_owner(db, "brand", line.id) == 1
        assert await service.freeze_owner(db, "brand", line.id) == 0                       # idempotent
        (row,) = await crud.list_for_owner(db, "brand", line.id)
        assert row.is_frozen and [m["tax_name"] for m in row.snapshot["members"]] == ["CGST9", "SGST9"]

        # the rate moves on; the issued document does not
        group.tax_percentage = Decimal("28")
        await db.flush()
        assert row.snapshot["tax_percentage"] == "18"

        from app.common.exception.errors import ConflictError
        with pytest.raises(ConflictError, match="frozen"):
            await service.replace_assignments(db, "brand", line.id, [])
    await db.commit()
    with pytest.raises(IntegrityError, match="is frozen"):                    # and not even a raw UPDATE can
        await db.execute(text("UPDATE tax.tax_assignments SET position = 3 WHERE id = :id"), {"id": row.id})
    await db.rollback()


# ── pending: a source's tax that has not been synced yet ────────────────────

async def test_an_unsynced_tax_waits_on_the_reconcile_queue_and_is_linked_when_it_arrives(worlds, db):
    client, acme, _ = worlds
    category = await _category(client, acme.auth(acme.admin), (await _taxonomy(client, acme.auth(acme.admin)))["id"])
    with tenant_scope(acme.tenant.id, acme.organization.id):
        (row,) = await service.replace_assignments(db, "category", category["id"], [
            AssignmentSpec(external_ref="ZOHO-TAX-1", tax_specification="inter")], source_system="zoho")
    assert row.is_pending and row.tax_component_id is None
    waiter = await db.scalar(select(PendingReference).where(PendingReference.waiting_id == row.id))
    assert (waiter.module, waiter.external_id, waiter.waiting_table, waiter.waiting_column) == (
        "taxes", "ZOHO-TAX-1", "tax.tax_assignments", "tax_component_id")
    await db.commit()

    # pending rows never answer a resolution…
    with tenant_scope(acme.tenant.id, acme.organization.id):
        assert (await service.resolve_taxes(db, [("category", category["id"])], specification="inter")).via == "none"

    # …until the taxes module syncs the tax and the generic reconcile lane links it
    igst = await _tax(db, acme, "IGST18")
    await upsert_record(db, tenant_id=acme.tenant.id, source_system="zoho", module="taxes",
                        external_id="ZOHO-TAX-1", values={"entity_table": "tax.tax_components",
                                                          "entity_id": igst.id, "link_state": LinkState.LINKED})
    assert (await drain_pending_references(db, tenant_id=acme.tenant.id)).linked == 1
    await db.commit()
    await db.refresh(row)          # the reconcile lane wrote with a bare UPDATE, behind the identity map
    with tenant_scope(acme.tenant.id, acme.organization.id):
        (row,) = await crud.list_for_owner(db, "category", category["id"])
        assert row.tax_component_id == igst.id and not row.is_pending
        assert (await service.resolve_taxes(db, [("category", category["id"])], specification="inter")).via == "owner"


# ── the database is authoritative: writing PAST the service ─────────────────

def _raw(tenant_id: int, organization_id: int, **kw) -> TaxAssignment:
    """An assignment written PAST the service. Takes plain ids: a failed COMMIT rolls back and expires
    every ORM object in the session, so a fixture's ``world.tenant.id`` is not safe to read afterwards."""
    return TaxAssignment(tenant_id=tenant_id, organization_id=organization_id, **kw)


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


async def test_the_database_refuses_a_class_that_has_not_opted_in(worlds, db):
    _, acme, _ = worlds
    igst = await _tax(db, acme)
    tid, oid = acme.tenant.id, acme.organization.id
    db.add(_raw(tid, oid, owner_type_code="brand", owner_id=1, tax_component_id=igst.id))
    with pytest.raises(IntegrityError, match="fk_tax_assignments_owner_type"):
        await db.flush()
    await db.rollback()


async def test_the_database_refuses_an_owner_that_does_not_exist_at_commit(worlds, db):
    _, acme, _ = worlds
    igst = await _tax(db, acme)
    tid, oid = acme.tenant.id, acme.organization.id
    db.add(_raw(tid, oid, owner_type_code="category", owner_id=987654, tax_component_id=igst.id))
    await db.flush()                                                     # deferred: passes the flush…
    with pytest.raises(IntegrityError, match="category 987654 does not exist"):
        await db.commit()                                                # …and dies at COMMIT
    await db.rollback()


async def test_the_database_refuses_an_owner_from_another_organization(worlds, db):
    _, acme, _ = worlds
    category = await _category_row(db, acme)
    igst = await _tax(db, acme)
    tid, oid, cid = acme.tenant.id, acme.organization.id, category.id
    with tenant_scope(tid):
        second = Organization(org_code="ACME-2", legal_name="Acme Two", tenant_id=tid)
        db.add(second)
        await db.flush()
    second_id = second.id
    with tenant_scope(tid, second_id):
        db.add(_raw(tid, second_id, owner_type_code="category", owner_id=cid, tax_component_id=igst.id))
        await db.flush()
    with pytest.raises(IntegrityError, match=f"belongs to organization {oid}"):
        await db.commit()
    await db.rollback()


async def test_the_database_enforces_one_tax_per_context(worlds, db):
    _, acme, _ = worlds
    category = await _category_row(db, acme)
    a, b = await _tax(db, acme, "A", "1"), await _tax(db, acme, "B", "2")
    tid, oid, cid = acme.tenant.id, acme.organization.id, category.id
    with tenant_scope(tid, oid):
        db.add_all([_raw(tid, oid, owner_type_code="category", owner_id=cid, tax_component_id=a.id,
                         tax_specification="inter"),
                    _raw(tid, oid, owner_type_code="category", owner_id=cid, tax_component_id=b.id,
                         tax_specification="inter")])
        await db.flush()
    with pytest.raises(IntegrityError, match="already has a tax for this context"):
        await db.commit()
    await db.rollback()


async def test_the_database_refuses_an_exemption_on_a_class_that_does_not_take_one(worlds, db):
    _, acme, _ = worlds
    category = await _category_row(db, acme)
    tid, oid, cid = acme.tenant.id, acme.organization.id, category.id
    with tenant_scope(tid, oid):
        exemption = TaxExemption(tenant_id=tid, tax_exemption_code="X")
        db.add(exemption)
        await db.flush()
        db.add(_raw(tid, oid, owner_type_code="category", owner_id=cid, tax_exemption_id=exemption.id))
        await db.flush()
    with pytest.raises(IntegrityError, match="cannot carry a tax exemption"):
        await db.commit()
    await db.rollback()


async def test_the_same_tax_cannot_be_assigned_twice_even_in_the_any_context(worlds, db):
    """NULL = "any context": without NULLS NOT DISTINCT two of them would not collide."""
    _, acme, _ = worlds
    category = await _category_row(db, acme)
    igst = await _tax(db, acme)
    tid, oid, cid = acme.tenant.id, acme.organization.id, category.id
    with tenant_scope(tid, oid):
        db.add(_raw(tid, oid, owner_type_code="category", owner_id=cid, tax_component_id=igst.id))
        await db.flush()
        db.add(_raw(tid, oid, owner_type_code="category", owner_id=cid, tax_component_id=igst.id))
        with pytest.raises(IntegrityError, match="uq_tax_assignments_component"):
            await db.flush()
    await db.rollback()


async def test_a_disabled_class_takes_no_new_assignments(worlds, db):
    _, acme, _ = worlds
    category = await _category_row(db, acme)
    igst = await _tax(db, acme)
    await db.execute(text("UPDATE tax.taxable_entity_types SET is_enabled = false WHERE entity_type_code='category'"))
    try:
        with tenant_scope(acme.tenant.id, acme.organization.id):
            with pytest.raises(TaxRuleError, match="disabled"):
                await service.replace_assignments(db, "category", category.id, [AssignmentSpec(tax_component_id=igst.id)])
    finally:
        await db.execute(text("UPDATE tax.taxable_entity_types SET is_enabled = true WHERE entity_type_code='category'"))
        await db.commit()
    assert (await crud.get_policy(db, "category")).is_enabled is True


async def test_the_orphan_finder_reports_an_owner_that_was_hard_deleted(worlds, db):
    _, acme, _ = worlds
    category = await _category_row(db, acme)
    igst = await _tax(db, acme)
    with tenant_scope(acme.tenant.id, acme.organization.id):
        await service.replace_assignments(db, "category", category.id, [AssignmentSpec(tax_component_id=igst.id)])
    await db.commit()
    assert (await db.execute(text("SELECT * FROM tax.find_orphan_tax_assignments()"))).all() == []
    await db.execute(text("DELETE FROM core.categories WHERE id = :id"), {"id": category.id})
    orphans = (await db.execute(text("SELECT orphan_type, orphan_id FROM tax.find_orphan_tax_assignments()"))).all()
    assert [tuple(o) for o in orphans] == [("category", category.id)]


async def test_registering_a_class_is_idempotent_and_never_overwrites_a_rule(db):
    """The one call a module makes to opt in — safe to re-run, and an operator's tightened rule survives."""
    async def register(**rule):
        await db.run_sync(lambda session: register_taxable_entity_type(
            session.connection(), code="manufacturer", name="Manufacturer", target_schema="core",
            target_table="manufacturers", **rule))

    try:
        await register(allows_multiple=True)
        first = await db.scalar(select(TaxableEntityType).where(TaxableEntityType.entity_type_code == "manufacturer"))
        assert first.allows_multiple is True
        await register(allows_multiple=False, allows_exemption=True)                    # a later, different call
        await db.refresh(first)
        assert first.allows_multiple is True and first.allows_exemption is False          # the first rule stands
    finally:
        await db.rollback()
        await db.execute(text("DELETE FROM tax.taxable_entity_types WHERE entity_type_code = 'manufacturer'"))
        await db.commit()
