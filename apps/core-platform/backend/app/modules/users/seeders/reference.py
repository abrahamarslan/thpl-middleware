"""Reference data seeder for countries, timezones, and country-timezone mappings.

Authoritative sources:
- backend/data/countries/countries.json (mledoze/countries metadata)
- backend/data/timezones/zone1970.tab (IANA tzdb country-timezone table)
"""

from __future__ import annotations

from collections import defaultdict
import json
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from app.modules.users.model import Country, CountryTimezone, Timezone


def load_countries_data(json_path: str) -> list[dict[str, Any]]:
    """Load JSON country metadata."""
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_country_timezones(zone1970_path: str) -> dict[str, list[str]]:
    """Build country -> IANA timezones mapping from zone1970.tab.

    zone1970.tab lists the primary/most populous timezone first,
    so index 0 is marked is_default = True.
    """
    mapping: dict[str, list[str]] = defaultdict(list)
    with open(zone1970_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                codes, _coords, tz_name = parts[0], parts[1], parts[2]
                for iso2 in codes.split(","):
                    clean_iso2 = iso2.strip().upper()
                    if tz_name not in mapping[clean_iso2]:
                        mapping[clean_iso2].append(tz_name)
    return mapping


def phone_code(idd: dict | None) -> str | None:
    """Extract international dialing prefix from idd dictionary."""
    if not idd or not idd.get("root"):
        return None
    suffixes = idd.get("suffixes") or [""]
    return f"{idd['root']}{suffixes[0]}"


def primary_currency(currencies: dict | None) -> str | None:
    """Extract primary currency code from currencies dictionary."""
    return next(iter(currencies), None) if currencies else None


def seed_countries(conn: Connection, countries_data: list[dict[str, Any]]) -> set[str]:
    """Upsert countries from JSON data. Returns set of valid ISO2 codes."""
    table = Country.__table__
    rows: list[dict[str, Any]] = []
    valid_iso2: set[str] = set()

    for c in countries_data:
        iso2 = c.get("cca2")
        iso3 = c.get("cca3")
        if not iso2 or not iso3:
            continue
        iso2_clean = iso2.strip().upper()
        valid_iso2.add(iso2_clean)
        rows.append({
            "iso2": iso2_clean,
            "iso3": iso3.strip().upper(),
            "numeric_code": c.get("ccn3") or None,
            "name": c["name"]["common"],
            "official_name": c["name"].get("official"),
            "region": c.get("region") or None,
            "subregion": c.get("subregion") or None,
            "phone_code": phone_code(c.get("idd")),
            "currency_code": primary_currency(c.get("currencies")),
            "is_active": True,
        })

    if not rows:
        return valid_iso2

    stmt = pg_insert(table).values(rows)
    update_cols = {col: stmt.excluded[col] for col in rows[0] if col not in ("iso2", "created_at")}
    stmt = stmt.on_conflict_do_update(index_elements=["iso2"], set_=update_cols)
    conn.execute(stmt)
    return valid_iso2


def seed_timezones(conn: Connection, tz_names: set[str]) -> None:
    """Upsert unique IANA timezones into timezones table."""
    table = Timezone.__table__
    rows = [
        {"iana_name": tz, "display_name": tz.replace("_", " "), "is_active": True}
        for tz in sorted(tz_names)
    ]
    if not rows:
        return

    stmt = pg_insert(table).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["iana_name"],
        set_={"display_name": stmt.excluded.display_name, "is_active": True},
    )
    conn.execute(stmt)


def seed_country_timezones(
    conn: Connection, mapping: dict[str, list[str]], valid_iso2: set[str]
) -> int:
    """Populate country_timezones mapping. First timezone for each country is default."""
    table = CountryTimezone.__table__
    rows = []
    for iso2, tz_list in mapping.items():
        if iso2 not in valid_iso2:
            continue
        for i, tz in enumerate(tz_list):
            rows.append({
                "country_iso2": iso2,
                "timezone_name": tz,
                "is_default": i == 0,  # zone.tab lists primary/most populous first
            })

    if rows:
        conn.execute(delete(table))
        conn.execute(table.insert(), rows)
    return len(rows)


def seed_reference_on_connection(
    conn,
    json_path: str = "data/countries/countries.json",
    zone_path: str = "data/timezones/zone1970.tab",
) -> dict[str, int]:
    """Seed countries, timezones and mappings on an OPEN sync connection.

    Taking a connection rather than an engine is what lets this run on an
    asyncpg-only install: the caller hands it a sync ``Connection`` obtained
    from ``AsyncConnection.run_sync``. ``requirements.txt`` removed psycopg2 on
    purpose — asyncpg is the only driver — so a seeder that builds its own sync
    engine cannot run at all.
    """
    countries_data = load_countries_data(json_path)
    tz_mapping = build_country_timezones(zone_path)

    # Collect all unique timezones from mapping plus fallback zone
    all_timezones = {tz for tz_list in tz_mapping.values() for tz in tz_list}
    all_timezones.add("Asia/Kolkata")
    all_timezones.add("UTC")

    valid_iso2 = seed_countries(conn, countries_data)
    seed_timezones(conn, all_timezones)
    mapping_count = seed_country_timezones(conn, tz_mapping, valid_iso2)

    return {
        "countries": len(valid_iso2),
        "timezones": len(all_timezones),
        "mappings": mapping_count,
    }


def run_seed_reference(
    engine: Engine,
    json_path: str = "data/countries/countries.json",
    zone_path: str = "data/timezones/zone1970.tab",
) -> dict[str, int]:
    """Engine-level wrapper, for callers that already hold a sync engine."""
    with engine.begin() as conn:
        return seed_reference_on_connection(conn, json_path=json_path, zone_path=zone_path)
