"""The tax adapter end to end: leaf taxes, groups, exemptions, grants, and the read API.

Real engine, real scratch Postgres, ``FakeZohoClient`` for Zoho. What is pinned here
is what the redesign paste required and the sync must therefore keep true:

  * a DETAIL payload fills every column it names, and the second run writes nothing;
  * the organization whose connection synced a tax is granted it — and an operator's
    revocation is not the sync's to undo;
  * a group's ``taxes[]`` becomes ordered ``tax_group_members``; a member that left the
    array is soft-deleted; a member not synced yet fails the record instead of linking
    fewer members than the source lists;
  * exemptions land with their P2 columns and the crosswalk holds their identity.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.database.tenancy import tenant_scope
from app.main import app
from app.modules.organizations.model import Organization
from app.modules.sync.models import SyncRecord
from app.modules.taxes.component import TaxComponent, TaxGroupMember
from app.modules.taxes.exemption import TaxExemption
from app.modules.taxes.org_tax import OrganizationTaxComponent
from app.modules.taxes.zoho.hooks import TaxGroupError, grant_to_context_organization
from app.modules.taxes.zoho.translator import TAX_TRANSLATOR
from app.modules.tenants.model import Tenant
from app.modules.users.deps import get_current_user
from app.modules.zoho.sync.engine import ZohoSyncEngine
from app.modules.zoho.sync.registry import sync_registry
from tests.zoho_sync.fake_client import FakeZohoClient, make_response

DETAIL = {
    "tax_id": "T-GST18", "tax_display_name": "GST 18%", "tax_name": "GST18", "tax_percentage": 18.0,
    "tax_type": "tax", "tax_specific_type": "igst", "tax_authority_id": "460000000066001",
    "tax_authority_name": "CBIC", "output_tax_account_name": "Output GST", "tax_account_id": "982000000000388",
    "tds_payable_account_id": "132086000000107337", "is_inactive": False, "is_default_tax": True,
    "is_editable": True, "tax_specification": "inter", "diff_rate_reason": "", "start_date": "2017-07-01",
    "end_date": "", "status": "Active", "description": "Standard rate", "reference_id": "REF-1",
    "tax_name_formatted": "GST18 (18%)", "is_state_cess": False, "tax_factor": "rate", "is_value_added": True,
    "country": "India", "country_code": "IN", "purchase_tax_account_id": "982000000000390",
    "purchase_tax_account_name": "Input GST", "purchase_tax_expense_account_id": 982000000000392,
}


def leaf(tax_id: str, name: str, pct: float, kind: str) -> dict:
    return {"tax_id": tax_id, "tax_name": name, "tax_percentage": pct, "tax_type": "tax",
            "tax_specific_type": kind}


def taxes_client(*records: dict, details: dict | None = None) -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub_list("/settings/taxes", [list(records)])
    for record in records:
        client.stub("GET", f"/settings/taxes/{record['tax_id']}", make_response((details or {}).get(record["tax_id"], record)))
    return client


async def _tenant_org(db, code="TAXSYNC"):
    tenant = Tenant(tenant_code=code, name=f"{code} Ltd", primary_contact_email=f"ops@{code.lower()}.example",
                    status="active")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        org = Organization(org_code=f"{code}-HQ", legal_name=f"{code} HQ", tenant_id=tenant.id)
        db.add(org)
        await db.flush()
    await db.commit()
    return tenant, org


async def _sync_leaves(db, tenant, org, *records):
    with tenant_scope(tenant.id, org.id):
        report = await ZohoSyncEngine(db, taxes_client(*records)).run("taxes")
    await db.commit()
    return report


async def _component(db, name: str) -> TaxComponent:
    return await db.scalar(select(TaxComponent).where(TaxComponent.tax_name == name))


def group_payload(*member_ids: str, name="GST18", group_id="G-GST18", **extra) -> dict:
    return {"tax_group_id": group_id, "tax_group_name": name, "tax_group_percentage": 18,
            "taxes": [{"tax_id": m, "tax_name": m} for m in member_ids], **extra}


async def _apply_group(db, tenant, org, payload):
    engine = ZohoSyncEngine(db, FakeZohoClient())
    with tenant_scope(tenant.id, org.id):
        return await engine.apply_payload(sync_registry.get("tax_groups"), payload, source="detail_fetch")


async def _members(db, group: TaxComponent) -> list[tuple[str, int | None]]:
    rows = (await db.execute(
        select(TaxComponent.tax_name, TaxGroupMember.position)
        .join(TaxGroupMember, TaxGroupMember.member_tax_id == TaxComponent.id)
        .where(TaxGroupMember.tax_group_id == group.id).order_by(TaxGroupMember.position)
    )).all()
    return [(name, position) for name, position in rows]


# ── leaf taxes ───────────────────────────────────────────────────────────────

async def test_a_detail_payload_fills_every_column_and_the_second_run_writes_nothing(db):
    tenant, org = await _tenant_org(db)
    with tenant_scope(tenant.id, org.id):
        client = taxes_client(leaf("T-GST18", "GST18", 18, "igst"), details={"T-GST18": DETAIL})
        report = await ZohoSyncEngine(db, client).run("taxes")
    await db.commit()
    assert report.created == 1 and report.updated == 1                       # index, then detail

    row = await _component(db, "GST18")
    for column, expected in TAX_TRANSLATOR.decode(DETAIL).values.items():
        assert getattr(row, column) == expected, column
    assert row.status == "active" and row.end_date is None and row.diff_rate_reason is None
    assert row.tax_type == "tax" and row.is_group is False
    assert row.tenant_id == tenant.id

    record = await db.scalar(select(SyncRecord).where(SyncRecord.external_id == "T-GST18"))
    assert (record.module, record.entity_table, record.entity_id) == ("taxes", "tax.tax_components", row.id)
    assert record.raw_source == "detail_fetch" and record.raw["tax_display_name"] == "GST 18%"

    with tenant_scope(tenant.id, org.id):
        again = await ZohoSyncEngine(db, taxes_client(leaf("T-GST18", "GST18", 18, "igst"),
                                                      details={"T-GST18": DETAIL})).run("taxes")
    assert again.unchanged == 2 and again.created == again.updated == 0     # index and detail phase, both no-ops


async def test_the_organization_that_synced_a_tax_is_granted_it(db):
    tenant, org = await _tenant_org(db)
    await _sync_leaves(db, tenant, org, leaf("T1", "CGST9", 9, "cgst"), leaf("T2", "SGST9", 9, "sgst"))
    grants = (await db.scalars(select(OrganizationTaxComponent))).all()
    assert len(grants) == 2 and {g.organization_id for g in grants} == {org.id}
    assert all(g.is_active and g.tenant_id == tenant.id for g in grants)


async def test_a_sync_with_no_organization_in_context_grants_nobody_and_does_not_fail(db):
    tenant, _ = await _tenant_org(db)
    with tenant_scope(tenant.id):
        report = await ZohoSyncEngine(db, taxes_client(leaf("T1", "CGST9", 9, "cgst"))).run("taxes")
    await db.commit()
    assert report.created == 1 and report.errors == 0
    assert (await db.scalars(select(OrganizationTaxComponent))).all() == []


async def test_a_revoked_grant_is_not_re_granted_by_the_sync(db):
    tenant, org = await _tenant_org(db)
    await _sync_leaves(db, tenant, org, leaf("T1", "CGST9", 9, "cgst"))
    component = await _component(db, "CGST9")
    grant = await db.scalar(select(OrganizationTaxComponent))
    with tenant_scope(tenant.id, org.id):
        grant.soft_delete(reason="operator revoked")
        await db.flush()
        await grant_to_context_organization(component, {})
        await db.flush()
    live = (await db.scalars(select(OrganizationTaxComponent))).all()
    assert live == []                                    # still revoked — no fresh live row


async def test_a_bad_record_quarantines_and_its_neighbours_survive(db):
    tenant, org = await _tenant_org(db)
    bad = {**leaf("T-BAD", "Broken", 9, "cgst"), "tax_type": 2}     # legacy numeric type: never guessed
    report = await _sync_leaves(db, tenant, org, leaf("T1", "CGST9", 9, "cgst"), bad)
    assert report.created == 1 and report.errors == 1
    assert await _component(db, "Broken") is None


# ── tax groups ───────────────────────────────────────────────────────────────

async def test_tax_groups_are_registered_but_disabled_because_zoho_documents_no_list(db):
    defn = sync_registry.get("tax_groups")
    assert defn.config.direction.value == "disabled"
    client = FakeZohoClient()
    tenant, org = await _tenant_org(db)
    with tenant_scope(tenant.id, org.id):
        report = await ZohoSyncEngine(db, client).run("tax_groups")
    assert report.mode == "skipped" and client.calls == []


async def test_a_group_becomes_ordered_members_and_is_forced_to_be_a_group(db):
    tenant, org = await _tenant_org(db)
    await _sync_leaves(db, tenant, org, leaf("T1", "CGST9", 9, "cgst"), leaf("T2", "SGST9", 9, "sgst"))

    # The payload even claims a specific leg and a leaf type: the adapter overrides both.
    result = await _apply_group(db, tenant, org, group_payload(
        "T2", "T1", tax_type="tax", tax_specific_type="cgst", status="Active"))
    await db.commit()
    assert result.created

    group = await _component(db, "GST18")
    assert group.tax_type == "tax_group" and group.tax_specific_type is None and group.is_group
    assert group.tax_percentage == 18 and group.status == "active"
    assert await _members(db, group) == [("SGST9", 0), ("CGST9", 1)]

    record = await db.scalar(select(SyncRecord).where(SyncRecord.external_id == "G-GST18"))
    assert (record.module, record.entity_table) == ("tax_groups", "tax.tax_components")
    # A group is shareable like any component.
    assert await db.scalar(select(OrganizationTaxComponent.id).where(
        OrganizationTaxComponent.tax_component_id == group.id)) is not None


async def test_membership_follows_the_payload_and_a_removed_member_is_soft_deleted(db):
    tenant, org = await _tenant_org(db)
    await _sync_leaves(db, tenant, org, leaf("T1", "CGST9", 9, "cgst"), leaf("T2", "SGST9", 9, "sgst"),
                       leaf("T3", "CESS1", 1, "cess"))
    await _apply_group(db, tenant, org, group_payload("T1", "T2"))
    await db.commit()
    group = await _component(db, "GST18")

    await _apply_group(db, tenant, org, group_payload("T3", "T1", name="GST18 v2"))     # T2 leaves, T3 joins
    await db.commit()
    assert await _members(db, group) == [("CESS1", 0), ("CGST9", 1)]

    ghosts = (await db.scalars(select(TaxGroupMember).where(TaxGroupMember.deleted_at.is_not(None))
                               .execution_options(include_deleted=True))).all()
    assert len(ghosts) == 1 and ghosts[0].deleted_reason == "no longer listed by the source"

    await _apply_group(db, tenant, org, {**group_payload("T1"), "tax_group_name": "GST18 v3", "taxes": []})
    await db.commit()
    assert await _members(db, group) == []                # an empty array IS a statement


async def test_a_payload_without_taxes_says_nothing_about_membership(db):
    tenant, org = await _tenant_org(db)
    await _sync_leaves(db, tenant, org, leaf("T1", "CGST9", 9, "cgst"))
    await _apply_group(db, tenant, org, group_payload("T1"))
    await db.commit()
    group = await _component(db, "GST18")

    thin = {k: v for k, v in group_payload("T1", name="GST18 renamed").items() if k != "taxes"}
    await _apply_group(db, tenant, org, thin)
    await db.commit()
    assert group.tax_name == "GST18 renamed" and await _members(db, group) == [("CGST9", 0)]


async def test_a_group_naming_an_unsynced_member_fails_the_record_and_leaves_nothing(db):
    tenant, org = await _tenant_org(db)
    await _sync_leaves(db, tenant, org, leaf("T1", "CGST9", 9, "cgst"))
    with pytest.raises(TaxGroupError, match="not synced yet.*T-MISSING"):
        async with db.begin_nested():
            await _apply_group(db, tenant, org, group_payload("T1", "T-MISSING"))
    # The record's transaction (crosswalk row included) rolled back, so the next
    # attempt is judged afresh instead of being skipped as "unchanged".
    assert await _component(db, "GST18") is None
    assert await db.scalar(select(SyncRecord).where(SyncRecord.external_id == "G-GST18")) is None


async def test_a_group_cannot_list_another_group_as_a_member(db):
    tenant, org = await _tenant_org(db)
    await _sync_leaves(db, tenant, org, leaf("T1", "CGST9", 9, "cgst"))
    await _apply_group(db, tenant, org, group_payload("T1", name="Inner", group_id="G-INNER"))
    # Make the inner group resolvable as a "taxes" reference, as Zoho's shared id namespace would.
    inner = await _component(db, "Inner")
    db.add(SyncRecord(tenant_id=tenant.id, source_system="zoho", module="taxes", external_id="G-INNER",
                      entity_table="tax.tax_components", entity_id=inner.id))
    await db.commit()
    with pytest.raises(TaxGroupError, match="tax groups as members"):
        async with db.begin_nested():
            await _apply_group(db, tenant, org, group_payload("G-INNER", name="Outer", group_id="G-OUTER"))


# ── exemptions ───────────────────────────────────────────────────────────────

EXEMPTIONS = [
    {"tax_exemption_id": "E1", "tax_exemption_code": "BILL OF SUPPLY", "description": "Composition dealer",
     "type": "item", "type_formatted": "Item", "exemption_name": "", "exemption_type": "exempt",
     "exemption_type_formatted": "Exempt"},
    {"tax_exemption_id": "E2", "tax_exemption_code": "MINABEN PATEL", "description": "",
     "type": "customer", "type_formatted": "Customer", "exemption_name": "M. Patel",
     "exemption_type": "something-new", "exemption_type_formatted": "Something new"},
]


def exemptions_client() -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub("GET", "/settings/taxexemptions", make_response(EXEMPTIONS))
    return client


async def test_exemptions_sync_with_their_p2_columns_and_open_vocabularies(db):
    tenant, org = await _tenant_org(db)
    client = exemptions_client()
    with tenant_scope(tenant.id, org.id):
        report = await ZohoSyncEngine(db, client).run("tax_exemptions")
    await db.commit()
    assert report.created == 2 and len(client.calls) == 1 and client.calls[0]["params"] is None

    by_code = {r.tax_exemption_code: r for r in (await db.scalars(select(TaxExemption))).all()}
    supply, person = by_code["BILL OF SUPPLY"], by_code["MINABEN PATEL"]
    assert (supply.type, supply.type_formatted, supply.exemption_type, supply.description) == \
        ("item", "Item", "exempt", "Composition dealer")
    assert supply.exemption_name is None                                  # "" → NULL
    assert person.exemption_name == "M. Patel" and person.exemption_type == "something-new"   # open, no CHECK
    assert supply.organization_id == org.id and supply.tenant_id == tenant.id

    records = (await db.scalars(select(SyncRecord).where(SyncRecord.module == "tax_exemptions"))).all()
    assert {r.external_id: r.entity_table for r in records} == {"E1": "tax.tax_exemptions", "E2": "tax.tax_exemptions"}

    with tenant_scope(tenant.id, org.id):
        again = await ZohoSyncEngine(db, exemptions_client()).run("tax_exemptions")
    assert again.unchanged == 2 and again.created == again.updated == 0


# ── the read API ─────────────────────────────────────────────────────────────

@pytest.fixture
async def api_client(db):
    import httpx

    from app.database.db import get_db

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, email="u@x.com")
    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_the_api_serves_slim_lists_and_a_fat_group_by_local_uuid_or_zoho_id(db, api_client):
    tenant, org = await _tenant_org(db)
    other_tenant, other_org = await _tenant_org(db, "OTHERORG")
    await _sync_leaves(db, tenant, org, leaf("T1", "CGST9", 9, "cgst"), leaf("T2", "SGST9", 9, "sgst"))
    await _apply_group(db, tenant, org, group_payload("T1", "T2"))
    await db.commit()
    group = await _component(db, "GST18")

    listed = (await api_client.get("/api/taxes", params={"tax_type": "tax_group"})).json()["data"]
    assert [r["tax_name"] for r in listed] == ["GST18"]
    assert "tds_payable_account_id" not in listed[0] and "members" not in listed[0]        # Slim

    for ref in (str(group.id), str(group.uuid), "G-GST18"):
        fat = (await api_client.get(f"/api/taxes/{ref}")).json()["data"]
        assert fat["id"] == group.id and fat["tax_type"] == "tax_group"
        assert [(m["position"], m["member"]["tax_name"]) for m in fat["members"]] == [(0, "CGST9"), (1, "SGST9")]
        assert [(s["module"], s["external_id"]) for s in fat["sources"]] == [("tax_groups", "G-GST18")]

    granted = (await api_client.get("/api/taxes", params={"organization_id": org.id})).json()["data"]
    assert {r["tax_name"] for r in granted} == {"CGST9", "SGST9", "GST18"}
    assert (await api_client.get("/api/taxes", params={"organization_id": other_org.id})).json()["data"] == []
    assert (await api_client.get("/api/taxes", params={"tax_type": "bogus"})).status_code == 422


async def test_the_api_serves_exemptions_treatments_and_defaults(db, api_client):
    tenant, org = await _tenant_org(db)
    with tenant_scope(tenant.id, org.id):
        await ZohoSyncEngine(db, exemptions_client()).run("tax_exemptions")
    await db.commit()
    data = (await api_client.get("/api/taxes/exemptions")).json()["data"]
    assert {r["tax_exemption_code"] for r in data} == {"BILL OF SUPPLY", "MINABEN PATEL"}   # not read as a {ref}

    assert (await api_client.get("/api/taxes/gst-treatments")).json()["data"] == []
    assert (await api_client.get("/api/taxes/default-preferences")).json()["data"] == []
