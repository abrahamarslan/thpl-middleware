"""Apply hooks for the Zoho locations adapter.

post_upsert  project the synced mirror row into a canonical place
             (``geo.places``), so a Zoho warehouse can be addressed,
             geofenced and related like anything else in the platform.

The mirror keeps recording exactly what Zoho said; the place is the usable
form. The projection is one-way — Zoho owns those columns on a Zoho-linked
place (``ZOHO_OWNED_PLACE_FIELDS``), so a local edit can never fight the next
sync.
"""

from typing import Any

from sqlalchemy import inspect as sa_inspect


async def project_place(row: Any, _payload: dict) -> None:
    session = sa_inspect(row).async_session
    if session is None:
        return
    # Imported here, not at module scope: the sync engine imports this module
    # while building the registry, and the location hub imports the tenancy
    # core — a top-level import would widen that graph for no reason.
    from app.modules.geo.service import upsert_place_from_zoho_location

    await upsert_place_from_zoho_location(session, row)
