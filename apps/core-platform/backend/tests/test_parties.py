"""Parties — customers and vendors (Zoho contacts), contact persons, addresses, registrations, custom fields.

  * hermetic — the translator on Zoho's live shapes, address normalization (empty / country / plausible
    coordinates), registration extraction, the document mixins;
  * database — the hook's projections driven with Zoho-shaped payloads (persons + one primary + child
    crosswalk, addresses into the location hub with in-party reuse and copy-on-write, registrations,
    custom fields learned from payloads, payment terms, merges), scope;
  * API — list / search (name, mobile, GSTIN) / detail, organization isolation.

The full Zoho path (real transport, list → detail, rate-limit halt, merge redirect through the engine,
confirm-before-tombstone) is ``tests/zoho_core/test_masters_e2e.py``.
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database.tenancy import tenant_scope
from app.modules.custom_fields.model import DataType, FieldDefinition, FieldValue
from app.modules.geo.model.link import PlaceLink
from app.modules.geo.model.place import Place
from app.modules.parties.mixins import HasCustomerMixin, HasVendorMixin
from app.modules.parties.model import ContactPerson, Party, PaymentTerm
from app.modules.parties.zoho.addresses import address_parts, plausible_point
from app.modules.parties.zoho.hooks import after_party_upsert
from app.modules.parties.zoho.registrations import wanted_registrations
from app.modules.parties.zoho.spec import PARTIES_CONFIG, PARTIES_TRANSLATOR
from app.modules.sync.models import LinkState, SyncRecord
from app.modules.sync.translation import PayloadShape
from app.modules.taxes.tax_registration import TaxRegistration

# A Zoho contact DETAIL, shaped like the live documents (THPL samples, anonymised).
ADDRESS = {"address_id": "a-bill", "attention": "Ramesh Patel", "address": "CQ92+9PC, Main Road", "street2": "",
           "city": "Ditwas", "state_code": "", "state": "Gujarat ", "zip": "389250", "country": "India",
           "county": "", "latitude": "", "longitude": "", "country_code": "IN", "phone": "+919000000001", "fax": ""}
DETAIL = {
    "contact_id": "c-1", "contact_name": "Patel Medical Store", "company_name": "Patel Medical Store",
    "contact_type": "customer", "customer_sub_type": "business", "status": "active", "source": "api",
    "first_name": "Ramesh", "last_name": "Patel", "mobile": "+919000000001", "email": "", "language_code": "",
    "is_bcy_only_contact": True, "payment_terms": 0, "payment_terms_label": "Due on Receipt",
    "payment_terms_id": "pt-due", "place_of_contact": "GJ", "gst_treatment": "business_gst",
    "contact_category": "business_gst", "gst_no": "24ABCDE1234F1Z5", "pan_no": "ABCDE1234F",
    "trader_name": "PATEL MEDICALS", "legal_name": "RAMESH PATEL", "udyam_reg_no": "", "msme_type": "",
    "tax_info_list": [{"tax_info_id": "ti-1", "tax_registration_no": "24ABCDE1234F1Z5", "place_of_supply": "GJ",
                       "is_primary": True, "trader_name": "PATEL MEDICALS", "legal_name": "RAMESH PATEL"}],
    "tax_id": "", "tax_exemption_id": "", "account_id": "", "owner_id": "",
    "primary_contact_id": "p-1",
    "contact_persons": [
        {"contact_person_id": "p-1", "first_name": "Ramesh", "last_name": "Patel", "mobile": "+919000000001",
         "is_primary_contact": True, "communication_preference": {"is_email_enabled": True, "is_whatsapp_enabled": False},
         "is_sms_enabled_for_cp": False, "can_invite": True},
        {"contact_person_id": "p-2", "first_name": "Suresh", "last_name": "", "mobile": "+91 90000 00002",
         "is_primary_contact": False, "communication_preference": {"is_email_enabled": True, "is_whatsapp_enabled": True}},
    ],
    "billing_address": ADDRESS,
    "shipping_address": {**ADDRESS, "address_id": "a-ship"},           # same text, own Zoho id
    "addresses": [],
    "custom_fields": [
        {"field_id": "f-risk", "api_name": "cf_risk_score", "label": "Credit Risk", "data_type": "dropdown",
         "value": "Medium", "selected_option_id": "o-med", "color_code": "ffb94d", "index": 1, "is_active": True},
        {"field_id": "f-hul", "api_name": "cf_is_hul_record", "label": "Is HUL record", "data_type": "check_box",
         "value": True, "index": 2, "is_active": True},
    ],
    "created_time": "2025-11-24T16:55:48+0530", "last_modified_time": "2026-07-08T09:49:49+0530",
}
LIST_ROW = {k: DETAIL[k] for k in ("contact_id", "contact_name", "company_name", "contact_type", "customer_sub_type",
                                    "status", "mobile", "payment_terms", "payment_terms_label", "payment_terms_id",
                                    "place_of_contact", "gst_treatment", "gst_no", "pan_no", "custom_fields",
                                    "created_time", "last_modified_time")}


# ── hermetic ──────────────────────────────────────────────────────────────────

def test_the_translator_maps_zoho_contact_keys_onto_party_columns():
    decoded = PARTIES_TRANSLATOR.decode({**LIST_ROW, "payment_terms": "-3",
                                         "payment_terms_label": "Due end of next month"},
                                        shape=PayloadShape.INDEX).values
    assert decoded["name"] == "Patel Medical Store" and decoded["party_type"] == "customer"
    assert decoded["place_of_supply"] == "GJ" and decoded["payment_terms"] == -3       # a rule code, kept as is
    assert "notes" not in decoded and "first_name" not in decoded                       # absent, not NULL
    assert not any(k in decoded for k in ("contact_name", "contact_type", "place_of_contact"))
    detail = PARTIES_TRANSLATOR.decode(DETAIL, shape=PayloadShape.DETAIL).values
    assert detail["email"] is None and detail["language_code"] is None                  # '' → NULL


def test_the_spec_lists_every_contact_in_a_stable_order_and_confirms_deletions():
    cfg = PARTIES_CONFIG
    assert (cfg.module, cfg.endpoint, cfg.zoho_id_attr) == ("parties", "/contacts", "contact_id")
    assert cfg.list_params == {"filter_by": "Status.All", "sort_column": "created_time", "sort_order": "A"}
    assert cfg.detail_required and cfg.index_then_detail and cfg.soft_delete_missing and cfg.confirm_missing_by_detail


def test_addresses_skip_empty_blocks_and_infer_the_country():
    assert address_parts({"address_id": "x", "phone": "+91999", "attention": "A"}) is None   # phone only = not postal
    parts = address_parts({"address": "Opp. garden ", "street2": "Balasinor road", "city": "Kathlal",
                           "state": "Gujarat ", "country": "", "country_code": ""})
    assert (parts["state"], parts["country"], parts["country_code"]) == ("Gujarat", "India", "IN")
    assert plausible_point("22.95", "73.75") == (22.95, 73.75)
    assert plausible_point("2.295", "73.75") is None and plausible_point("abc", "1") is None


def test_registrations_come_from_the_gst_list_and_the_scalar_keys():
    regs = wanted_registrations(None, {**DETAIL, "udyam_reg_no": "UDYAM-GJ-01-0000001", "msme_type": "micro"})
    kinds = {(r["registration_type"], r["registration_number"]) for r in regs}
    assert kinds == {("gstin", "24ABCDE1234F1Z5"), ("pan", "ABCDE1234F"), ("udyam", "UDYAM-GJ-01-0000001")}
    gstin = next(r for r in regs if r["registration_type"] == "gstin")
    assert gstin["zoho_id"] == "ti-1" and gstin["is_primary"] is True                # gst_no == the list entry: once


def test_the_document_mixins_carry_column_fk_relationship_and_zoho_reference():
    fk = HasCustomerMixin.customer_fk("invoices")
    assert (fk.name, [c for c in fk.column_keys]) == ("fk_invoices_customer", ["tenant_id", "organization_id",
                                                                               "customer_id"])
    rule = HasVendorMixin.zoho_vendor_reference()
    assert (rule.attr, rule.module, rule.fk) == ("vendor_id", "parties", "vendor_id")


# ── database: the hook's projections ──────────────────────────────────────────

async def _party(db, world, **kw) -> Party:
    with tenant_scope(world.tenant.id, world.organization.id):
        party = Party(organization_id=world.organization.id, name=kw.pop("name", "Patel Medical Store"),
                      party_type=kw.pop("party_type", "customer"), zoho_id=kw.pop("zoho_id", "c-1"), **kw)
        db.add(party)
        await db.flush()
    return party


async def test_persons_land_with_one_primary_and_their_own_crosswalk(worlds, db):
    _, acme, _ = worlds
    party = await _party(db, acme)
    with tenant_scope(acme.tenant.id, acme.organization.id):
        await after_party_upsert(party, DETAIL)
        persons = {p.zoho_id: p for p in await db.scalars(select(ContactPerson))}
        assert persons["p-1"].is_primary and not persons["p-2"].is_primary
        assert party.primary_contact_person_id == persons["p-1"].id
        assert persons["p-2"].display_name == "Suresh" and persons["p-2"].is_whatsapp_enabled is True
        links = {r.external_id: r for r in await db.scalars(select(SyncRecord).where(
            SyncRecord.module == "contact_persons"))}
        assert links["p-1"].entity_id == persons["p-1"].id and links["p-1"].link_state == LinkState.LINKED

        # Zoho moves the primary flag and drops p-1: no unique violation, p-1 retired and tombstoned.
        moved = copy.deepcopy(DETAIL)
        moved["contact_persons"] = [{**moved["contact_persons"][1], "is_primary_contact": True}]
        await after_party_upsert(party, moved)
        live = list(await db.scalars(select(ContactPerson)))
        assert [(p.zoho_id, p.is_primary) for p in live] == [("p-2", True)]
        assert party.primary_contact_person_id == live[0].id
        tomb = await db.scalar(select(SyncRecord).where(SyncRecord.module == "contact_persons",
                                                        SyncRecord.external_id == "p-1"))
        assert tomb.remote_deleted_at is not None

        # A list row (no contact_persons key) changes nothing.
        await after_party_upsert(party, LIST_ROW)
        assert len(list(await db.scalars(select(ContactPerson)))) == 1


async def test_addresses_go_to_the_location_hub_reused_within_the_party_only(worlds, db):
    _, acme, _ = worlds
    party = await _party(db, acme)
    other = await _party(db, acme, name="Other Store", zoho_id="c-2")
    with tenant_scope(acme.tenant.id, acme.organization.id):
        await after_party_upsert(party, DETAIL)
        links = {link.zoho_id: link for link in await db.scalars(select(PlaceLink).where(PlaceLink.owner_id == party.id))}
        assert set(links) == {"a-bill", "a-ship"}
        assert links["a-bill"].place_id == links["a-ship"].place_id                  # same text → one place
        assert (links["a-bill"].link_type, links["a-bill"].is_primary, links["a-bill"].attention) == (
            "billing", True, "Ramesh Patel")
        place = await db.get(Place, links["a-bill"].place_id)
        assert (place.state, place.postal_code, place.kind) == ("Gujarat", "389250", "customer_site")

        # Another party with the SAME text gets its own place (never matched across parties).
        await after_party_upsert(other, {**DETAIL, "contact_id": "c-2", "contact_persons": [],
                                         "tax_info_list": [], "gst_no": "", "pan_no": "", "custom_fields": [],
                                         "billing_address": {**ADDRESS, "address_id": "b-bill"},
                                         "shipping_address": {"address_id": "b-ship"}})
        other_link = await db.scalar(select(PlaceLink).where(PlaceLink.zoho_id == "b-bill"))
        assert other_link.place_id != place.id
        assert await db.scalar(select(PlaceLink).where(PlaceLink.zoho_id == "b-ship")) is None   # empty → nothing

        # Zoho edits the shipping text: the place is shared with billing → copy-on-write, billing untouched.
        edited = copy.deepcopy(DETAIL)
        edited["shipping_address"] = {**ADDRESS, "address_id": "a-ship", "address": "Shop 4, Station Road"}
        edited["addresses"] = [{**ADDRESS, "address_id": "a-extra", "address": "Godown, GIDC"}]
        await after_party_upsert(party, edited)
        await db.refresh(links["a-bill"])
        await db.refresh(links["a-ship"])
        assert links["a-bill"].place_id == place.id and links["a-ship"].place_id != place.id
        extra = await db.scalar(select(PlaceLink).where(PlaceLink.zoho_id == "a-extra"))
        assert (extra.link_type, extra.is_primary) == ("other", False)              # owner decision: other

        # Zoho empties the extra address: its link is closed (history), never deleted.
        edited["addresses"] = []
        await after_party_upsert(party, edited)
        await db.refresh(extra)
        assert extra.valid_to is not None and extra.deleted_at is None


async def test_the_same_address_twice_in_addresses_keeps_one_link(worlds, db):
    """Live (2026-10-10, 12 THPL contacts): billing + the SAME text twice in addresses[] under two
    address_ids. Both extras reuse the billing place, and the second used to violate uq_place_links_dedupe
    and fail the whole contact."""
    _, acme, _ = worlds
    party = await _party(db, acme)
    payload = copy.deepcopy(DETAIL)
    payload["addresses"] = [{**ADDRESS, "address_id": "x-1"}, {**ADDRESS, "address_id": "x-2"}]
    with tenant_scope(acme.tenant.id, acme.organization.id):
        await after_party_upsert(party, payload)
        await after_party_upsert(party, payload)           # idempotent on the next sync
        others = list(await db.scalars(select(PlaceLink).where(
            PlaceLink.owner_id == party.id, PlaceLink.link_type == "other", PlaceLink.valid_to.is_(None))))
    assert len(others) == 1 and others[0].zoho_id == "x-1"


async def test_registrations_custom_fields_and_payment_terms_are_learned(worlds, db):
    _, acme, _ = worlds
    party = await _party(db, acme)
    with tenant_scope(acme.tenant.id, acme.organization.id):
        await after_party_upsert(party, DETAIL)
        regs = {r.registration_type: r for r in await db.scalars(select(TaxRegistration))}
        assert regs["pan"].registration_number == "ABCDE1234F"                       # in clear (owner decision)
        assert (regs["gstin"].zoho_id, regs["gstin"].is_primary, regs["gstin"].source_system) == ("ti-1", True, "zoho")

        definitions = {d.api_name: d for d in await db.scalars(select(FieldDefinition))}
        assert definitions["cf_risk_score"].zoho_field_id == "f-risk"
        assert definitions["cf_risk_score"].options == [{"id": "o-med", "value": "Medium", "color_code": "ffb94d"}]
        learned = await db.scalar(select(DataType).where(DataType.code == "check_box"))
        assert learned.storage_column == "value_boolean"                              # an unseen Zoho type is learned
        values = {v.field_definition_id: v for v in await db.scalars(select(FieldValue))}
        assert values[definitions["cf_risk_score"].id].value_text == "Medium"
        assert values[definitions["cf_is_hul_record"].id].value_boolean is True

        term = await db.scalar(select(PaymentTerm))
        assert (term.zoho_id, term.payment_terms, term.label, term.net_days) == ("pt-due", 0, "Due on Receipt", 0)
        assert party.payment_term_id == term.id

        # Zoho omits a now-empty custom field and drops the PAN.
        later = {**DETAIL, "custom_fields": DETAIL["custom_fields"][:1], "pan_no": ""}
        await after_party_upsert(party, later)
        assert definitions["cf_is_hul_record"].id not in {
            v.field_definition_id for v in await db.scalars(select(FieldValue))}
        assert "pan" not in {r.registration_type for r in await db.scalars(select(TaxRegistration))}


async def test_a_merged_duplicate_redirects_to_the_survivor_but_a_live_one_is_left_alone(worlds, db):
    _, acme, _ = worlds
    survivor = await _party(db, acme)
    live = await _party(db, acme, name="Still in Zoho", zoho_id="c-live")
    with tenant_scope(acme.tenant.id, acme.organization.id):
        from app.modules.sync.crosswalk import upsert_record

        await upsert_record(db, tenant_id=acme.tenant.id, source_system="zoho", module="parties",
                            external_id="c-live", values={"entity_table": "party.parties", "entity_id": live.id,
                                                          "link_state": LinkState.LINKED})
        await after_party_upsert(survivor, {**LIST_ROW, "cf_merged_customer_ids": "c-gone, c-live"})
        rows = {r.external_id: r for r in await db.scalars(select(SyncRecord).where(SyncRecord.module == "parties"))}
        assert (rows["c-gone"].entity_id, rows["c-gone"].link_state) == (survivor.id, LinkState.MERGED)
        assert (rows["c-live"].entity_id, rows["c-live"].link_state) == (live.id, LinkState.LINKED)


# ── API ───────────────────────────────────────────────────────────────────────

async def test_the_api_lists_searches_and_describes_within_the_organization(worlds, db):
    client, acme, globex = worlds
    party = await _party(db, acme, mobile="+919000000001", credit_limit=Decimal("50000"))
    await _party(db, acme, name="Gupta Traders", zoho_id="c-9", party_type="vendor")
    with tenant_scope(acme.tenant.id, acme.organization.id):
        await after_party_upsert(party, DETAIL)
    await db.commit()
    headers = acme.auth(acme.admin)

    page = (await client.get("/api/parties", headers=headers)).json()["data"]
    assert page["total"] == 2
    vendors = (await client.get("/api/parties?type=vendor", headers=headers)).json()["data"]["items"]
    assert [v["name"] for v in vendors] == ["Gupta Traders"]
    for q in ("patel", "90000 00001", "24abcde1234f1z5"):                           # name, mobile, GSTIN
        found = (await client.get(f"/api/parties?q={q}", headers=headers)).json()["data"]["items"]
        assert [p["name"] for p in found] == ["Patel Medical Store"], q

    detail = (await client.get(f"/api/parties/{party.uuid}", headers=headers)).json()["data"]
    assert [p["zoho_id"] for p in detail["persons"]] == ["p-1", "p-2"]
    assert {a["link_type"] for a in detail["addresses"]} == {"billing", "shipping"}
    assert {r["registration_type"] for r in detail["registrations"]} == {"gstin", "pan"}
    assert {c["api_name"] for c in detail["custom_fields"]} == {"cf_risk_score", "cf_is_hul_record"}
    assert detail["payment_term"]["label"] == "Due on Receipt" and detail["app_metadata"] == {}

    persons = (await client.get(f"/api/parties/{party.id}/persons", headers=headers)).json()["data"]
    assert persons[0]["is_primary"] and persons[0]["avatar_urls"] is None

    globex_headers = globex.auth(globex.admin)
    assert (await client.get("/api/parties", headers=globex_headers)).json()["data"]["total"] == 0
    assert (await client.get(f"/api/parties/{party.id}", headers=globex_headers)).status_code == 404


@pytest.mark.parametrize("bad", ["", None])
def test_an_empty_merge_field_is_ignored(bad):
    assert not (LIST_ROW | {"cf_merged_customer_ids": bad}).get("cf_merged_customer_ids")
