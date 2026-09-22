"""Taxes ↔ Zoho: identity, endpoint, storage contract and sync defaults.

Three modules, three Zoho resources, two canonical tables:

  ``taxes``           GET /settings/taxes[/{tax_id}]        → tax.tax_components
  ``tax_groups``      GET /settings/taxgroups/{id}          → tax.tax_components + tax_group_members
  ``tax_exemptions``  GET /settings/taxexemptions[/{id}]    → tax.tax_exemptions

``taxes``
  - Paginated (documented ``page_context``). ``index_then_detail``: the listed row
    is written first and completed from the detail document — the list is thinner
    (the account echoes and ``tds_payable_account_id`` arrive only on the detail),
    and writing the index first means a tax an invoice references exists the
    moment it is listed.
  - No ``last_modified_time`` → FULL. The apply gate makes the steady state free.

``tax_groups`` is registered **DISABLED**, deliberately. Zoho documents create /
get / update / delete for ``/settings/taxgroups`` but NO list, so the engine's
scan has nothing to walk. The adapter is complete and exercised through
``apply_payload`` (a group fetched by id — what the Phase-6 reference resolver
will do when an invoice names a group we do not hold); flipping ``direction``
on is a one-line change the day a list source exists. Its members resolve
through the crosswalk to leaf components, so the ``taxes`` module must have run.

``tax_exemptions`` is documented (list + get). The documented list example has no
``page_context`` → ``paginated=False`` (the currencies precedent); a tenant with
more than one page of exemptions would need that revisited. Exemption codes and
names are P2 (see exemption.py).

No module matches sources onto existing rows (``match_on=()``): two authorities
can both define "VAT 20%", and two customers can share a name. Every source id
gets its own row until a steward says otherwise — never invent a match.

``crosswalk=True`` throughout: identity and gate state live in
``sync.sync_records`` and no tax table carries a source id. ``content_hash`` on
the entity is NOT stamped by the sync — the crosswalk's ``raw_hash`` is the
sync's hash and the gate already writes nothing when it matches; the column
serves hash-guarded writers that bypass the crosswalk (seeders, imports).
"""

from app.modules.sync.contract import SyncContract
from app.modules.taxes.enums import TAX_SCHEMA
from app.modules.taxes.exemption import TaxExemption
from app.modules.taxes.component import TaxComponent
from app.modules.taxes.zoho.fields import EXEMPTION_FIELDS, TAX_FIELDS, TAX_GROUP_FIELDS
from app.modules.taxes.zoho.hooks import (
    after_tax_group,
    enforce_group_shape,
    grant_to_context_organization,
)
from app.modules.taxes.zoho.translator import (
    EXEMPTION_TRANSLATOR,
    TAX_GROUP_TRANSLATOR,
    TAX_TRANSLATOR,
)
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition

#: Columns Zoho feeds. A local edit to one of these is reverted by the next
#: sync, so the API refuses it on a linked row. Derived, never hand-listed.
ZOHO_OWNED_TAX_FIELDS: frozenset[str] = frozenset(TAX_TRANSLATOR.readable)
ZOHO_OWNED_TAX_GROUP_FIELDS: frozenset[str] = frozenset(TAX_GROUP_TRANSLATOR.readable)
ZOHO_OWNED_EXEMPTION_FIELDS: frozenset[str] = frozenset(EXEMPTION_TRANSLATOR.readable)

TAXES_CONFIG = resolve_module_config(
    module="taxes",
    endpoint="/settings/taxes",
    zoho_id_attr="tax_id",
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=True,
    detail_dispatch="inline",
    index_then_detail=True,
    modified_since_param=None,
    sort_column=None,
    sync_interval_minutes=1440,
    weekly_full_enabled=False,        # the scheduled lane already IS a full scan
    field_map=TAX_FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table=f"{TAX_SCHEMA}.tax_components",
        match_on=(),
        crosswalk=True,
        history_raw=True,
        capture_custom_fields=True,
        owned_fields=ZOHO_OWNED_TAX_FIELDS,
    ),
)

TAX_GROUPS_CONFIG = resolve_module_config(
    module="tax_groups",
    endpoint="/settings/taxgroups",
    zoho_id_attr="tax_group_id",
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.DISABLED,   # no documented list endpoint — see the module docstring
    paginated=False,
    detail_required=False,
    modified_since_param=None,
    sort_column=None,
    sync_interval_minutes=1440,
    weekly_full_enabled=False,
    field_map=TAX_GROUP_FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table=f"{TAX_SCHEMA}.tax_components",
        match_on=(),
        crosswalk=True,
        history_raw=True,
        capture_custom_fields=True,
        owned_fields=ZOHO_OWNED_TAX_GROUP_FIELDS,
    ),
)

TAX_EXEMPTIONS_CONFIG = resolve_module_config(
    module="tax_exemptions",
    endpoint="/settings/taxexemptions",
    zoho_id_attr="tax_exemption_id",
    paginated=False,
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=False,
    modified_since_param=None,
    sort_column=None,
    sync_interval_minutes=1440,
    weekly_full_enabled=False,
    field_map=EXEMPTION_FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table=f"{TAX_SCHEMA}.tax_exemptions",
        match_on=(),
        crosswalk=True,
        history_raw=True,
        capture_custom_fields=False,
        owned_fields=ZOHO_OWNED_EXEMPTION_FIELDS,
    ),
)

SPEC = ZohoModuleDefinition(
    config=TAXES_CONFIG,
    model=TaxComponent,
    translator=TAX_TRANSLATOR,
    post_upsert=grant_to_context_organization,
    tags=["settings", "o1-master"],
)

TAX_GROUPS_SPEC = ZohoModuleDefinition(
    config=TAX_GROUPS_CONFIG,
    model=TaxComponent,
    translator=TAX_GROUP_TRANSLATOR,
    pre_upsert=enforce_group_shape,
    post_upsert=after_tax_group,
    tags=["settings", "o1-master"],
)

TAX_EXEMPTIONS_SPEC = ZohoModuleDefinition(
    config=TAX_EXEMPTIONS_CONFIG,
    model=TaxExemption,
    translator=EXEMPTION_TRANSLATOR,
    tags=["settings", "o1-master", "p2"],
)

__all__ = [
    "SPEC",
    "TAXES_CONFIG",
    "TAX_EXEMPTIONS_CONFIG",
    "TAX_EXEMPTIONS_SPEC",
    "TAX_GROUPS_CONFIG",
    "TAX_GROUPS_SPEC",
    "ZOHO_OWNED_EXEMPTION_FIELDS",
    "ZOHO_OWNED_TAX_FIELDS",
    "ZOHO_OWNED_TAX_GROUP_FIELDS",
]
