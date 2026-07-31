"""Zoho Organizations module — registers itself with the sync engine.

Config highlights (hierarchical overrides on top of sync_defaults):
  - strategy FULL: Zoho's /organizations API has no last_modified_time
    filter, and the dataset is tiny (one row per business), so a full pull
    IS the cheap path. modified_since_param=None makes any requested
    incremental run degrade to full automatically.
  - detail_required + inline dispatch: the list payload is a thin index
    (no address/date_format/...); each org gets a GET /organizations/{id}
    before upserting. Inline because N is single digits — queued fan-out
    would be pure overhead here.
  - BIDIRECTIONAL: local edits push back via the outbox
    (POST /organizations on create, PUT /organizations/{id} on update).
"""

from app.modules.zoho.organizations.model import ZohoOrganization
from app.modules.zoho.sync.config import (
    FieldMapping as F,
)
from app.modules.zoho.sync.config import (
    SyncDirection,
    SyncStrategyName,
    resolve_module_config,
)
from app.modules.zoho.sync.registry import ZohoModuleDefinition, sync_registry

ORGANIZATIONS_CONFIG = resolve_module_config(
    module="organizations",
    endpoint="/organizations",
    zoho_id_attr="organization_id",
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.BIDIRECTIONAL,
    detail_required=True,
    detail_dispatch="inline",
    modified_since_param=None,   # Zoho orgs API: no incremental support
    sort_column=None,
    sync_interval_minutes=360,   # small dataset; 6h refresh is plenty
    wait_between_calls=0.2,      # be polite on the inline N+1 detail calls
    field_map=[
        # Identity & contact
        F(zoho="name", local="name", transform="str"),
        F(zoho="contact_name", local="contact_name", transform="str"),
        F(zoho="email", local="email", transform="str"),
        F(zoho="phone", local="phone", transform="str"),
        F(zoho="website", local="website", transform="str"),
        # State (server-managed attrs never push outbound)
        F(zoho="is_default_org", local="is_default_org", transform="bool", outbound=False),
        F(zoho="is_org_active", local="is_org_active", transform="bool", outbound=False),
        F(zoho="user_role", local="user_role", transform="str", outbound=False),
        F(zoho="user_status", local="user_status", transform="str", outbound=False),
        F(zoho="account_created_date", local="account_created_date", transform="zoho_date", outbound=False),
        F(zoho="industry_type", local="industry_type", transform="str"),
        F(zoho="industry_size", local="industry_size", transform="str"),
        # Locale / formats
        F(zoho="language_code", local="language_code", transform="str"),
        F(zoho="time_zone", local="time_zone", transform="str"),
        F(zoho="date_format", local="date_format", transform="str"),
        F(zoho="field_separator", local="field_separator", transform="str"),
        F(zoho="fiscal_year_start_month", local="fiscal_year_start_month", transform="int"),
        F(zoho="tax_group_enabled", local="tax_group_enabled", transform="bool", outbound=False),
        # Currency (ids are server-assigned; read-only inbound)
        F(zoho="currency_id", local="currency_id", transform="str", outbound=False),
        F(zoho="currency_code", local="currency_code", transform="str"),
        F(zoho="currency_symbol", local="currency_symbol", transform="str", outbound=False),
        F(zoho="currency_format", local="currency_format", transform="str", outbound=False),
        F(zoho="price_precision", local="price_precision", transform="int", outbound=False),
        # Nested billing address -> flat local columns (both directions)
        F(zoho="address.street_address1", local="address_street1", transform="str"),
        F(zoho="address.street_address2", local="address_street2", transform="str"),
        F(zoho="address.city", local="address_city", transform="str"),
        F(zoho="address.state", local="address_state", transform="str"),
        F(zoho="address.country", local="address_country", transform="str"),
        F(zoho="address.zip", local="address_zip", transform="str"),
    ],
)

sync_registry.register(
    ZohoModuleDefinition(
        config=ORGANIZATIONS_CONFIG,
        model=ZohoOrganization,
        tags=["settings", "core"],
    )
)
