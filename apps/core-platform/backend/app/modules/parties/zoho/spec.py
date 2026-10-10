"""Parties ↔ Zoho contacts: identity, endpoint, storage contract and sync defaults.

  GET /contacts?filter_by=Status.All&sort_column=created_time&sort_order=A   → party.parties (index)
  GET /contacts/{contact_id}                                                → + persons, addresses,
        registrations, taxes, control account, custom fields, merges (hooks.py)

Live facts that set the defaults (THPL probe 2026-10-08, docs/implementation-plan/contacts-module.md §1):
8,212 contacts; the default list hides inactive ones (512+), so ``filter_by=Status.All``; every list row
carries ``last_modified_time`` and its custom fields; persons / addresses / GSTINs / tax / price list
are detail-only.

  - **FULL** — no modified-since filter is documented for ``GET /contacts``. The apply gate makes a scan
    of an unchanged book cheap: one list call per 200 contacts, a detail call only for what moved
    (~30–60 contacts/day observed).
  - **Sorted by ``created_time`` ascending.** A scan pages through 42 pages; with the default (name) or
    ``last_modified_time`` order, an edit made mid-scan moves a row to another page, where it is seen
    twice or not at all. Creation order is stable under edits; new contacts append at the end.
  - **index_then_detail** — every contact exists (and is searchable) from the first list scan; the
    detail completes it. ``wait_between_calls=1.5`` (≈ 40/min): Zoho's documented limit is 100/min per
    organization, and an undocumented block (code 43) was observed at ≈ 54/min with detail calls. A
    rate limit mid-page keeps the page's progress and resumes on the same page (engine).
  - **soft_delete_missing + confirm_missing_by_detail** — a contact absent from a complete scan is
    confirmed with a detail GET before it is tombstoned (paging under concurrent deletes can hide a
    live row). Merged-away ids are never "missing" (crosswalk ``link_state='merged'``).
  - ``direction=INBOUND``: Zoho masters contacts; Zoho-owned columns are read-only through the API.
  - References: ``currency_id`` → currencies, ``pricebook_id`` → price_lists (both DEFER).
  - Tenant / organization: the connection's organization (THPL).
"""

from app.modules.parties.model import Party
from app.modules.parties.zoho.fields import FIELDS, VOLATILE_KEYS
from app.modules.parties.zoho.hooks import MODULE, after_party_upsert
from app.modules.sync.contract import OnMissing, ReferenceRule, SyncContract
from app.modules.sync.translation import FieldTranslator
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition

PARTIES_TRANSLATOR = FieldTranslator(MODULE, FIELDS)

#: Columns Zoho owns on a linked party: every field the translator reads, plus what the hooks resolve.
ZOHO_OWNED_PARTY_FIELDS: frozenset[str] = frozenset(PARTIES_TRANSLATOR.readable) | {
    "currency_id", "price_list_id", "payment_term_id", "primary_contact_person_id", "owner_zoho_user_id",
    "merged_into_party_id",
}

PARTIES_CONFIG = resolve_module_config(
    module=MODULE,
    endpoint="/contacts",
    zoho_id_attr="contact_id",
    api="books",
    paginated=True,
    list_params={"filter_by": "Status.All", "sort_column": "created_time", "sort_order": "A"},
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=True,
    detail_dispatch="inline",
    index_then_detail=True,
    detail_max_age_minutes=0,
    modified_since_param=None,
    sort_column=None,
    soft_delete_missing=True,
    confirm_missing_by_detail=True,
    sync_interval_minutes=360,
    weekly_full_enabled=False,          # every scheduled run already IS full
    wait_between_calls=1.5,
    hash_volatile_keys=VOLATILE_KEYS,
    field_map=FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table="party.parties",
        match_on=("zoho_id",),
        crosswalk=True,
        identity_echo=("zoho_id",),
        history_raw=True,
        capture_custom_fields=True,
        owned_fields=ZOHO_OWNED_PARTY_FIELDS,
        references=(
            ReferenceRule(attr="currency_id", module="currencies", fk="currency_id", on_missing=OnMissing.DEFER),
            ReferenceRule(attr="pricebook_id", module="price_lists", fk="price_list_id", on_missing=OnMissing.DEFER),
        ),
    ),
)

SPEC = ZohoModuleDefinition(
    config=PARTIES_CONFIG,
    model=Party,
    translator=PARTIES_TRANSLATOR,
    post_upsert=after_party_upsert,
    tags=["parties", "o1-master"],
)

__all__ = ["PARTIES_CONFIG", "PARTIES_TRANSLATOR", "SPEC", "ZOHO_OWNED_PARTY_FIELDS"]
