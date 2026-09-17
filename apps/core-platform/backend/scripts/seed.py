#!/usr/bin/env python3
"""seed.py — Master seeder orchestrator for core-platform backend.

Runs all domain seeders in topological dependency order:
  1. users.reference (Countries, Timezones, Country-Timezone mappings)
  2. Future seeders (Roles, Permissions, System Defaults)

Usage:
  python scripts/seed.py
  python scripts/seed.py --only users.reference
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine
from app.modules.users.seeders.reference import run_seed_reference


def main() -> None:
    parser = argparse.ArgumentParser(description="Master seeder orchestrator.")
    parser.add_argument("--only", choices=["users.reference"], help="Run a specific seeder only")
    parser.add_argument("--database-url", default=None, help="Database URL")
    args = parser.parse_args()

    db_url = args.database_url or os.environ.get("DATABASE_URL", "postgresql://app:app_password@localhost:5432/app_db")
    if "postgresql+asyncpg://" in db_url:
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    print(f"Connecting to database...")
    try:
        engine = create_engine(db_url)
    except Exception:
        engine = create_engine(db_url.replace("+psycopg2", ""))

    print("=== Running Seeders ===")
    if not args.only or args.only == "users.reference":
        print("[1/1] Seeding reference data (countries & timezones)...")
        json_file = str(backend_dir / "data" / "countries" / "countries.json")
        if not os.path.exists(json_file):
            json_file = str(backend_dir / "data" / "countries.json")
        zone_file = str(backend_dir / "data" / "timezones" / "zone1970.tab")
        results = run_seed_reference(engine, json_path=json_file, zone_path=zone_file)
        print(f"      ✓ {results['countries']} countries, {results['timezones']} timezones, {results['mappings']} mappings seeded.")

    print("=== All Seeders Executed Successfully ===")


if __name__ == "__main__":
    main()
