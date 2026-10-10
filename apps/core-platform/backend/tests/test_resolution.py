"""The resolution engine — "what applies here?" for taxes and accounts, along owner chains.

    hermetic   registry validation (unknown role / filter / expander die at registration);
    database   the account and tax chains end to end — explicit owner → item → item's categories
               (the ``categories`` expander, a real ``core.categorizables`` row) → contact →
               organization default; fail-closed on an unusable answer; ``skip`` through a
               per-organization policy override; the trace; and the batching guarantee — the
               statement count is the same for 1 and 50 subjects;
    API        ``/api/resolution``: facets, effective policy + layer, override, reset, resolve.

``brand`` stands in for the owner classes that do not exist yet (item, contact): the fixture
opts it in to taxes (several + exemption) and to account purposes, then removes the policy
rows again — they are seeded data the suite never truncates.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import event, text

from app.database.tenancy import tenant_scope
from app.modules.accounting.assignment import AccountAssignment
from app.modules.accounting.model import Account
from app.modules.accounting.registration import register_account_owner_type
from app.modules.brands.model import Brand
from app.modules.resolution import Outcome, OwnerRef, Policy, Step, Subject, resolution_registry, resolve_many
from app.modules.resolution.engine import ResolutionError
from app.modules.taxes import assignment_service as tax_service
from app.modules.taxes.assignment_service import AssignmentSpec
from app.modules.taxes.component import TaxComponent
from app.modules.taxes.exemption import TaxExemption
from app.modules.taxes.org_tax import OrganizationTaxComponent
from app.modules.taxes.preference import OrgDefaultTaxPreference
from app.modules.taxes.registration import register_taxable_entity_type

# ── hermetic: the registry refuses what the engine could not run ────────────


def test_every_registered_policy_is_valid():
    resolution_registry.autodiscover()
    assert {f.code for f in resolution_registry.facets()} == {"tax", "account"}
    for policy in resolution_registry.policies():
        assert resolution_registry.problems_of(policy) == [], (policy.facet, policy.subject)


def test_a_policy_with_an_unknown_role_filter_or_expander_is_refused():
    base = resolution_registry.policy("tax", "sales_line")
    problems = resolution_registry.problems_of(base, [Step("nope"), Step("item", filter="not_a_filter")])
    assert any("unknown role 'nope'" in p for p in problems)
    assert any("unknown filter 'not_a_filter'" in p for p in problems)
    duplicate = resolution_registry.problems_of(base, [Step("item"), Step("item")])
    assert any("repeats role" in p for p in duplicate)
    from app.modules.resolution import Expansion

    bad = Policy(facet="account", subject="x", roles=frozenset({"item"}), steps=(Step("item"),),
                 expansions=(Expansion(role="cat", from_role="item", expander="missing"),))
    assert any("unregistered expander 'missing'" in p for p in resolution_registry.problems_of(bad))


def test_the_accountant_approved_precedence_is_the_default():
    tax = [s.as_dict() for s in resolution_registry.policy("tax", "sales_line").steps]
    assert [(s["role"], s["filter"]) for s in tax] == [
        ("line", None), ("contact", "exemption_only"), ("item", None), ("item_category", None),
        ("contact", "taxes_only")]
    account = [s.role for s in resolution_registry.policy("account", "sales_line").steps]
    assert account == ["line", "item", "item_category", "contact"]          # the item beats the contact


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def stand_ins(db):
    """``brand`` (item / contact stand-in) and ``category`` may carry accounts; brand may carry taxes."""
    def register(session):
        conn = session.connection()
        register_taxable_entity_type(conn, code="brand", name="Brand", target_schema="core", target_table="brands",
                                     allows_multiple=True, allows_exemption=True)
        register_account_owner_type(conn, code="brand", name="Brand", target_schema="core", target_table="brands",
                                    purposes={"sales": True, "purchase": True, "receivable": True})
        register_account_owner_type(conn, code="category", name="Category", target_schema="core",
                                    target_table="categories", purposes={"sales": True})

    await db.run_sync(register)
    await db.commit()
    yield
    await db.rollback()
    await db.execute(text("DELETE FROM accounting.account_assignments WHERE owner_type_code IN ('brand','category')"))
    await db.execute(text("DELETE FROM accounting.account_purpose_policies WHERE entity_type_code IN ('brand','category')"))
    await db.execute(text("DELETE FROM tax.tax_assignments WHERE owner_type_code = 'brand'"))
    await db.execute(text("DELETE FROM tax.taxable_entity_types WHERE entity_type_code = 'brand'"))
    await db.commit()


async def _brand(db, world, name) -> Brand:
    with tenant_scope(world.tenant.id, world.organization.id):
        brand = Brand(name=name, organization_id=world.organization.id, owner_type="organization",
                      owner_id=world.organization.id)
        db.add(brand)
        await db.flush()
    return brand


async def _account(db, world, name, account_type, status="active") -> Account:
    with tenant_scope(world.tenant.id, world.organization.id):
        account = Account(organization_id=world.organization.id, account_name=name, account_type=account_type,
                          status=status)
        db.add(account)
        await db.flush()
    return account


async def _assign(db, world, owner_type, owner_id, purpose, account) -> None:
    with tenant_scope(world.tenant.id, world.organization.id):
        db.add(AccountAssignment(organization_id=world.organization.id, owner_type_code=owner_type,
                                 owner_id=owner_id, purpose_code=purpose, account_id=account.id))
        await db.flush()


async def _item_in_a_category(client, headers, db, world):
    """A brand standing in for an item, placed in a category through the real categorizables API."""
    taxonomy = (await client.post("/api/taxonomies", json={"slug": "goods", "name": "Goods"},
                                  headers=headers)).json()["data"]
    put = await client.put(f"/api/taxonomies/{taxonomy['uuid']}/entity-types", headers=headers,
                           json={"entity_types": [{"entity_type_code": "brand", "allows_multiple": None}]})
    assert put.status_code == 200, put.text
    category = (await client.post("/api/categories", json={"taxonomy_id": taxonomy["id"], "name": "OTC"},
                                  headers=headers)).json()["data"]
    item = await _brand(db, world, "Paracetamol")
    linked = await client.post("/api/categorizables", headers=headers, json={
        "category_id": category["id"], "categorizable_type": "brand", "categorizable_id": item.id})
    assert linked.status_code == 201, linked.text
    return item, category


def _subject(world, item, contact, **context) -> Subject:
    return Subject(roles={"item": OwnerRef("brand", item.id), "contact": OwnerRef("brand", contact.id)},
                   organization_id=world.organization.id, context=context)


class _Statements:
    """Counts the SQL statements a block sends."""

    def __init__(self, db) -> None:
        self.db, self.count = db, 0

    def _hit(self, *_args, **_kwargs) -> None:
        self.count += 1

    async def __aenter__(self):
        self.conn = (await self.db.connection()).sync_connection
        event.listen(self.conn, "before_cursor_execute", self._hit)
        return self

    async def __aexit__(self, *exc):
        event.remove(self.conn, "before_cursor_execute", self._hit)


# ── accounts along the chain ──────────────────────────────────────────────────

async def test_the_income_account_walks_item_then_its_categories_then_the_organization(worlds, db, stand_ins):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    item, category = await _item_in_a_category(client, headers, db, acme)
    contact = await _brand(db, acme, "Retailer")
    org_sales = await _account(db, acme, "Sales", "income")
    otc_sales = await _account(db, acme, "OTC Sales", "income")
    para_sales = await _account(db, acme, "Paracetamol Sales", "income")
    await _assign(db, acme, "organization", acme.organization.id, "sales", org_sales)

    async def resolve(**kw):
        with tenant_scope(acme.tenant.id, acme.organization.id):
            (result,) = await resolve_many(db, "account", "sales_line",
                                           [_subject(acme, item, contact, purpose="sales")], **kw)
        return result

    result = await resolve()
    assert (result.outcome, result.via, result.values[0].account_id) == (
        Outcome.ORGANIZATION_DEFAULT, "organization", org_sales.id)

    await _assign(db, acme, "category", category["id"], "sales", otc_sales)
    result = await resolve()
    assert (result.via, result.owner, result.values[0].account_id) == (
        "item_category", OwnerRef("category", category["id"]), otc_sales.id)

    await _assign(db, acme, "brand", item.id, "sales", para_sales)
    result = await resolve(explain=True)
    assert (result.outcome, result.via, result.values[0].account_id) == (Outcome.ANSWERED, "item", para_sales.id)
    assert [(t.role, t.result) for t in result.trace] == [("line", "no_owner"), ("item", "answered")]

    # fail closed: the item's account went inactive — never a silent fall-through to the category
    with tenant_scope(acme.tenant.id, acme.organization.id):
        para_sales.status = "inactive"
        await db.flush()
    result = await resolve()
    assert (result.outcome, result.via, result.reason) == (Outcome.UNUSABLE, "item", "account_inactive")

    # … unless the organization's policy says the item layer is optional
    put = await client.put("/api/resolution/policies/account/sales_line", headers=headers, json={
        "steps": [{"role": "line"}, {"role": "item", "on_unusable": "skip"}, {"role": "item_category"},
                  {"role": "contact"}], "notes": "accountant: skip inactive item accounts"})
    assert put.status_code == 200, put.text
    assert put.json()["data"]["layer"] == "organization"
    result = await resolve(explain=True)
    assert (result.via, result.values[0].account_id) == ("item_category", otc_sales.id)
    assert ("item", "skipped:account_inactive") in [(t.role, t.result) for t in result.trace]


async def test_the_contact_answers_after_the_item_and_a_purpose_never_leaks(worlds, db, stand_ins):
    _, acme, _ = worlds
    item, contact = await _brand(db, acme, "Item"), await _brand(db, acme, "Key Account")
    key_sales = await _account(db, acme, "Key Account Sales", "income")
    debtors = await _account(db, acme, "Debtors", "accounts_receivable")
    await _assign(db, acme, "brand", contact.id, "sales", key_sales)
    await _assign(db, acme, "organization", acme.organization.id, "receivable", debtors)
    with tenant_scope(acme.tenant.id, acme.organization.id):
        sales, receivable, purchase = await resolve_many(db, "account", "sales_line", [
            _subject(acme, item, contact, purpose="sales"), _subject(acme, item, contact, purpose="receivable"),
            _subject(acme, item, contact, purpose="purchase")])
    assert (sales.via, sales.values[0].account_id) == ("contact", key_sales.id)
    assert (receivable.outcome, receivable.values[0].account_id) == (Outcome.ORGANIZATION_DEFAULT, debtors.id)
    assert purchase.outcome is Outcome.NONE                       # nobody answers: the caller decides


async def test_resolution_is_batched_the_statement_count_does_not_grow_with_subjects(worlds, db, stand_ins):
    client, acme, _ = worlds
    item, category = await _item_in_a_category(client, acme.auth(acme.admin), db, acme)
    contact = await _brand(db, acme, "Retailer")
    sales = await _account(db, acme, "Sales", "income")
    await _assign(db, acme, "category", category["id"], "sales", sales)
    counts = []
    for size in (1, 50):
        subjects = [_subject(acme, item, contact, purpose="sales") for _ in range(size)]
        with tenant_scope(acme.tenant.id, acme.organization.id):
            async with _Statements(db) as statements:
                results = await resolve_many(db, "account", "sales_line", subjects)
        assert {r.values[0].account_id for r in results} == {sales.id}
        counts.append(statements.count)
    # effective policy (1) + the categories expansion (1) + the account facet load (1)
    assert counts == [3, 3]


async def test_an_unknown_role_is_a_loud_caller_error(worlds, db, stand_ins):
    _, acme, _ = worlds
    with tenant_scope(acme.tenant.id, acme.organization.id), pytest.raises(ResolutionError, match="unknown role"):
        await resolve_many(db, "account", "document_party", [Subject(
            roles={"warehouse": OwnerRef("brand", 1)}, organization_id=acme.organization.id,
            context={"purpose": "receivable"})])


# ── taxes along the chain ─────────────────────────────────────────────────────

async def test_a_customers_exemption_beats_the_items_tax_then_the_items_tax_then_the_default(
        worlds, db, stand_ins):
    _, acme, _ = worlds
    item, contact = await _brand(db, acme, "Item"), await _brand(db, acme, "SEZ Unit")
    with tenant_scope(acme.tenant.id, acme.organization.id):
        igst = TaxComponent(tenant_id=acme.tenant.id, tax_name="IGST12", tax_percentage=Decimal("12"),
                            tax_type="tax")
        cgst = TaxComponent(tenant_id=acme.tenant.id, tax_name="GST5", tax_percentage=Decimal("5"), tax_type="tax")
        default = TaxComponent(tenant_id=acme.tenant.id, tax_name="IGST18", tax_percentage=Decimal("18"),
                               tax_type="tax")
        sez = TaxExemption(tenant_id=acme.tenant.id, tax_exemption_code="SEZ", exemption_type="exempt")
        db.add_all([igst, cgst, default, sez])
        await db.flush()
        for component in (igst, cgst, default):
            db.add(OrganizationTaxComponent(tenant_id=acme.tenant.id, organization_id=acme.organization.id,
                                            tax_component_id=component.id))
        db.add(OrgDefaultTaxPreference(tenant_id=acme.tenant.id, organization_id=acme.organization.id,
                                       tax_specification="inter", default_tax_id=default.id))
        await db.flush()
        await tax_service.replace_assignments(db, "brand", item.id, [
            AssignmentSpec(tax_component_id=igst.id, tax_specification="inter")])
        await tax_service.replace_assignments(db, "brand", contact.id, [
            AssignmentSpec(tax_exemption_id=sez.id), AssignmentSpec(tax_component_id=cgst.id)])

        async def resolve():
            (result,) = await resolve_many(db, "tax", "sales_line", [
                _subject(acme, item, contact, specification="inter", transaction_type="sales")], explain=True)
            return result

        exempt = await resolve()
        assert (exempt.via, exempt.values[0].tax_exemption_id) == ("contact", sez.id)

        await tax_service.replace_assignments(db, "brand", contact.id, [AssignmentSpec(tax_component_id=cgst.id)])
        by_item = await resolve()
        assert (by_item.via, [a.tax_component_id for a in by_item.values]) == ("item", [igst.id])

        await tax_service.replace_assignments(db, "brand", item.id, [])
        by_contact = await resolve()                              # the contact's default tax, after the item
        assert (by_contact.via, [a.tax_component_id for a in by_contact.values]) == ("contact", [cgst.id])
        assert [t.result for t in by_contact.trace if t.role == "contact"] == ["filtered", "answered"]

        await tax_service.replace_assignments(db, "brand", contact.id, [])
        fallback = await resolve()
        assert (fallback.outcome, [c.id for c in fallback.values]) == (Outcome.ORGANIZATION_DEFAULT, [default.id])

        # the legacy chain API rides the same engine and keeps its contract
        legacy = await tax_service.resolve_taxes(db, [("brand", item.id)], specification="inter",
                                                 organization_id=acme.organization.id)
        assert legacy.via == "organization_default" and [c.tax_name for c in legacy.components] == ["IGST18"]


# ── API ───────────────────────────────────────────────────────────────────────

async def test_the_policy_api_shows_layers_validates_and_resets(worlds, db, stand_ins):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    facets = (await client.get("/api/resolution/facets", headers=headers)).json()["data"]
    assert {f["code"] for f in facets} == {"tax", "account"}
    url = "/api/resolution/policies/tax/sales_line"
    assert (await client.get(url, headers=headers)).json()["data"]["layer"] == "code"

    bad = await client.put(url, headers=headers, json={"steps": [{"role": "warehouse"}]})
    assert bad.status_code == 422 and "unknown role" in bad.json()["msg"]

    tenant = await client.put(url + "?scope=tenant", headers=headers,
                              json={"steps": [{"role": "item"}], "use_organization_default": False})
    assert tenant.json()["data"]["layer"] == "tenant"
    org = await client.put(url, headers=headers, json={"steps": [{"role": "contact", "filter": "exemption_only"},
                                                                 {"role": "item"}]})
    assert org.json()["data"]["layer"] == "organization"
    assert (await client.get(url, headers=headers)).json()["data"]["layer"] == "organization"
    reset = await client.delete(url, headers=headers)
    assert reset.json()["data"]["layer"] == "tenant" and reset.json()["data"]["use_organization_default"] is False
    assert (await client.delete(url + "?scope=tenant", headers=headers)).json()["data"]["layer"] == "code"
    assert (await client.delete(url, headers=headers)).status_code == 404

    # a member may read but not change policies
    member = acme.auth(acme.member)
    assert (await client.get(url, headers=member)).status_code == 200
    assert (await client.put(url, headers=member, json={"steps": []})).status_code == 403


async def test_the_resolve_endpoint_describes_the_answer(worlds, db, stand_ins):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    contact = await _brand(db, acme, "Retailer")
    debtors = await _account(db, acme, "Debtors", "accounts_receivable")
    await _assign(db, acme, "organization", acme.organization.id, "receivable", debtors)
    response = await client.post("/api/resolution/account/document_party/resolve", headers=headers, json={
        "subjects": [{"roles": {"contact": {"type": "brand", "id": contact.id}}, "context": {"purpose": "receivable"}}],
        "explain": True})
    assert response.status_code == 200, response.text
    (answer,) = response.json()["data"]
    assert answer["outcome"] == "organization_default" and answer["values"][0]["display_name"] == "Debtors"
    assert [t["result"] for t in answer["trace"]] == ["no_candidates", "answered"]
    invalid = await client.post("/api/resolution/account/document_party/resolve", headers=headers,
                                json={"subjects": [{"roles": {}, "context": {}}]})
    assert invalid.status_code == 422                                   # purpose is required
