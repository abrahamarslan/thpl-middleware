"""Organizations ↔ Zoho: a Zoho organization is a ROOT node of the tenant's tree.

  - paginated=False: GET /organizations returns every org the token can see in
    ONE response without page_context (ERRORS E29). **[verify]** Phase 0.
  - detail_required + inline: the list is a thin index; each org gets
    GET /organizations/{id} (N is tiny).
  - FULL strategy, every 360 min: no last_modified_time filter.
  - INBOUND only: the tree (codes, types, parents, status) is ours; Zoho owns
    the profile of the node it created (legal/display name, contact, locale,
    address). The v1 outbox push of organizations is retired with the old
    ``zoho_organizations`` table.
  - The node is written in the Zoho tenant (ZOHO_TENANT_CODE / default) by the
    engine's tenant scope; mirrors of the other masters are attached to it.
"""

from app.modules.organizations.model import Organization
from app.modules.organizations.zoho.fields import FIELDS
from app.modules.organizations.zoho.hooks import link_currency, zoho_owned_legal_name
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition

ORGANIZATIONS_CONFIG = resolve_module_config(
    module="organizations",
    endpoint="/organizations",
    zoho_id_attr="organization_id",
    paginated=False,
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=True,
    detail_dispatch="inline",
    modified_since_param=None,
    sort_column=None,
    sync_interval_minutes=360,
    wait_between_calls=0.2,
    field_map=FIELDS,
)

SPEC = ZohoModuleDefinition(
    config=ORGANIZATIONS_CONFIG, model=Organization,
    pre_upsert=zoho_owned_legal_name, post_upsert=link_currency,
    tags=["settings", "core", "tenancy"],
)
