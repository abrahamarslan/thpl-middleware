"""Address labels for checkpoint fixes — never on the write path, never for the continuous stream.

Nobody reads the street address of a fix taken while riding between villages; a manager does
read "visit started at: Station Road, Godhra". So only CHECKPOINT rows are reverse-geocoded,
through the platform geocoding service, which owns the snapping (~11 m), the per-tenant cache,
the provider licence window, the breaker and the cost ledger (docs/geo/geocoding.md). The row
keeps ``geocode_call_id`` (provenance) and ``address_label`` (a display snapshot).
"""

from __future__ import annotations

import datetime as dt

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.tenancy import system_actor, tenant_scope

logger = structlog.get_logger("app.fieldops.geocode")


async def label_checkpoints(db: AsyncSession, *, limit: int = 200) -> dict:
    from app.modules.geo.geocoding.service import GeocodingUnavailable, reverse_geocode
    from app.modules.geo.geocoding.types import ReverseQuery

    rows = (await db.execute(text("""
        SELECT id, recorded_at, tenant_id, organization_id,
               ST_Y(coordinates::geometry) AS lat, ST_X(coordinates::geometry) AS lng
          FROM fieldops.location_pings
         WHERE kind = 'checkpoint' AND address_label IS NULL AND geocode_call_id IS NULL
           AND coordinates IS NOT NULL AND NOT is_mock AND received_at > :since
         ORDER BY received_at
         LIMIT :limit
    """), {"since": dt.datetime.now(dt.UTC) - dt.timedelta(days=2), "limit": limit})).all()
    labelled = failed = 0
    for row in rows:
        try:
            with tenant_scope(row.tenant_id, row.organization_id, system_actor("fieldops-geocoder")):
                outcome = await reverse_geocode(db, ReverseQuery(latitude=row.lat, longitude=row.lng))
        except GeocodingUnavailable:
            break
        except Exception as exc:  # noqa: BLE001 — one bad lookup must not stop the sweep
            failed += 1
            logger.warning("fieldops.geocode.failed", ping_id=row.id, error=str(exc)[:200])
            continue
        best = outcome.best
        await db.execute(text(
            "UPDATE fieldops.location_pings SET address_label = :label, geocode_call_id = :call "
            "WHERE recorded_at = :recorded_at AND id = :id"
        ), {"label": best.formatted_address if best else "", "call": outcome.call_id,
            "recorded_at": row.recorded_at, "id": row.id})
        labelled += 1
    return {"labelled": labelled, "failed": failed, "candidates": len(rows)}


__all__ = ["label_checkpoints"]
