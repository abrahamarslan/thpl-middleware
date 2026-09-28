#!/bin/sh
# TEMPORARY (fieldops build): downgrade → seed a legacy ping → upgrade → prove the copy + partitions.
set -e
. /app/.fo_scratch.sh true 2>/dev/null || true
cd /app
alembic downgrade 8f3f9c0b6d65
python - <<'EOF'
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        user = (await conn.execute(text("SELECT id, tenant_id, organization_id FROM users LIMIT 1"))).first()
        if user is None:
            tenant = (await conn.execute(text("SELECT id FROM org_management.tenants LIMIT 1"))).scalar()
            org = (await conn.execute(text("SELECT id FROM org_management.organizations WHERE tenant_id=:t LIMIT 1"), {"t": tenant})).scalar()
            uid = (await conn.execute(text(
                "INSERT INTO users (name, email, password, tenant_id, organization_id, row_version, app_metadata) "
                "VALUES ('Legacy Rep', 'legacy@x.example', 'x', :t, :o, 1, '{}') RETURNING id"), {"t": tenant, "o": org})).scalar()
            user = (uid, tenant, org)
        await conn.execute(text(
            "INSERT INTO user_location_pings (user_id, coordinates, accuracy_m, heading_deg, location_source, device_id, "
            "recorded_at, tenant_id, organization_id) VALUES "
            "(:u, ST_GeogFromText('SRID=4326;POINT(73.62 22.77)'), 9, 360, 'gps', 'dlp-9', now() - interval '40 days', :t, :o), "
            "(:u, ST_GeogFromText('SRID=4326;POINT(73.63 22.78)'), -1, 10, 'weird', NULL, now() - interval '1 day', :t, :o)"),
            {"u": user[0], "t": user[1], "o": user[2]})
        print("legacy rows:", (await conn.execute(text("SELECT count(*) FROM user_location_pings"))).scalar())
    await engine.dispose()

asyncio.run(main())
EOF
alembic upgrade head
python - <<'EOF'
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT tableoid::regclass, heading_deg, accuracy_m, provider, time_basis, extras FROM fieldops.location_pings "
            "ORDER BY recorded_at"))).all()
        for r in rows:
            print("copied:", r)
        print("old table gone:", (await conn.execute(text("SELECT to_regclass('public.user_location_pings')"))).scalar() is None)
        parts = (await conn.execute(text(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhrelid "
            "WHERE i.inhparent='fieldops.location_pings'::regclass ORDER BY 1"))).scalars().all()
        print("partitions:", parts)
        print("view rows:", (await conn.execute(text("SELECT count(*) FROM fieldops.v_ping_flags"))).scalar())
        print("perms:", (await conn.execute(text("SELECT count(*) FROM rbac.permissions WHERE module_name='fieldops'"))).scalar())
        print("entity types:", (await conn.execute(text("SELECT array_agg(code ORDER BY code) FROM core.entity_types WHERE target_schema='fieldops'"))).scalar())
        await conn.execute(text("DELETE FROM fieldops.location_pings"))
        await conn.execute(text("DELETE FROM users WHERE email='legacy@x.example'"))
    await engine.dispose()

asyncio.run(main())
EOF
