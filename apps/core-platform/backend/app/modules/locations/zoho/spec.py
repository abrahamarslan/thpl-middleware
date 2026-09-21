"""Locations ↔ Zoho: identity, endpoint and sync defaults.

  - GET /locations returns every location in one response; the documented
    example has no page_context → ``paginated=False`` **[verify]** Phase 0.
    (It also fails with a Zoho error when locations are not enabled for the
    org — POST /settings/locations/enable; the run is then FAILED with the
    Zoho message, which is the correct signal.)
  - No detail endpoint exists (no GET /locations/{id}) and the list row is
    complete → no detail calls.
  - No last_modified_time → FULL, daily; the apply-gate hash makes an
    unchanged list a zero-write run (1 call/day).
  - INBOUND only (O1 master managed in Zoho).
"""

from app.modules.locations.model import ZohoLocation
from app.modules.locations.zoho.fields import FIELDS
from app.modules.locations.zoho.hooks import project_place
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition

LOCATIONS_CONFIG = resolve_module_config(
    module="locations",
    endpoint="/locations",
    zoho_id_attr="location_id",
    paginated=False,
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=False,
    modified_since_param=None,
    sort_column=None,
    sync_interval_minutes=1440,
    weekly_full_enabled=False,
    field_map=FIELDS,
)

SPEC = ZohoModuleDefinition(
    config=LOCATIONS_CONFIG, model=ZohoLocation, post_upsert=project_place,
    tags=["settings", "o1-master"],
)
