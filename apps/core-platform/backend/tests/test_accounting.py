"""Accounting — chart of accounts, account assignments, Zoho chart → tax links.

Three layers, tested as three layers (docs/implementation-plan/accounts-module.md §12.3):

  * hermetic — the 46-type seed against the tenant's own response and Zoho's documented list,
    the purposes, the translator, the owned-field set, the strategy rule;
  * database — the triggers are authoritative (normal side, depth, cycles, the delete guard,
    the deferred assignment integrity), asserted by writing PAST the service;
  * service + API — the clean 4xx a caller gets, and the Zoho tax → account link through the
    crosswalk, pending until the chart syncs, linked by the reconcile lane.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database.tenancy import tenant_scope
from app.modules.accounting import assignment_service as assignments
from app.modules.accounting.assignment import AccountAssignment
from app.modules.accounting.errors import AccountRuleError
from app.modules.accounting.model import Account
from app.modules.accounting.seed import seed_organization_defaults
from app.modules.accounting.seed_data import account_type_rows, purpose_rows
from app.modules.accounting.zoho.spec import CHART_OF_ACCOUNTS_TRANSLATOR, ZOHO_OWNED_ACCOUNT_FIELDS
from app.modules.organizations.model import Organization
from app.modules.sync.crosswalk import upsert_record
from app.modules.sync.models import LinkState, PendingReference
from app.modules.sync.reconcile import drain_pending_references
from app.modules.sync.translation import PayloadShape
from app.modules.taxes.component import TaxComponent

_REPO = Path(__file__).resolve().parents[4]
_SAMPLE = _REPO / "docs" / "zoho-docs-md" / "samples" / "accounts" / "account-types.json"
_COA_DOC = _REPO / "docs" / "zoho-docs-md" / "chart-of-accounts.md"


# ── hermetic: the seed ────────────────────────────────────────────────────────

def test_the_seed_carries_46_types_and_matches_the_tenants_own_response_field_by_field():
    rows = {row["code"]: row for row in account_type_rows()}
    assert len(rows) == 46
    observed = json.loads(_SAMPLE.read_text(encoding="utf-8"))["account_types"]
    assert len(observed) == 26
    for item in observed:
        row = rows[item["account_type"]]
        assert row["zoho_id"] == item["id"], item["account_type"]
        assert row["name"] == item["account_type_formatted"]
        assert row["account_group"] == item["account_group"]
        assert row["is_sub_account_allowed"] is item["is_sub_account_allowed"]
        assert row["can_show_opening_balance"] is (str(item["can_show_opening_balance"]) == "true")
        assert row["can_enable_in_ze"] is item["can_enable_in_ze"]
        assert row["asset_type"] == item.get("asset_type")
    # a type the tenant never reported is stored as UNKNOWN, never guessed
    assert {code for code, row in rows.items() if row["zoho_id"] is None} == set(rows) - {
        i["account_type"] for i in observed}
    for code, row in rows.items():
        if row["zoho_id"] is None:
            assert row["is_sub_account_allowed"] is None and row["can_enable_in_ze"] is None, code


def test_every_type_zoho_documents_is_seeded_and_flagged_documented():
    documented = re.search(r"Allowed Values: (.+?)\.", _COA_DOC.read_text(encoding="utf-8")).group(1)
    codes = set(re.findall(r"`([a-z_]+)`", documented))
    assert len(codes) == 38
    rows = {row["code"]: row for row in account_type_rows()}
    assert codes <= set(rows)
    assert {code for code, row in rows.items() if row["is_documented"]} == codes


def test_the_normal_side_follows_the_group():
    for row in account_type_rows():
        assert row["default_normal_balance_is_debit"] is (row["account_group"] in ("asset", "expense")), row["code"]


def test_purposes_name_real_groups_and_types():
    groups = {"asset", "liability", "equity", "income", "expense"}
    types = {row["code"]: row["account_group"] for row in account_type_rows()}
    for purpose in purpose_rows():
        assert set(purpose["allowed_groups"]) <= groups, purpose["code"]
        for account_type in purpose["allowed_types"] or []:
            assert types[account_type] in purpose["allowed_groups"], (purpose["code"], account_type)


# ── hermetic: the translator ──────────────────────────────────────────────────

def test_the_translator_absorbs_zohos_quirks_and_never_invents_a_value():
    decoded = CHART_OF_ACCOUNTS_TRANSLATOR.decode({
        "account_id": "460000000038079", "account_name": "Notes Payable", "account_code": "",
        "account_type": "long_term_liability", "is_active": "true", "is_system_account": False,
        "can_show_in_ze": "false", "current_balance": 12.5,
    }, shape=PayloadShape.INDEX).values
    assert decoded == {"account_name": "Notes Payable", "account_code": None, "account_type": "long_term_liability",
                       "status": "active", "is_system_account": False, "is_expense_claim_enabled": False}
    assert "description" not in decoded and "placeholder" not in decoded      # absent keys are skipped
    assert CHART_OF_ACCOUNTS_TRANSLATOR.decode({"is_active": False}).values == {"status": "inactive"}


def test_zoho_owns_what_it_feeds_plus_the_parent_and_the_currency():
    assert {"account_name", "account_code", "account_type", "status", "parent_id", "currency_id"} <= \
        ZOHO_OWNED_ACCOUNT_FIELDS
    assert "is_contra" not in ZOHO_OWNED_ACCOUNT_FIELDS                      # ours, Zoho has no such field


def test_every_registered_zoho_module_declares_its_strategy():
    """The platform default is FULL; no real module may rely on a default to pick its strategy."""
    from app.modules.zoho.sync.registry import sync_registry

    for definition in sync_registry.all():
        spec_file = Path(inspect.getsourcefile(inspect.getmodule(definition.model))).parent / "zoho" / "spec.py"
        spec_source = spec_file.read_text(encoding="utf-8")
        configs = spec_source.count("resolve_module_config(")
        assert configs and spec_source.count("strategy=") >= configs, definition.name


# ── fixtures ──────────────────────────────────────────────────────────────────

async def _account(db, world, name, account_type, *, code=None, parent=None, status="active", zoho_id=None,
                   is_contra=False) -> Account:
    with tenant_scope(world.tenant.id, world.organization.id):
        account = Account(organization_id=world.organization.id, account_name=name, account_type=account_type,
                          account_code=code, parent_id=parent.id if parent else None, status=status,
                          zoho_id=zoho_id, is_contra=is_contra)
        db.add(account)
        await db.flush()
        await db.refresh(account)
    return account


# ── database: derived fields and structure ────────────────────────────────────

async def test_the_database_derives_the_normal_side_and_the_depth(worlds, db):
    _, acme, _ = worlds
    cash = await _account(db, acme, "Cash", "cash")
    loan = await _account(db, acme, "Bank Loan", "long_term_liability")
    sales = await _account(db, acme, "Sales", "income")
    depreciation = await _account(db, acme, "Accumulated Depreciation", "fixed_asset", is_contra=True)
    assert (cash.normal_balance_is_debit, loan.normal_balance_is_debit, sales.normal_balance_is_debit) == (
        True, False, False)
    assert depreciation.normal_balance_is_debit is False                     # a contra asset is credit-normal

    retail = await _account(db, acme, "Retail", "income", parent=sales)
    online = await _account(db, acme, "Online", "income", parent=retail)
    assert (sales.depth, retail.depth, online.depth) == (0, 1, 2)

    # re-parenting cascades the subtree's depth AND bumps its row_version (a Core update must)
    other = await _account(db, acme, "Other Income", "other_income")
    deeper = await _account(db, acme, "Other Income - Misc", "other_income", parent=other)
    version = online.row_version
    with tenant_scope(acme.tenant.id, acme.organization.id):
        retail.parent_id = deeper.id
        await db.flush()
    await db.refresh(online)
    assert online.depth == 3 and online.row_version == version + 1
    await db.execute(text("UPDATE accounting.accounts SET parent_id = NULL WHERE id = :id"), {"id": retail.id})
    await db.refresh(online)
    assert online.depth == 1


async def test_a_cycle_is_refused_by_the_database(worlds, db):
    _, acme, _ = worlds
    root = await _account(db, acme, "Expenses", "expense")
    child = await _account(db, acme, "Travel", "expense", parent=root)
    await db.commit()
    with pytest.raises(IntegrityError, match="own ancestor"):
        await db.execute(text("UPDATE accounting.accounts SET parent_id = :c WHERE id = :r"),
                         {"c": child.id, "r": root.id})
    await db.rollback()


async def test_a_parent_from_another_tenant_or_organization_is_structurally_impossible(worlds, db):
    _, acme, globex = worlds
    theirs = await _account(db, globex, "Globex Sales", "income")
    await db.commit()
    with pytest.raises(IntegrityError, match="fk_accounts_parent_scope"):
        with tenant_scope(acme.tenant.id, acme.organization.id):
            db.add(Account(organization_id=acme.organization.id, account_name="Mine", account_type="income",
                           parent_id=theirs.id))
            await db.flush()
    await db.rollback()


async def test_an_unknown_type_fails_and_a_blank_code_is_refused(worlds, db):
    _, acme, _ = worlds
    tid, oid = acme.tenant.id, acme.organization.id     # a failed flush expires every fixture object
    for kwargs, match in (({"account_type": "not_a_type"}, "unknown account type"),
                          ({"account_type": "cash", "account_code": "  "}, "ck_accounts_code_not_blank")):
        with tenant_scope(tid, oid), pytest.raises(IntegrityError, match=match):
            db.add(Account(organization_id=oid, account_name="X", **kwargs))
            await db.flush()
        await db.rollback()


# ── API: the chart ────────────────────────────────────────────────────────────

async def test_the_chart_api_creates_lists_nests_and_filters_by_picker(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    types = (await client.get("/api/accounting/account-types", headers=headers)).json()["data"]
    assert len(types) == 46 and types[0]["code"] == "other_asset"

    sales = (await client.post("/api/accounting/accounts", headers=headers, json={
        "account_name": "Sales", "account_code": "4000", "account_type": "income"})).json()["data"]
    assert sales["display_name"] == "4000 - Sales" and sales["normal_balance_is_debit"] is False
    assert sales["account_group"] == "income"
    child = await client.post("/api/accounting/accounts", headers=headers, json={
        "account_name": "Retail Sales", "account_type": "income", "parent_id": sales["id"]})
    assert child.status_code == 201, child.text
    await client.post("/api/accounting/accounts", headers=headers, json={
        "account_name": "Inventory Asset", "account_type": "stock"})
    await client.post("/api/accounting/accounts", headers=headers, json={
        "account_name": "Purchases", "account_type": "cost_of_goods_sold"})

    def names(response):
        return sorted(row["account_name"] for row in response.json()["data"])

    assert names(await client.get("/api/accounting/accounts?usage=sales", headers=headers)) == [
        "Retail Sales", "Sales"]
    assert names(await client.get("/api/accounting/accounts?usage=purchase", headers=headers)) == ["Purchases"]
    assert names(await client.get("/api/accounting/accounts?usage=inventory", headers=headers)) == [
        "Inventory Asset"]
    assert names(await client.get("/api/accounting/accounts?q=retail", headers=headers)) == ["Retail Sales"]
    tree = (await client.get("/api/accounting/accounts?tree=true&group=income", headers=headers)).json()["data"]
    assert [(n["account_name"], [c["account_name"] for c in n["children"]]) for n in tree] == [
        ("Sales", ["Retail Sales"])]
    detail = (await client.get(f"/api/accounting/accounts/{sales['uuid']}", headers=headers)).json()["data"]
    assert detail["has_children"] is True and detail["assignment_count"] == 0

    # globex cannot see acme's chart
    globex_headers = worlds[2].auth(worlds[2].admin)
    assert (await client.get("/api/accounting/accounts", headers=globex_headers)).json()["data"] == []


async def test_local_writes_follow_zohos_sub_account_rules(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    bank = await _account(db, acme, "HDFC", "bank")
    expense = await _account(db, acme, "Expenses", "expense")
    under_bank = await client.post("/api/accounting/accounts", headers=headers, json={
        "account_name": "Sub", "account_type": "bank", "parent_id": bank.id})
    assert under_bank.status_code == 422 and under_bank.json()["data"]["rule"] == "sub_account_not_allowed"
    cross_group = await client.post("/api/accounting/accounts", headers=headers, json={
        "account_name": "Wrong", "account_type": "income", "parent_id": expense.id})
    assert cross_group.status_code == 422 and cross_group.json()["data"]["rule"] == "parent_group_mismatch"


async def test_a_zoho_mastered_chart_refuses_local_creation_and_zoho_owned_edits(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    linked = await _account(db, acme, "Sales", "income", zoho_id="460000000038079")
    with tenant_scope(acme.tenant.id):
        organization = await db.get(Organization, acme.organization.id)
        organization.zoho_id = "10234695"
        await db.flush()
    created = await client.post("/api/accounting/accounts", headers=headers, json={
        "account_name": "Local", "account_type": "income"})
    assert created.status_code == 422 and created.json()["code"] == "zoho_mastered_chart"
    renamed = await client.patch(f"/api/accounting/accounts/{linked.uuid}", headers=headers,
                                 json={"account_name": "Revenue"})
    assert renamed.status_code == 422 and renamed.json()["code"] == "zoho_owned_field"
    ours = await client.patch(f"/api/accounting/accounts/{linked.uuid}", headers=headers, json={"is_contra": True})
    assert ours.status_code == 200 and ours.json()["data"]["normal_balance_is_debit"] is True
    deactivated = await client.post(f"/api/accounting/accounts/{linked.uuid}/deactivate", headers=headers)
    assert deactivated.status_code == 422


async def test_an_account_in_use_is_not_deleted(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    receivable = await _account(db, acme, "Debtors", "accounts_receivable")
    put = await client.put(f"/api/accounting/assignments/organization/{acme.organization.id}", headers=headers,
                           json={"items": [{"purpose": "receivable", "account": str(receivable.uuid)}]})
    assert put.status_code == 200, put.text
    refused = await client.delete(f"/api/accounting/accounts/{receivable.uuid}?reason=cleanup", headers=headers)
    assert refused.status_code == 409 and refused.json()["data"] == {"children": 0, "assignments": 1}
    # and not even a raw soft delete gets past the database
    await db.commit()
    with pytest.raises(IntegrityError, match="still assigned"):
        await db.execute(text("UPDATE accounting.accounts SET deleted_at = now() WHERE id = :id"),
                         {"id": receivable.id})
    await db.rollback()


# ── assignments ───────────────────────────────────────────────────────────────

async def test_organization_defaults_are_judged_by_the_purpose(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    sales = await _account(db, acme, "Sales", "income")
    debtors = await _account(db, acme, "Debtors", "accounts_receivable")
    inactive = await _account(db, acme, "Old Sales", "income", status="inactive")
    url = f"/api/accounting/assignments/organization/{acme.organization.id}"

    wrong_group = await client.put(url, headers=headers, json={"items": [
        {"purpose": "receivable", "account": str(sales.uuid)}]})
    assert wrong_group.status_code == 422 and wrong_group.json()["data"]["rule"] == "account_group_not_allowed"
    wrong_type = await client.put(url, headers=headers, json={"items": [
        {"purpose": "inventory_asset", "account": str(debtors.uuid)}]})
    assert wrong_type.status_code == 422 and wrong_type.json()["data"]["rule"] == "account_type_not_allowed"
    not_active = await client.put(url, headers=headers, json={"items": [
        {"purpose": "sales", "account": str(inactive.uuid)}]})
    assert not_active.status_code == 422 and "inactive" in not_active.json()["msg"]
    not_per_currency = await client.put(url, headers=headers, json={"items": [
        {"purpose": "sales", "account": str(sales.uuid), "currency_id": 1}]})
    assert not_per_currency.status_code == 422

    ok = await client.put(url, headers=headers, json={"items": [
        {"purpose": "sales", "account": str(sales.uuid)}, {"purpose": "receivable", "account": str(debtors.uuid)}]})
    assert ok.status_code == 200, ok.text
    assert sorted((r["purpose_code"], r["account"]["account_name"]) for r in ok.json()["data"]) == [
        ("receivable", "Debtors"), ("sales", "Sales")]
    # replacing is a diff: dropping a purpose soft-deletes it
    again = await client.put(url, headers=headers, json={"items": [{"purpose": "sales", "account": str(sales.uuid)}]})
    assert [r["purpose_code"] for r in again.json()["data"]] == ["sales"]
    # a class that has not opted in to a purpose is refused
    category_try = await client.put(f"/api/accounting/assignments/tax_component/{debtors.id}", headers=headers,
                                    json={"items": [{"purpose": "receivable", "account": str(debtors.uuid)}]})
    assert category_try.status_code in (404, 422)


async def test_a_source_slot_cannot_be_taken_locally(worlds, db):
    _, acme, _ = worlds
    sales = await _account(db, acme, "Sales", "income")
    with tenant_scope(acme.tenant.id, acme.organization.id):
        await assignments.put_assignments(db, "organization", acme.organization.id,
                                          [assignments.AccountSpec("sales", account_id=sales.id)],
                                          source_system="zoho")
        from app.common.exception.errors import ConflictError

        with pytest.raises(ConflictError, match="maintained by zoho"):
            await assignments.put_assignments(db, "organization", acme.organization.id,
                                              [assignments.AccountSpec("sales", account_id=sales.id)])


async def test_the_database_judges_local_rows_and_trusts_a_sources(worlds, db):
    _, acme, _ = worlds
    sales = await _account(db, acme, "Sales", "income")
    await db.commit()
    tid, oid, sid = acme.tenant.id, acme.organization.id, sales.id
    other_org = worlds[2].organization.id
    # a LOCAL receivable pointing at an income account is refused at COMMIT …
    db.add(AccountAssignment(tenant_id=tid, organization_id=oid, owner_type_code="organization", owner_id=oid,
                             purpose_code="receivable", account_id=sid))
    with pytest.raises(IntegrityError, match="does not fit purpose"):
        await db.commit()
    await db.rollback()
    # … the same link fed by Zoho is Zoho's data: trusted (the service logs the misfit)
    db.add(AccountAssignment(tenant_id=tid, organization_id=oid, owner_type_code="organization", owner_id=oid,
                             purpose_code="receivable", account_id=sid, source_system="zoho"))
    await db.commit()
    # an owner in another organization is refused whatever the source
    db.add(AccountAssignment(tenant_id=tid, organization_id=oid, owner_type_code="organization",
                             owner_id=other_org, purpose_code="sales", account_id=sid,
                             source_system="zoho"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_zoho_tax_accounts_wait_for_the_chart_then_link(worlds, db):
    """A synced tax names its ledger accounts by Zoho id → pending until the chart arrives → linked."""
    from app.modules.taxes.zoho.hooks import link_tax_accounts

    _, acme, _ = worlds
    with tenant_scope(acme.tenant.id, acme.organization.id):
        tax = TaxComponent(tenant_id=acme.tenant.id, tax_name="IGST18", tax_percentage=18, tax_type="tax")
        db.add(tax)
        await db.flush()
        await link_tax_accounts(tax, {"tax_id": "z-tax", "tax_account_id": "z-out", "purchase_tax_account_id": ""})
        rows = await assignments.list_assignments(db, "tax_component", tax.id)
    assert [(r.purpose_code, r.is_pending, r.external_ref, r.organization_id) for r in rows] == [
        ("output_tax", True, "z-out", acme.organization.id)]
    waiter = await db.scalar(select(PendingReference).where(PendingReference.waiting_id == rows[0].id))
    assert (waiter.module, waiter.waiting_table, waiter.waiting_column) == (
        "chart_of_accounts", "accounting.account_assignments", "account_id")
    await db.commit()

    # the chart syncs; the generic reconcile lane links the waiter
    output = await _account(db, acme, "Output IGST", "other_current_liability", zoho_id="z-out")
    await upsert_record(db, tenant_id=acme.tenant.id, source_system="zoho", module="chart_of_accounts",
                        external_id="z-out", values={"entity_table": "accounting.accounts",
                                                     "entity_id": output.id, "link_state": LinkState.LINKED})
    assert (await drain_pending_references(db, tenant_id=acme.tenant.id)).linked == 1
    await db.commit()
    with tenant_scope(acme.tenant.id, acme.organization.id):
        (row,) = await assignments.list_assignments(db, "tax_component", tax.id)
        await db.refresh(row)
        assert row.account_id == output.id and not row.is_pending

        # a later sync that names the account again resolves it directly — no new waiter
        await link_tax_accounts(tax, {"tax_account_id": "z-out"})
        (row,) = await assignments.list_assignments(db, "tax_component", tax.id)
        assert row.account_id == output.id
        # a payload that does not carry the account attributes changes nothing
        await link_tax_accounts(tax, {"tax_name": "IGST18"})
        assert len(await assignments.list_assignments(db, "tax_component", tax.id)) == 1


async def test_a_shared_tax_posts_to_each_organizations_own_account(tree_world, db):
    _, world = tree_world
    with tenant_scope(world.tenant.id):
        tax = TaxComponent(tenant_id=world.tenant.id, tax_name="CGST9", tax_percentage=9, tax_type="tax")
        db.add(tax)
        await db.flush()
    accounts = {}
    for branch in (world.branch_a, world.branch_b):
        with tenant_scope(world.tenant.id, branch.id):
            account = Account(organization_id=branch.id, account_name=f"Output CGST {branch.org_code}",
                              account_type="other_current_liability")
            db.add(account)
            await db.flush()
            accounts[branch.id] = account
            await assignments.put_assignments(db, "tax_component", tax.id,
                                              [assignments.AccountSpec("output_tax", account_id=account.id)],
                                              organization_id=branch.id)
    await db.commit()
    with tenant_scope(world.tenant.id):
        rows = await assignments.list_assignments(db, "tax_component", tax.id)
    assert sorted((r.organization_id, r.account_id) for r in rows) == sorted(
        (org_id, account.id) for org_id, account in accounts.items())
    # an account of branch B cannot answer for branch A
    with tenant_scope(world.tenant.id, world.branch_a.id), pytest.raises(AccountRuleError):
        await assignments.put_assignments(db, "tax_component", tax.id,
                                          [assignments.AccountSpec("output_tax",
                                                                   account_id=accounts[world.branch_b.id].id)],
                                          organization_id=world.branch_a.id)


async def test_seeding_defaults_assigns_only_what_the_chart_makes_unambiguous(worlds, db):
    _, acme, _ = worlds
    await _account(db, acme, "Debtors", "accounts_receivable")
    await _account(db, acme, "Creditors", "accounts_payable")
    await _account(db, acme, "Creditors (USD)", "accounts_payable")
    await _account(db, acme, "Inventory", "stock")
    with tenant_scope(acme.tenant.id, acme.organization.id):
        report = await seed_organization_defaults(db, acme.organization.id)
        assert sorted(report["assigned"]) == ["inventory_asset", "receivable"]
        assert "payable" in report["unassigned"]                 # two AP accounts: ambiguous, never guessed
        assert "sales" in report["unassigned"]                   # never picked by name
        again = await seed_organization_defaults(db, acme.organization.id)
        assert again["assigned"] == [] and sorted(again["kept"]) == ["inventory_asset", "receivable"]


async def test_the_backfill_replays_stored_tax_documents_without_calling_zoho(worlds, db):
    """Taxes synced BEFORE account assignments existed get their links from the stored raw document."""
    from app.modules.taxes.zoho.backfill import backfill_tax_accounts

    _, acme, _ = worlds
    output = await _account(db, acme, "Output CGST", "other_current_liability", zoho_id="z-cgst-out")
    with tenant_scope(acme.tenant.id, acme.organization.id):
        thick = TaxComponent(tenant_id=acme.tenant.id, tax_name="CGST9", tax_percentage=9, tax_type="tax")
        thin = TaxComponent(tenant_id=acme.tenant.id, tax_name="SGST9", tax_percentage=9, tax_type="tax")
        db.add_all([thick, thin])
        await db.flush()
    for module, external_id, entity_table, entity_id, raw in (
        ("chart_of_accounts", "z-cgst-out", "accounting.accounts", output.id, {"account_id": "z-cgst-out"}),
        ("taxes", "z-cgst", "tax.tax_components", thick.id, {"tax_id": "z-cgst", "tax_account_id": "z-cgst-out"}),
        ("taxes", "z-sgst", "tax.tax_components", thin.id, {"tax_id": "z-sgst", "tax_name": "SGST9"}),
    ):
        await upsert_record(db, tenant_id=acme.tenant.id, source_system="zoho", module=module,
                            external_id=external_id, values={"entity_table": entity_table, "entity_id": entity_id,
                                                             "link_state": LinkState.LINKED, "raw": raw})
    with tenant_scope(acme.tenant.id, acme.organization.id):
        report = await backfill_tax_accounts(db)
        assert (report.scanned, report.replayed, report.skipped_thin) == (2, 1, 1)
        (row,) = await assignments.list_assignments(db, "tax_component", thick.id)
        assert (row.purpose_code, row.account_id, row.source_system) == ("output_tax", output.id, "zoho")
        assert await assignments.list_assignments(db, "tax_component", thin.id) == []
        again = await backfill_tax_accounts(db)                    # idempotent: the writer is a diff
        assert again.replayed == 1 and len(await assignments.list_assignments(db, "tax_component", thick.id)) == 1


def test_a_gst_legs_input_account_is_read_from_where_zoho_actually_puts_it():
    """Live THPL data: GST legs carry the INPUT-tax account in tds_payable_account_id (not documented)."""
    from app.modules.taxes.zoho.hooks import tax_account_refs

    cgst = TaxComponent(tax_name="CGST9", tax_specific_type="cgst")
    live = {"tax_account_id": "out", "purchase_tax_account_id": "", "tds_payable_account_id": "in"}
    assert tax_account_refs(cgst, live) == {"output_tax": "out", "input_tax": "in", "tds_payable": None}
    documented = {"tax_account_id": "out", "purchase_tax_account_id": "in", "tds_payable_account_id": "tds"}
    assert tax_account_refs(cgst, documented) == {"output_tax": "out", "input_tax": "in", "tds_payable": "tds"}
    tds = TaxComponent(tax_name="TDS 194C", tax_specific_type=None)
    assert tax_account_refs(tds, {"tds_payable_account_id": "tds"})["tds_payable"] == "tds"
