"""READ-ONLY population audit of party.* against LIVE Zoho (temporary; delete after use).

1. Full list (Status.All): every Zoho contact is a live party (or a merged redirect), same name/type/status.
2. A random sample of detail documents compared field by field: party columns (through the translator, so NULLs
   must mirror blanks), persons, primary, addresses (links by address_id; empty blocks must have no open link),
   registrations, custom-field values, payment term, price list, currency.
"""

import asyncio
import collections
import importlib
import random
from decimal import Decimal

SAMPLE = 150
PACE = 1.5


def norm(v):
    if isinstance(v, Decimal):
        return v.normalize()
    if isinstance(v, str):
        return v.strip()
    return v


async def main():
    importlib.import_module("app.router")
    from sqlalchemy import select

    from app.database.db import async_session_factory, engine
    from app.database.redis import redis_client
    from app.modules.custom_fields.model import FieldDefinition, FieldValue
    from app.modules.geo.model.link import PlaceLink
    from app.modules.geo.model.place import Place
    from app.modules.parties.model import ContactPerson, Party, PaymentTerm
    from app.modules.parties.zoho.addresses import address_parts, wanted_addresses
    from app.modules.parties.zoho.registrations import wanted_registrations
    from app.modules.parties.zoho.spec import PARTIES_TRANSLATOR
    from app.modules.price_lists.model import PriceList
    from app.modules.sync.models import SyncRecord
    from app.modules.sync.translation import PayloadShape
    from app.modules.taxes.tax_registration import TaxRegistration
    from app.modules.zoho.core import transport

    problems: list[str] = []
    stats = collections.Counter()
    client = transport.ZohoClient(default_module="parties")
    try:
        # ── 1. the full list ──
        rows, page = [], 1
        while True:
            r = await client.get("/contacts", params={"page": page, "per_page": 200, "filter_by": "Status.All",
                                                      "sort_column": "created_time", "sort_order": "A"})
            rows.extend(r.data)
            if not (r.page_context and r.page_context.has_more_page):
                break
            page += 1
            await asyncio.sleep(1.0)
        stats["zoho_contacts"] = len(rows)
        async with async_session_factory() as db:
            parties = {p.zoho_id: p for p in (await db.scalars(select(Party))).all()}
            merged = {r.external_id for r in (await db.scalars(select(SyncRecord).where(
                SyncRecord.module == "parties", SyncRecord.link_state == "merged"))).all()}
            stats["live_parties"], stats["merged_redirects"] = len(parties), len(merged)
            for row in rows:
                party = parties.get(row["contact_id"])
                if party is None:
                    problems.append(f"MISSING party for contact {row['contact_id']}" +
                                    (" (it is a merged id!)" if row["contact_id"] in merged else ""))
                    continue
                for col, key in (("name", "contact_name"), ("party_type", "contact_type"), ("status", "status")):
                    if norm(getattr(party, col)) != norm(row.get(key)):
                        problems.append(f"LIST {row['contact_id']}.{col}: ours={getattr(party, col)!r} zoho={row.get(key)!r}")
            extra = set(parties) - {r["contact_id"] for r in rows}
            if extra:
                problems.append(f"{len(extra)} live parties not in Zoho's list, e.g. {sorted(extra)[:3]}")

            # ── 2. a sample of details ──
            sample = random.sample(rows, min(SAMPLE, len(rows)))
            for row in sample:
                await asyncio.sleep(PACE)
                d = (await client.get(f"/contacts/{row['contact_id']}")).data
                party = parties[row["contact_id"]]
                w = f"{party.zoho_id}"
                decoded = PARTIES_TRANSLATOR.decode(d, shape=PayloadShape.DETAIL).values
                for col, theirs in decoded.items():
                    if col in ("status",) and theirs is None:
                        continue
                    ours = getattr(party, col)
                    if norm(ours) != norm(theirs):
                        problems.append(f"{w}.{col}: ours={ours!r} zoho={theirs!r}")
                    stats["cells_checked"] += 1
                # references
                if d.get("pricebook_id"):
                    pl = await db.scalar(select(PriceList.id).where(PriceList.zoho_id == d["pricebook_id"]))
                    if party.price_list_id != pl:
                        problems.append(f"{w}.price_list_id ours={party.price_list_id} zoho={d['pricebook_id']}")
                elif party.price_list_id is not None:
                    problems.append(f"{w}.price_list_id set but Zoho has none")
                if d.get("payment_terms_id"):
                    term = await db.scalar(select(PaymentTerm).where(PaymentTerm.zoho_id == d["payment_terms_id"]))
                    if term is None or party.payment_term_id != term.id:
                        problems.append(f"{w}.payment_term_id not linked to {d['payment_terms_id']}")
                # persons
                persons = {p.zoho_id: p for p in (await db.scalars(select(ContactPerson).where(
                    ContactPerson.party_id == party.id))).all()}
                zp = {p["contact_person_id"]: p for p in d.get("contact_persons") or []}
                if set(persons) != set(zp):
                    problems.append(f"{w}.persons ours={sorted(persons)} zoho={sorted(zp)}")
                for pid, zperson in zp.items():
                    ours = persons.get(pid)
                    if ours is None:
                        continue
                    for col, key in (("first_name", "first_name"), ("last_name", "last_name"), ("mobile", "mobile"),
                                     ("email", "email"), ("designation", "designation")):
                        theirs = (zperson.get(key) or "").strip() or None
                        if getattr(ours, col) != theirs:
                            problems.append(f"{w}/{pid}.{col}: ours={getattr(ours, col)!r} zoho={theirs!r}")
                    if bool(ours.is_primary) != bool(zperson.get("is_primary_contact")):
                        problems.append(f"{w}/{pid}.is_primary mismatch")
                stats["persons_checked"] += len(zp)
                # addresses
                links = {l.zoho_id: l for l in (await db.scalars(select(PlaceLink).where(
                    PlaceLink.owner_type == "party", PlaceLink.owner_id == party.id))).all()}
                for address_id, link_type, raw, _label in wanted_addresses(d):
                    parts = address_parts(raw)
                    link = links.get(address_id)
                    if parts is None:
                        stats["empty_addresses"] += 1
                        if link is not None and link.valid_to is None:
                            problems.append(f"{w}.address {address_id} is empty in Zoho but its link is open")
                        continue
                    if link is None or link.valid_to is not None:
                        problems.append(f"{w}.address {address_id} ({link_type}) has no open link")
                        continue
                    place = await db.get(Place, link.place_id)
                    for col in ("street", "street2", "city", "state", "postal_code"):
                        if norm(getattr(place, col)) != norm(parts[col]):
                            problems.append(f"{w}.address {address_id}.{col}: ours={getattr(place, col)!r} zoho={parts[col]!r}")
                    if link.link_type != link_type:
                        problems.append(f"{w}.address {address_id} type ours={link.link_type} zoho={link_type}")
                    stats["addresses_checked"] += 1
                # registrations
                ours_regs = {(r.registration_type, r.registration_number) for r in (await db.scalars(select(TaxRegistration).where(
                    TaxRegistration.owner_type_code == "party", TaxRegistration.owner_id == party.id))).all()}
                theirs_regs = {(r["registration_type"], r["registration_number"]) for r in wanted_registrations(party, d)}
                if ours_regs != theirs_regs:
                    problems.append(f"{w}.registrations ours={sorted(ours_regs)} zoho={sorted(theirs_regs)}")
                stats["registrations_checked"] += len(theirs_regs)
                # custom fields
                values = {}
                for v in (await db.scalars(select(FieldValue).where(FieldValue.owner_type_code == "party",
                                                                   FieldValue.owner_id == party.id))).all():
                    definition = await db.get(FieldDefinition, v.field_definition_id)
                    raw = next((getattr(v, c) for c in ("value_text", "value_numeric", "value_boolean", "value_date",
                                                        "value_json") if getattr(v, c) is not None), None)
                    values[definition.api_name] = raw
                for field in d.get("custom_fields") or []:
                    theirs = field.get("value")
                    if theirs in (None, ""):
                        continue
                    ours = values.get(field.get("api_name"))
                    same = str(ours).lower() == str(theirs).lower() or (
                        isinstance(ours, Decimal) and str(ours.normalize()) == str(Decimal(str(theirs)).normalize()))
                    if not same and not (hasattr(ours, "date") and str(theirs) in str(ours)):
                        problems.append(f"{w}.cf {field.get('api_name')}: ours={ours!r} zoho={theirs!r}")
                    stats["cf_checked"] += 1
    finally:
        await client.aclose()
        await redis_client.aclose()
        await engine.dispose()

    print("STATS:", dict(stats))
    print("PROBLEMS:", len(problems))
    for p in problems[:60]:
        print("  ", p)


asyncio.run(main())
