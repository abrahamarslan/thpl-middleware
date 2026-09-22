#!/usr/bin/env python3
"""seed.py — Master seeder orchestrator for core-platform backend.

Runs all domain seeders in topological dependency order:
  1. users.reference (Countries, Timezones, Country-Timezone mappings)
  2. documents.types (the document-type catalog; never overwrites edited rows)
  3. company (the deployment's tenant + root organization, from COMPANY_* settings)

Usage:
  python scripts/seed.py
  python scripts/seed.py --only users.reference
  python scripts/seed.py --only company
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.modules.documents.seed import seed_document_types  # noqa: E402
from app.modules.tenants.seed import run_seed_company  # noqa: E402
from app.modules.users.seeders.reference import seed_reference_on_connection  # noqa: E402


async def _run_sync(db_url: str, fn):
    """Run a synchronous seeder over the async driver.

    requirements.txt removed psycopg2 deliberately — asyncpg is the only
    driver — so the seeders cannot build a sync engine of their own. They do
    not need one: ``AsyncConnection.run_sync`` hands them exactly the sync
    ``Connection`` they take, over asyncpg.
    """
    engine = create_async_engine(db_url)
    try:
        async with engine.begin() as conn:
            return await conn.run_sync(fn)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Master seeder orchestrator.")
    parser.add_argument("--only", choices=["users.reference", "documents.types", "company"],
                        help="Run a specific seeder only")
    parser.add_argument("--database-url", default=None, help="Database URL")
    args = parser.parse_args()

    db_url = args.database_url or os.environ.get("DATABASE_URL", "postgresql://app:app_password@localhost:5432/app_db")
    if "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    run_reference = not args.only or args.only == "users.reference"
    run_documents = not args.only or args.only == "documents.types"
    run_company = not args.only or args.only == "company"

    print("=== Running Seeders ===")
    if run_reference:
        print("[1/3] Seeding reference data (countries & timezones)...")
        json_file = str(backend_dir / "data" / "countries" / "countries.json")
        if not os.path.exists(json_file):
            json_file = str(backend_dir / "data" / "countries.json")
        zone_file = str(backend_dir / "data" / "timezones" / "zone1970.tab")
        results = asyncio.run(_run_sync(db_url, lambda conn: seed_reference_on_connection(
            conn, json_path=json_file, zone_path=zone_file)))
        print(f"      ✓ {results['countries']} countries, {results['timezones']} timezones, {results['mappings']} mappings seeded.")

    if run_documents:
        print("[2/3] Seeding the document-type catalog...")
        added = asyncio.run(_run_sync(db_url, seed_document_types))
        print(f"      ✓ {added} document types added (existing rows are never overwritten).")

    if run_company:
        print("[3/3] Seeding the tenant + root organization (COMPANY_* settings)...")
        result = asyncio.run(run_seed_company(db_url))
        tenant, org = result["tenant"], result["organization"]
        verb = "created" if result["tenant_created"] else "updated"
        print(f"      ✓ Tenant '{tenant.tenant_code}' {verb} (id={tenant.id}).")
        verb = "created" if result["organization_created"] else "updated"
        print(f"      ✓ Organization '{org.org_code}' {verb} (id={org.id}).")
        print(f"      ✓ Roles: {', '.join(sorted(result['roles']))}.")
        admin = result["admin_user"]
        if admin is None:
            print("      ! Admin user skipped — set COMPANY_ADMIN_PASSWORD in .env.")
        else:
            verb = "created" if result["admin_user_created"] else "updated"
            print(f"      ✓ Admin user '{admin.email}' {verb} (role={admin.role_id}).")

    print("=== All Seeders Executed Successfully ===")


if __name__ == "__main__":
    main()
