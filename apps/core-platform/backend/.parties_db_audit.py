"""READ-ONLY consistency audit of party.* against the Zoho documents the sync stored (no Zoho calls).

For every party whose crosswalk holds the DETAIL document, recompute what every table should contain from that
document and compare: party columns (through the translator), references (currency, price list, payment term,
owner, primary person), persons, addresses (geo), registrations (tax), custom fields (extfields), tax assignment,
merges, coordinates. Also: every Zoho key is accounted for, and fill rates show which columns are blank and why.
Temporary — delete after use.
"""

import asyncio
import collections
import importlib
from decimal import Decimal

# Zoho keys deliberately not stored as columns (the adapter doc says why) — anything else unmapped is reported.
NOT_COLUMNS = {
    "contact_id", "customer_name", "vendor_name", "currency_id", "currency_code", "currency_symbol", "price_precision",
    "exchange_rate", "pricebook_id", "pricebook_name", "payment_terms_id", "tax_id", "tax_name", "tax_percentage",
    "contact_tax_information", "tax_specification", "tds_tax_id", "tds_tax_name", "tds_tax_percentage",
    "tax_exemption_id", "tax_exemption_code", "tax_treatment", "gst_no", "pan_no", "tax_info_list", "udyam_reg_no",
    "msme_type", "is_valid_udyam_no", "udyam_validated_time", "vat_reg_no", "tax_reg_no", "tax_reg_label",
    "country_code", "account_id", "account_name", "owner_id", "owner_name", "primary_contact_id", "contact_persons",
    "billing_address", "shipping_address", "addresses", "entity_address_id", "custom_fields", "custom_field_hash",
    "last_modified_time", "created_date", "created_by_name", "created_by_id", "last_modified_by_id",
    "opening_balances", "default_templates", "cards", "checks", "upi_mandates", "bank_accounts", "vpa_list",
    "ach_supported", "associated_with_square", "approvers_list", "submitted_date", "submitted_by",
    "submitted_by_name", "submitted_by_email", "submitted_by_photo_url", "submitter_id", "approver_id",
    "approval_name", "approval_path", "approvers", "note_to_approver", "is_multi_match_approval", "lock_details",
    "lock_detail", "locked_actions", "contact_blocks", "zcrm_account_id", "zcrm_contact_id", "zcrm_vendor_id",
    "crm_owner_id", "is_crm_customer", "is_linked_with_zohocrm", "zohopeople_client_id", "integration_references",
    "additional_information", "registration_details", "can_show_integration_outlet_info",
    "is_credit_limit_migration_completed", "can_show_customer_ob", "can_show_vendor_ob", "invited_by",
    "is_client_review_asked", "is_client_review_settings_enabled", "contact_relation_type", "documents", "photo_url",
    "tags", "has_attachment", "opening_balance_amount", "opening_balance_amount_bcy", "credit_limit_exceeded_amount",
    "customer_currency_summaries", "vendor_currency_summaries", "unused_retainer_payments", "portal_receipt_count",
    "outstanding_ob_receivable_amount", "outstanding_ob_payable_amount",
}
NOT_COLUMN_PREFIXES = ("cf_", "outstanding_", "unused_")


def norm(v):
    if isinstance(v, Decimal):
        return v.normalize()
    if isinstance(v, str):
        return " ".join(v.split()) or None
    return v


async def main():
    importlib.import_module("app.router")
    from sqlalchemy import select

    from app.database.db import async_session_factory, engine
    from app.modules.custom_fields.model import FieldDefinition, FieldValue
    from app.modules.geo.model.link import PlaceLink
    from app.modules.geo.model.place import Place
    from app.modules.parties.model import ContactPerson, Party, PaymentTerm
    from app.modules.parties.zoho.addresses import address_parts, plausible_point, wanted_addresses
    from app.modules.parties.zoho.persons import person_values
    from app.modules.parties.zoho.registrations import wanted_registrations
    from app.modules.parties.zoho.spec import PARTIES_TRANSLATOR
    from app.modules.sync.models import SyncRecord
    from app.modules.sync.translation import PayloadShape
    from app.modules.taxes.assignment import TaxAssignment
    from app.modules.taxes.tax_registration import TaxRegistration
    from app.modules.zoho_users.model import ZohoUser

    problems: dict[str, list[str]] = collections.defaultdict(list)
    stats = collections.Counter()
    unknown_keys = collections.Counter()
    mapped = {f.external for f in PARTIES_TRANSLATOR.fields} if hasattr(PARTIES_TRANSLATOR, "fields") else set()
    from app.modules.parties.zoho.fields import FIELDS
    mapped = {f.external for f in FIELDS}

    def flag(kind, msg):
        problems[kind].append(msg)

    async with async_session_factory() as db:
        xw = {r.external_id: r for r in (await db.scalars(select(SyncRecord).where(SyncRecord.module == "parties"))).all()}
        crosswalk_by = lambda module: {r.external_id: r.entity_id for r in xw_all.get(module, [])}  # noqa: E731
        xw_all = collections.defaultdict(list)
        for r in (await db.scalars(select(SyncRecord).where(SyncRecord.module.in_(
                ("currencies", "price_lists", "taxes", "tax_groups", "tax_exemptions"))))).all():
            xw_all[r.module].append(r)
        currencies, price_lists = crosswalk_by("currencies"), crosswalk_by("price_lists")
        taxes = {**crosswalk_by("tax_groups"), **crosswalk_by("taxes")}
        terms = {t.zoho_id: t.id for t in (await db.scalars(select(PaymentTerm))).all()}
        users = {u.zoho_id: u.id for u in (await db.scalars(select(ZohoUser))).all()}
        parties = {p.id: p for p in (await db.scalars(select(Party).execution_options(include_deleted=True))).all()}
        definitions = {d.id: d for d in (await db.scalars(select(FieldDefinition))).all()}

        for ext, rec in xw.items():
            if rec.link_state == "merged":
                stats["merged_redirects"] += 1
                continue
            party = parties.get(rec.entity_id)
            if party is None:
                flag("crosswalk", f"{ext}: crosswalk points at missing party {rec.entity_id}")
                continue
            stats["parties"] += 1
            if party.organization_id is None or party.zoho_id != ext:
                flag("identity", f"{ext}: zoho_id echo {party.zoho_id!r}")
            if rec.raw_source != "detail_fetch":
                stats["awaiting_detail"] += 1
                continue
            d = rec.raw or {}
            stats["detailed"] += 1
            w = ext

            # Zoho keys: all accounted for?
            for key in d:
                if key not in mapped and key not in NOT_COLUMNS and not key.startswith(NOT_COLUMN_PREFIXES) \
                        and not key.endswith("_formatted"):
                    unknown_keys[key] += 1

            # 1. columns through the translator
            for col, theirs in PARTIES_TRANSLATOR.decode(d, shape=PayloadShape.DETAIL).values.items():
                ours = getattr(party, col)
                if norm(ours) != norm(theirs):
                    flag(f"column:{col}", f"{w}: ours={ours!r} zoho={theirs!r}")
                stats["cells"] += 1

            # 2. references
            want = currencies.get(str(d.get("currency_id") or "")) if d.get("currency_id") else None
            if d.get("currency_id") and party.currency_id != want:
                flag("ref:currency", f"{w}: ours={party.currency_id} want={want} (zoho {d.get('currency_id')})")
            if d.get("pricebook_id"):
                if party.price_list_id != price_lists.get(str(d["pricebook_id"])):
                    flag("ref:price_list", f"{w}: ours={party.price_list_id} zoho={d['pricebook_id']}")
            elif party.price_list_id is not None:
                flag("ref:price_list", f"{w}: set but Zoho has none")
            if d.get("payment_terms_id"):
                if party.payment_term_id != terms.get(str(d["payment_terms_id"])):
                    flag("ref:payment_term", f"{w}: ours={party.payment_term_id} zoho={d['payment_terms_id']}")
            elif party.payment_term_id is not None:
                flag("ref:payment_term", f"{w}: set but Zoho has none")
            if d.get("owner_id"):
                if party.owner_zoho_user_id != users.get(str(d["owner_id"])):
                    flag("ref:owner", f"{w}: ours={party.owner_zoho_user_id} zoho={d['owner_id']}")

            # 3. persons + primary
            persons = {p.zoho_id: p for p in (await db.scalars(select(ContactPerson).where(
                ContactPerson.party_id == party.id))).all()}
            zp = {str(p["contact_person_id"]): (i, p) for i, p in enumerate(d.get("contact_persons") or [])}
            if set(persons) != set(zp):
                flag("persons:set", f"{w}: ours={sorted(persons)} zoho={sorted(zp)}")
            for pid, (pos, zperson) in zp.items():
                ours = persons.get(pid)
                if ours is None:
                    continue
                stats["persons"] += 1
                for col, value in person_values(zperson, pos).items():
                    if norm(getattr(ours, col)) != norm(value):
                        flag(f"person:{col}", f"{w}/{pid}: ours={getattr(ours, col)!r} zoho={value!r}")
                if bool(ours.is_primary) != bool(zperson.get("is_primary_contact")):
                    flag("person:is_primary", f"{w}/{pid}: ours={ours.is_primary}")
                if (ours.tenant_id, ours.organization_id) != (party.tenant_id, party.organization_id):
                    flag("person:scope", f"{w}/{pid}")
            primary_zoho = str(d.get("primary_contact_id") or "")
            if primary_zoho and primary_zoho in persons:
                if party.primary_contact_person_id != persons[primary_zoho].id:
                    flag("ref:primary_person", f"{w}: ours={party.primary_contact_person_id} zoho={primary_zoho}")
            elif zp and party.primary_contact_person_id is None and any(p.get("is_primary_contact") for _, p in zp.values()):
                flag("ref:primary_person", f"{w}: flagged primary but pointer empty")

            # 4. addresses
            links = {link.zoho_id: link for link in (await db.scalars(select(PlaceLink).where(
                PlaceLink.owner_type == "party", PlaceLink.owner_id == party.id))).all()}
            for address_id, link_type, raw, _label in wanted_addresses(d):
                parts = address_parts(raw)
                link = links.get(address_id)
                if parts is None:
                    stats["addresses_empty"] += 1
                    if link is not None and link.valid_to is None:
                        flag("address:empty_but_open", f"{w}/{address_id}")
                    continue
                stats["addresses"] += 1
                if link is None or link.valid_to is not None:
                    flag("address:missing", f"{w}/{address_id} {link_type}")
                    continue
                place = await db.get(Place, link.place_id)
                for col in ("street", "street2", "city", "state", "postal_code", "country", "country_code", "district"):
                    if norm(getattr(place, col)) != norm(parts[col]):
                        flag(f"address:{col}", f"{w}/{address_id}: ours={getattr(place, col)!r} zoho={parts[col]!r}")
                if not place.formatted_address:
                    flag("address:formatted", f"{w}/{address_id}")
                for col, key in (("attention", "attention"), ("contact_phone", "phone")):
                    if norm(getattr(link, col)) != norm(raw.get(key)):
                        flag(f"address:{col}", f"{w}/{address_id}: ours={getattr(link, col)!r} zoho={raw.get(key)!r}")
                if link.link_type != link_type:
                    flag("address:type", f"{w}/{address_id}: ours={link.link_type} zoho={link_type}")
                if (place.tenant_id, place.organization_id) != (party.tenant_id, party.organization_id):
                    flag("address:scope", f"{w}/{address_id}")
                if place.has_coordinates:
                    stats["places_with_coordinates"] += 1
            # coordinates from custom fields
            if d.get("cf_location_latitude"):
                point = plausible_point(d.get("cf_location_latitude"), d.get("cf_location_longitude"))
                stats["cf_coordinates_" + ("plausible" if point else "implausible")] += 1

            # 5. registrations
            ours_regs = {(r.registration_type, r.registration_number): r for r in (await db.scalars(select(TaxRegistration).where(
                TaxRegistration.owner_type_code == "party", TaxRegistration.owner_id == party.id))).all()}
            want_regs = {(r["registration_type"], r["registration_number"]): r for r in wanted_registrations(party, d)}
            if set(ours_regs) != set(want_regs):
                flag("registrations:set", f"{w}: ours={sorted(ours_regs)} zoho={sorted(want_regs)}")
            for key, want in want_regs.items():
                row = ours_regs.get(key)
                if row is None:
                    continue
                stats["registrations"] += 1
                for col in ("zoho_id", "place_of_supply", "legal_name", "trade_name", "is_primary"):
                    if col in want and norm(getattr(row, col)) != norm(want[col]):
                        flag(f"registration:{col}", f"{w}/{key}: ours={getattr(row, col)!r} zoho={want[col]!r}")

            # 6. custom fields
            values = {}
            for v in (await db.scalars(select(FieldValue).where(FieldValue.owner_type_code == "party",
                                                               FieldValue.owner_id == party.id))).all():
                raw_value = next((getattr(v, c) for c in ("value_text", "value_numeric", "value_boolean", "value_date",
                                                          "value_json") if getattr(v, c) is not None), None)
                values[definitions[v.field_definition_id].api_name] = raw_value
            zoho_cf = {f.get("api_name"): f.get("value") for f in d.get("custom_fields") or [] if f.get("value") not in (None, "")}
            if set(values) != set(zoho_cf):
                flag("cf:set", f"{w}: ours={sorted(values)} zoho={sorted(zoho_cf)}")
            for api_name, theirs in zoho_cf.items():
                if api_name not in values:
                    continue
                stats["cf_values"] += 1
                ours = values[api_name]
                same = (str(ours).lower() == str(theirs).lower()
                        or (isinstance(ours, Decimal) and ours.normalize() == Decimal(str(theirs)).normalize())
                        or (hasattr(ours, "date") and str(theirs)[:10] == ours.date().isoformat()))
                if not same:
                    flag(f"cf:{api_name}", f"{w}: ours={ours!r} zoho={theirs!r}")

            # 7. default tax
            if d.get("tax_id"):
                assignment = await db.scalar(select(TaxAssignment).where(
                    TaxAssignment.owner_type_code == "party", TaxAssignment.owner_id == party.id,
                    TaxAssignment.source_system == "zoho"))
                want = taxes.get(str(d["tax_id"]))
                if assignment is None:
                    flag("tax:missing", f"{w}: tax {d['tax_id']}")
                elif want is not None and assignment.tax_component_id != want:
                    flag("tax:component", f"{w}: ours={assignment.tax_component_id} want={want}")
                elif want is None and assignment.external_ref != str(d["tax_id"]):
                    flag("tax:pending", f"{w}: tax {d['tax_id']} not resolved and not pending")
                stats["tax_" + ("linked" if assignment is not None and assignment.tax_component_id else "pending")] += 1

            # 8. merges
            for retired in [x.strip() for x in str(d.get("cf_merged_customer_ids") or "").split(",") if x.strip()]:
                if retired == ext:              # THPL lists the survivor's own id first
                    stats["merge_self_id"] += 1
                    continue
                r = xw.get(retired)
                if r is None:
                    flag("merge:missing", f"{w}: retired {retired} has no crosswalk row")
                elif r.link_state == "merged" and r.entity_id != party.id:
                    flag("merge:target", f"{w}: retired {retired} → {r.entity_id}, not {party.id}")
                elif r.link_state != "merged":
                    stats["merge_retired_still_live"] += 1

        # Fill rates of party columns over the detailed parties (what is blank, and how often).
        fill = collections.Counter()
        detailed = [parties[r.entity_id] for r in xw.values() if r.raw_source == "detail_fetch" and r.link_state != "merged"
                    and r.entity_id in parties]
        columns = [c for c in Party.__table__.c.keys()]
        for p in detailed:
            for col in columns:
                if getattr(p, col) not in (None, ""):
                    fill[col] += 1

    print("STATS:", dict(stats))
    print("UNACCOUNTED ZOHO KEYS:", dict(unknown_keys) or "none")
    total = sum(len(v) for v in problems.values())
    print("PROBLEMS:", total)
    for kind, items in sorted(problems.items(), key=lambda kv: -len(kv[1])):
        print(f"  [{kind}] {len(items)}  e.g. {items[:3]}")
    n = max(len(detailed), 1)
    print(f"FILL RATES over {len(detailed)} detailed parties (column: % non-blank):")
    print("   " + ", ".join(f"{c}:{round(100 * fill[c] / n)}" for c in columns))
    await engine.dispose()


asyncio.run(main())
