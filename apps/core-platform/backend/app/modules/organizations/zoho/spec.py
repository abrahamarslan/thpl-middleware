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

from app.modules.organizations.model import ORG_SCHEMA, Organization
from app.modules.organizations.zoho.fields import FIELDS
from app.modules.organizations.zoho.hooks import zoho_owned_legal_name
from app.modules.sync.contract import OnMissing, ReferenceRule, SyncContract
from app.modules.sync.translation import FieldTranslator
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition

ORGANIZATION_TRANSLATOR = FieldTranslator("organizations", FIELDS)

#: Profile columns Zoho feeds. A local edit to one of these is reverted by the
#: next sync, so the API refuses it on a linked row. Derived, never hand-listed.
ZOHO_OWNED_ORGANIZATION_FIELDS: frozenset[str] = frozenset(ORGANIZATION_TRANSLATOR.readable)

ORGANIZATIONS_CONFIG = resolve_module_config(
    module="organizations",
    endpoint="/organizations",
    zoho_id_attr="organization_id",
    paginated=False,
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=True,
    detail_dispatch="inline",
    # The list row is a thin index — it carries no address and no locale block
    # — so the row is written from the index first and completed from
    # /organizations/{id}. See GlobalSyncDefaults.index_then_detail.
    index_then_detail=True,
    modified_since_param=None,
    sort_column=None,
    sync_interval_minutes=360,
    wait_between_calls=0.2,
    field_map=FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table=f"{ORG_SCHEMA}.organizations",
        # Adopt, don't duplicate. An organization is not something we merge
        # across *systems* — but the deployment's own company row deliberately
        # declares which Zoho organization it is: `scripts/seed.py` stamps
        # ZOHO_ORGANIZATION_ID onto it (tenants/seed.py::_claim_zoho_identity).
        # Matching on the echo lets the first sync link the crosswalk to THAT
        # row instead of creating a parallel ZOHO-<id> node beside it — which
        # is what split this deployment's Zoho data from its app data before.
        # A row with no zoho_id never matches (a NULL key is not a match), so
        # genuinely new Zoho organizations still get their own node.
        match_on=("zoho_id",),
        crosswalk=True,
        history_raw=True,
        capture_custom_fields=True,
        # org_code is derived from zoho_id (model.before_insert), so this echo
        # is load-bearing here, not just a convenience.
        identity_echo=("zoho_id",),
        owned_fields=ZOHO_OWNED_ORGANIZATION_FIELDS,
        # Declarative reference resolution, replacing the hand-written
        # `link_currency` hook. The payload names a Zoho currency id; the
        # crosswalk turns it into our `currency.currencies` id.
        #
        # DEFER, not FETCH: organizations is scheduled before currencies (it
        # creates the node the org-scoped masters attach to), so on a cold
        # database the currency genuinely is not there yet. The waiter goes on
        # `sync.pending_references` and the reconcile lane links it as soon as
        # the currencies module runs — instead of spending an unplanned detail
        # call on a master that is about to arrive on its own schedule.
        references=(
            ReferenceRule(
                attr="currency_id", module="currencies",
                fk="currency_id", external_fk="zoho_currency_id",
                on_missing=OnMissing.DEFER,
            ),
        ),
    ),
)

SPEC = ZohoModuleDefinition(
    config=ORGANIZATIONS_CONFIG, model=Organization,
    translator=ORGANIZATION_TRANSLATOR,
    pre_upsert=zoho_owned_legal_name,
    tags=["settings", "core", "tenancy"],
)
