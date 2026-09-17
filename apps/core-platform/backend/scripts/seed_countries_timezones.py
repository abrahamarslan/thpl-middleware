#!/usr/bin/env python3
"""seed_countries_timezones.py

One-time and idempotent seeder for the `countries`, `timezones`, and
`country_timezones` reference tables.

Sources:
  - backend/data/countries/countries.json (mledoze/countries metadata)
  - backend/data/timezones/zone1970.tab (authoritative IANA tzdb table)

Usage:
  python scripts/seed_countries_timezones.py
  python scripts/seed_countries_timezones.py --database-url "postgresql://user:pass@host:5432/dbname"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add backend directory to sys.path so app imports work
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine

from app.modules.users.seeders.reference import run_seed_reference


def get_sync_db_url(raw_url: str | None) -> str:
    """Normalize DATABASE_URL for sync SQLAlchemy engine."""
    url = raw_url or os.environ.get("DATABASE_URL", "")
    if not url:
        # Fallback to local default if not configured
        url = "postgresql://app:app_password@localhost:5432/app_db"

    # Convert asyncpg DSN to standard sync postgresql DSN
    if "postgresql+asyncpg://" in url:
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    elif "postgres://" in url:
        url = url.replace("postgres://", "postgresql://")
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed countries, timezones, and country_timezones tables.")
    parser.add_argument(
        "--json-file",
        default=str(backend_dir / "data" / "countries" / "countries.json"),
        help="Path to countries.json",
    )
    parser.add_argument(
        "--zone-file",
        default=str(backend_dir / "data" / "timezones" / "zone1970.tab"),
        help="Path to zone1970.tab",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Target database URL (overrides DATABASE_URL env var)",
    )
    args = parser.parse_args()

    db_url = get_sync_db_url(args.database_url)

    if not os.path.exists(args.json_file):
        # Check fallback path
        alt_json = str(backend_dir / "data" / "countries.json")
        if os.path.exists(alt_json):
            args.json_file = alt_json
        else:
            sys.exit(f"Error: countries JSON file not found at {args.json_file}")

    if not os.path.exists(args.zone_file):
        sys.exit(f"Error: zone1970.tab file not found at {args.zone_file}")

    print(f"Connecting to database...")
    try:
        engine = create_engine(db_url)
    except Exception as e:
        # If psycopg2 is missing, try fallback without dialect specification
        clean_url = db_url.replace("+psycopg2", "")
        engine = create_engine(clean_url)

    print(f"Loading data:\n  - Countries JSON: {args.json_file}\n  - Timezones tab:  {args.zone_file}")
    
    results = run_seed_reference(engine, json_path=args.json_file, zone_path=args.zone_file)

    print(f"✓ Upserted {results['countries']} countries")
    print(f"✓ Upserted {results['timezones']} timezones")
    print(f"✓ Populated {results['mappings']} country-timezone mappings")
    print("Seed complete.")


if __name__ == "__main__":
    main()
