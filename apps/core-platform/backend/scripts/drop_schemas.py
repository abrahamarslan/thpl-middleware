"""Drop every schema and table the migrations own. Development only.

Runs over the network with asyncpg rather than shelling out to ``docker exec
psql``: the helper scripts run inside WSL where the Docker CLI may not exist,
and the database is reachable on a published port from everywhere the rest of
the tooling already works.

Keep ``_OWNED_SCHEMAS`` in step with ``alembic/env.py`` — a schema missing here
survives the reset, and the rebuild then fails on an object that already
exists, which looks like a broken migration rather than a stale database.

Usage (DATABASE_URL must be set — the .dev_* helpers do it):
    .venv/bin/python scripts/drop_schemas.py --yes
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg

#: Dropped whole. Mirrors alembic/env.py _OWNED_SCHEMAS minus `public`.
_OWNED_SCHEMAS = ("core", "tax", "sync", "currency", "geo", "org_management")

#: `public` holds our tables AND the PostGIS/extension objects, so it is
#: emptied of OUR tables rather than dropped. Extension-owned relations are
#: excluded by the pg_depend join.
_DROP_PUBLIC_TABLES = """
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_depend d ON d.objid = c.oid AND d.deptype = 'e'
    WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND d.objid IS NULL
  LOOP
    EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.relname);
  END LOOP;
END $$;
"""

_DROP_TYPES = "DROP TYPE IF EXISTS setting_context_enum CASCADE"


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL is not set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="required: this destroys data")
    args = parser.parse_args()

    dsn = _dsn()
    safe = dsn.split("@")[-1]
    if not args.yes:
        sys.exit(f"refusing to drop {safe} without --yes")

    conn = await asyncpg.connect(dsn)
    try:
        print(f"── dropping schemas on {safe} ──")
        for schema in _OWNED_SCHEMAS:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            print(f"   dropped schema {schema}")
        await conn.execute(_DROP_PUBLIC_TABLES)
        await conn.execute(_DROP_TYPES)
        remaining = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
        )
        print(f"   public emptied of owned tables ({remaining} left: extensions only)")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
