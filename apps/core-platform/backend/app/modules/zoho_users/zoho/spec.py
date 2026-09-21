"""Zoho users ↔ Zoho: identity, endpoint and sync defaults.

  - GET /users is paginated (documented page_context).
  - ``filter_by=Status.All``: the default list may hide inactive/invited
    users, but old documents still reference them — mirror everyone.
  - ``is_current_user`` is relative to the OAuth identity: it is stable for
    one connection, and a reconnect as another Zoho user legitimately flips
    it (two rows update once).
  - List rows carry everything we mirror → no detail call (GET /users/{id}
    exists but would cost N calls for nothing).
  - No last_modified_time → FULL, daily.
  - INBOUND only.
"""

from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition
from app.modules.zoho_users.model import ZohoUser
from app.modules.zoho_users.zoho.fields import FIELDS

USERS_CONFIG = resolve_module_config(
    module="users",
    endpoint="/users",
    zoho_id_attr="user_id",
    list_params={"filter_by": "Status.All"},
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=False,
    modified_since_param=None,
    sort_column=None,
    sync_interval_minutes=1440,
    weekly_full_enabled=False,
    field_map=FIELDS,
)

SPEC = ZohoModuleDefinition(config=USERS_CONFIG, model=ZohoUser, tags=["settings", "o1-master"])
