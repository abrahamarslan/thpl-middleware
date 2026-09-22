"""A real sync run against the scratch database.

Drives the actual engine, registry, translators, crosswalk and apply gate —
only the HTTP transport is a double, stubbed with the payloads documented in
docs/zoho-docs-md/. Prints what actually landed, and checks that every field
Zoho sent has a home.

    bash .dev_sync_run.sh
"""

import asyncio
import os
import sys

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database.tenancy import tenant_scope  # noqa: E402
from app.modules.currencies.model import Currency, ExchangeRate  # noqa: E402
from app.modules.organizations.model import Organization  # noqa: E402
from app.modules.sync.models import SyncPayload, SyncRecord  # noqa: E402
from app.modules.taxes.model import TaxComponent  # noqa: E402
from app.modules.tenants.model import Tenant  # noqa: E402
from app.modules.zoho.sync.engine import ZohoSyncEngine  # noqa: E402
from app.modules.zoho.sync.registry import sync_registry  # noqa: E402
from tests.zoho_sync.fake_client import FakeZohoClient, make_response  # noqa: E402

# ── payloads, from docs/zoho-docs-md ────────────────────────────────────────

CURRENCIES = [
    {"currency_id": "982000000004012", "currency_code": "AUD",
     "currency_name": "AUD- Australian Dollar", "currency_symbol": "$", "price_precision": 2,
     "currency_format": "1,234,567.89", "is_base_currency": False,
     "exchange_rate": 54.12, "effective_date": "2026-09-01"},
    {"currency_id": "982000000004000", "currency_code": "INR",
     "currency_name": "INR- Indian Rupee", "currency_symbol": "₹", "price_precision": 2,
     "currency_format": "1,23,45,678.90", "is_base_currency": True,
     "exchange_rate": 1, "effective_date": "2013-09-04"},
]

ORG_INDEX = {"organization_id": "10229182", "name": "Zillium Inc"}
ORG_DETAIL = {
    "organization_id": "10229182", "name": "Zillium Inc", "contact_name": "John Smith",
    "email": "johnsmith@zillum.com", "phone": "+1-650-555-0100", "website": "www.zillum.com",
    "is_default_org": False, "language_code": "en", "fiscal_year_start_month": "april",
    "time_zone": "PST", "is_org_active": True, "user_role": "admin", "user_status": "active",
    "account_created_date": "2012-02-15", "industry_type": "Services", "industry_size": "50-100",
    "currency_id": "982000000004000", "currency_code": "INR", "currency_symbol": "₹",
    "currency_format": "1,23,45,678.90", "price_precision": 2,
    "date_format": "dd MMM yyyy", "field_separator": " ", "tax_group_enabled": True,
    "address": {"street_address1": "14 Main St", "street_address2": "Suite 2",
                "city": "Palo Alto", "state": "CA", "country": "U.S.A", "zip": "94301"},
    "custom_fields": [{"api_name": "cf_zone", "value": "West"}],
}

# The tax LIST row is thin; the DETAIL carries the account echoes and the
# edition-specific attributes — which is exactly why taxes run index_then_detail.
TAX_INDEX = [
    {"tax_id": "982000000566009", "tax_name": "GST18", "tax_percentage": 18,
     "tax_type": "tax", "tax_specific_type": "igst"},
    {"tax_id": "982000000566011", "tax_name": "GST9-CGST", "tax_percentage": 9,
     "tax_type": "tax", "tax_specific_type": "cgst"},
]
TAX_DETAIL = {
    "982000000566009": {
        "tax_id": "982000000566009", "tax_name": "GST18", "tax_percentage": 18.0,
        "tax_type": "tax", "tax_specific_type": "igst", "tax_factor": "rate",
        "tds_payable_account_id": "132086000000107337",
        "tax_authority_id": "460000000066001",
        "tax_authority_name": "Illinois Department of Revenue",
        "is_value_added": False, "is_default_tax": True, "is_editable": True,
        "country": "India", "country_code": "IN",
        "tax_account_id": "982000000000388", "purchase_tax_account_id": "982000000000390",
        "output_tax_account_name": "Output CGST", "purchase_tax_account_name": "Input CGST",
        "purchase_tax_expense_account_id": 982000000000392,
    },
    "982000000566011": {
        "tax_id": "982000000566011", "tax_name": "GST9-CGST", "tax_percentage": 9.0,
        "tax_type": "tax", "tax_specific_type": "cgst", "is_value_added": False,
        "is_default_tax": False, "is_editable": True, "country": "India", "country_code": "IN",
    },
}


def currency_client() -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub("GET", "/settings/currencies", make_response(CURRENCIES))
    return client


def org_client() -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub("GET", "/organizations", make_response([ORG_INDEX]))
    client.stub("GET", "/organizations/10229182", make_response(ORG_DETAIL))
    return client


def tax_client() -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub_list("/settings/taxes", [TAX_INDEX])
    for tax_id, detail in TAX_DETAIL.items():
        client.stub("GET", f"/settings/taxes/{tax_id}", make_response(detail))
    return client


def banner(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def line(label: str, r) -> None:
    print(f"  {label:16} created={r.created} updated={r.updated} unchanged={r.unchanged} "
          f"stale={r.stale_ignored} errors={r.errors} saved={r.details_saved} status={r.status}")


def coverage(module: str, payload: dict, row, *, ignore: set[str]) -> None:
    """Every key Zoho sent must be stored somewhere, or explicitly ignored."""
    spec = sync_registry.get(module).config
    mapped = {f.external.split(".")[0] for f in spec.field_map}
    missing = sorted(set(payload) - mapped - ignore - {spec.zoho_id_attr})
    stored = {f.local: getattr(row, f.local, None) for f in spec.field_map}
    filled = sum(1 for v in stored.values() if v is not None)
    flag = "OK " if not missing else "GAP"
    print(f"  [{flag}] {module:14} zoho keys={len(payload):<3} mapped={len(mapped):<3} "
          f"columns filled={filled}/{len(stored)}")
    if missing:
        print(f"         UNMAPPED: {missing}")


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        # Clean slate for the SYNCED data, leaving the seeded tenant tree alone.
        #
        # TRUNCATE ... CASCADE is not usable for the currency tables:
        # org_management.organizations carries fk_organizations_currency, and
        # CASCADE follows the CONSTRAINT, not the rows — it would truncate the
        # seeded root organization this run needs as its scope. DELETE respects
        # the FK's ON DELETE SET NULL instead.
        await db.execute(text(
            "TRUNCATE zoho_sync_events, zoho_queue_logs, zoho_sync_stats, zoho_sync_runs, "
            "         zoho_sync_cursors, sync.pending_references, sync.sync_payloads, "
            "         sync.sync_records, tax.tax_components CASCADE"
        ))
        await db.execute(text("DELETE FROM currency.exchange_rates"))
        await db.execute(text("DELETE FROM currency.currencies"))
        # Zoho-sourced organizations only: the seeded root org must survive.
        await db.execute(text(
            "DELETE FROM org_management.organizations WHERE zoho_id IS NOT NULL"))
        await db.commit()

        # Sync into the SEEDED tenant and its root organization — the same rows
        # scripts/seed.py creates — rather than inventing a throwaway tenant, so
        # this exercises the deployment's real scoping.
        tenant = await db.scalar(select(Tenant).order_by(Tenant.id).limit(1))
        if tenant is None:
            raise SystemExit("no tenant found — run scripts/seed.py first")
        with tenant_scope(tenant.id):
            hq = await db.scalar(
                select(Organization).where(Organization.tenant_id == tenant.id)
                .order_by(Organization.id).limit(1)
            )
        if hq is None:
            raise SystemExit("no organization found — run scripts/seed.py first")
        print(f"\nseeded scope: tenant={tenant.tenant_code}(id={tenant.id}) "
              f"organization={hq.org_code}(id={hq.id})")

        banner("RUN 1 — first sync (cold cache)")
        with tenant_scope(tenant.id, hq.id):
            line("currencies", await ZohoSyncEngine(db, currency_client()).run("currencies"))
            await db.commit()
            line("organizations", await ZohoSyncEngine(db, org_client()).run("organizations"))
            await db.commit()
            line("taxes", await ZohoSyncEngine(db, tax_client()).run("taxes"))
            await db.commit()

        banner("RUN 2 — identical payloads (idempotency)")
        with tenant_scope(tenant.id, hq.id):
            line("currencies", await ZohoSyncEngine(db, currency_client()).run("currencies"))
            await db.commit()
            line("organizations", await ZohoSyncEngine(db, org_client()).run("organizations"))
            await db.commit()
            line("taxes", await ZohoSyncEngine(db, tax_client()).run("taxes"))
            await db.commit()

        banner("RUN 3 — Zoho changes a rate and a tax percentage")
        with tenant_scope(tenant.id, hq.id):
            c = currency_client()
            c.stub("GET", "/settings/currencies",
                   make_response([{**CURRENCIES[0], "exchange_rate": 58.90}, CURRENCIES[1]]))
            line("currencies", await ZohoSyncEngine(db, c).run("currencies"))
            await db.commit()

            t = tax_client()
            t.stub("GET", "/settings/taxes/982000000566009",
                   make_response({**TAX_DETAIL["982000000566009"], "tax_percentage": 20.0}))
            line("taxes", await ZohoSyncEngine(db, t).run("taxes"))
            await db.commit()

        # ── what landed ─────────────────────────────────────────────────────
        banner("currency.currencies")
        for c in (await db.scalars(select(Currency).order_by(Currency.currency_code))).all():
            print(f"  id={c.id:<4} code={c.currency_code:<4} name={c.currency_name:<24} "
                  f"zoho_id={c.zoho_id:<16} base={c.is_base_currency} rate={c.exchange_rate}")

        banner("currency.exchange_rates")
        for r in (await db.scalars(select(ExchangeRate).order_by(ExchangeRate.id))).all():
            print(f"  currency_id={r.currency_id:<4} rate={str(r.rate):<12} date={r.effective_date} "
                  f"source={r.rate_source}")

        banner("org_management.organizations")
        for o in (await db.scalars(
            select(Organization).where(Organization.zoho_id.is_not(None))
        )).all():
            print(f"  id={o.id} org_code={o.org_code} zoho_id={o.zoho_id}")
            print(f"    name={o.name!r}  contact={o.contact_name!r}  phone={o.phone}")
            print(f"    address={o.address_street1}, {o.address_city}, {o.address_state} "
                  f"{o.address_zip} ({o.address_country})")
            print(f"    fiscal_year_start_month={o.fiscal_year_start_month} (from 'april')  "
                  f"date_format={o.date_format!r}  tz={o.time_zone}")
            print(f"    currency_id={o.currency_id} (resolved)  "
                  f"zoho_currency_id={o.zoho_currency_id}")

        banner("tax.tax_components")
        for t_ in (await db.scalars(select(TaxComponent).order_by(TaxComponent.tax_name))).all():
            print(f"  id={t_.id:<4} {t_.tax_name:<10} {str(t_.tax_percentage):<8} "
                  f"{t_.tax_specific_type:<5} type={t_.tax_type} status={t_.status}")
            print(f"    authority={t_.tax_authority_name!r} ({t_.tax_authority_id})  "
                  f"country={t_.country}/{t_.country_code}")
            print(f"    accounts: tax={t_.tax_account_id} purchase={t_.purchase_tax_account_id} "
                  f"tds={t_.tds_payable_account_id} expense={t_.purchase_tax_expense_account_id}")
            print(f"    flags: value_added={t_.is_value_added} default={t_.is_default_tax} "
                  f"editable={t_.is_editable} factor={t_.tax_factor}")

        banner("sync.sync_records — the crosswalk")
        for s in (await db.scalars(
            select(SyncRecord).order_by(SyncRecord.module, SyncRecord.external_id)
        )).all():
            print(f"  {s.source_system}/{s.module:<14} {s.external_id:<17} -> "
                  f"{s.entity_table}#{s.entity_id}  v{s.sync_version} {s.raw_source}")

        banner("sync.sync_payloads — history (only real changes)")
        rows = (await db.scalars(select(SyncPayload).order_by(SyncPayload.id))).all()
        for p in rows:
            print(f"  {p.module:<14} {p.external_id:<17} {p.outcome:<10} v{p.sync_version} "
                  f"({len(p.changed_fields or [])} fields)")
        print(f"\n  {len(rows)} rows for 3 runs over 5 records")

        banner("FIELD COVERAGE — did anything Zoho sent get dropped?")
        currency = await db.scalar(select(Currency).where(Currency.currency_code == "AUD"))
        org = await db.scalar(select(Organization).where(Organization.zoho_id == "10229182"))
        tax = await db.scalar(select(TaxComponent).where(TaxComponent.id.in_(
            select(SyncRecord.entity_id).where(SyncRecord.module == "taxes",
                                               SyncRecord.external_id == "982000000566009"))))
        coverage("currencies", CURRENCIES[0], currency, ignore=set())
        coverage("organizations", ORG_DETAIL, org, ignore={"address", "custom_fields"})
        coverage("taxes", TAX_DETAIL["982000000566009"], tax, ignore=set())
        print("\n  'address' and 'custom_fields' are ignored deliberately: address is")
        print("  flattened through dotted paths (address.city -> address_city) and")
        print("  custom_fields is captured whole onto sync_records.custom_fields.")

    await engine.dispose()


asyncio.run(main())
