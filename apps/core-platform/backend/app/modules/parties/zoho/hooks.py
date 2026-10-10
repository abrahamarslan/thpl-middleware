"""Apply hook for the Zoho Books contacts adapter (module ``parties``, endpoint ``/contacts``).

``post_upsert`` runs after the party row is written (it has its id), inside the record's savepoint.
Each step runs ONLY when its keys are in the payload — a list row is thin (no persons, addresses,
tax_info_list, tax_id, pricebook_id), and absence is not emptiness:

    step                    keys                                   list  detail
    1 payment term          payment_terms_id / payment_terms / …    yes   yes
    2 owner                 owner_id                                 —     yes
    3 custom fields         custom_fields[]                          yes   yes
    4 persons + primary     contact_persons[], primary_contact_id    —     yes
    5 addresses             billing_address, shipping_address, …     —     yes
    6 coordinates           cf_location_latitude/longitude          (after 5, detail)
    7 registrations         tax_info_list (+ gst_no, pan_no, udyam…) —     yes
    8 taxes                 tax_id, tax_exemption_id                 —     yes
    9 control account       account_id                               —     yes
   10 merges                cf_merged_customer_ids                   yes   yes

Rule-level refusals from another module (a tax the party class may not carry …) are logged and skipped:
one party's odd data must not fail the page. Anything else raises and fails the record, visibly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_object_session

from app.modules.parties.enums import PARTIES_MODULE, PARTY_ENTITY_TYPE, PARTY_SCHEMA, PartyType
from app.modules.parties.model import Party, PaymentTerm
from app.modules.parties.zoho.addresses import apply_custom_coordinates, project_addresses
from app.modules.parties.zoho.custom_fields import project_custom_fields
from app.modules.parties.zoho.persons import project_persons
from app.modules.parties.zoho.registrations import project_registrations
from app.modules.sync.crosswalk import resolve_many, upsert_record
from app.modules.sync.models import LinkState, SyncRecord
from app.modules.sync.translation import CODECS

logger = structlog.get_logger("app.parties.zoho")

MODULE = PARTIES_MODULE
_TABLE = f"{PARTY_SCHEMA}.parties"
#: THPL records Zoho merges of duplicate contacts in this custom field: "<retired id>,<retired id>".
MERGE_FIELD = "cf_merged_customer_ids"
_str, _int = CODECS["str"].decode, CODECS["int"].decode


async def after_party_upsert(row: Party, payload: dict) -> None:
    db = async_object_session(row)
    if db is None or row.id is None:
        return
    counts: dict[str, int] = {}
    if "payment_terms_id" in payload or "payment_terms" in payload:
        await _payment_term(db, row, payload)
    if "owner_id" in payload:
        await _owner(db, row, payload)
    if isinstance(payload.get("custom_fields"), list):
        counts |= await project_custom_fields(db, row, PARTY_ENTITY_TYPE, payload["custom_fields"])
    if isinstance(payload.get("contact_persons"), list):
        counts |= await _persons(db, row, payload)
    if any(key in payload for key in ("billing_address", "shipping_address", "addresses")):
        counts |= await project_addresses(db, row, payload)
        if payload.get("cf_location_latitude") or payload.get("cf_location_longitude"):
            outcome = await apply_custom_coordinates(
                db, row, payload.get("cf_location_latitude"), payload.get("cf_location_longitude"))
            if outcome != "applied":
                logger.info("parties.zoho.custom_coordinates_not_applied", party_id=row.id, reason=outcome)
    if "tax_info_list" in payload:
        counts |= await project_registrations(db, row, payload)
    if "tax_id" in payload or "tax_exemption_id" in payload:
        await _taxes(db, row, payload)
    if "account_id" in payload:
        await _control_account(db, row, payload)
    if payload.get(MERGE_FIELD):
        await _merges(db, row, payload[MERGE_FIELD])
    if any(counts.values()):
        logger.debug("parties.zoho.projected", party_id=row.id, zoho_id=row.zoho_id, **counts)


# ── 1. payment terms (learned) ─────────────────────────────────────────────────

async def _payment_term(db: AsyncSession, row: Party, payload: dict) -> None:
    zoho_id = _str(payload.get("payment_terms_id"))
    if zoho_id is None:
        if row.payment_term_id is not None and "payment_terms_id" in payload:
            row.payment_term_id = None
        return
    cache = db.sync_session.info.setdefault("zoho_payment_terms", {})
    key = (row.organization_id, zoho_id)
    term_id = cache.get(key)
    if term_id is None:
        term = await db.scalar(select(PaymentTerm).where(PaymentTerm.organization_id == row.organization_id,
                                                         PaymentTerm.zoho_id == zoho_id))
        code, label = _int(payload.get("payment_terms")), _str(payload.get("payment_terms_label"))
        if term is None:
            term = PaymentTerm(tenant_id=row.tenant_id, organization_id=row.organization_id, zoho_id=zoho_id,
                               payment_terms=code if code is not None else 0, label=label or zoho_id)
            db.add(term)
            logger.info("parties.zoho.payment_term_learned", zoho_id=zoho_id, code=code, label=label)
        else:
            if label and term.label != label:
                term.label = label
            if code is not None and term.payment_terms != code:
                term.payment_terms = code
            term.last_seen_at = datetime.now(UTC)
        await db.flush()
        term_id = cache[key] = term.id
    if row.payment_term_id != term_id:
        row.payment_term_id = term_id


# ── 2. owner (a Zoho user) ─────────────────────────────────────────────────────

async def _owner(db: AsyncSession, row: Party, payload: dict) -> None:
    from app.modules.zoho_users.model import ZohoUser

    zoho_id = _str(payload.get("owner_id"))
    owner_id = None
    if zoho_id is not None:
        owner_id = await db.scalar(select(ZohoUser.id).where(ZohoUser.tenant_id == row.tenant_id,
                                                             ZohoUser.zoho_id == zoho_id).limit(1))
        if owner_id is None:
            logger.info("parties.zoho.owner_unknown", party_id=row.id, owner_zoho_id=zoho_id,
                        action="left NULL; sync users first")
    if row.owner_zoho_user_id != owner_id:
        row.owner_zoho_user_id = owner_id


# ── 4. persons ────────────────────────────────────────────────────────────────

async def _persons(db: AsyncSession, row: Party, payload: dict) -> dict[str, int]:
    counts = await project_persons(db, row, payload["contact_persons"])
    # project_persons points at the flagged primary; Zoho's primary_contact_id is the same person.
    primary_zoho = _str(payload.get("primary_contact_id"))
    if primary_zoho and row.primary_contact_person_id is None and payload["contact_persons"]:
        logger.warning("parties.zoho.primary_not_flagged", party_id=row.id, primary_contact_id=primary_zoho)
    await db.flush()
    return counts


# ── 8. taxes ──────────────────────────────────────────────────────────────────

async def _taxes(db: AsyncSession, row: Party, payload: dict) -> None:
    from app.modules.taxes import assignment_service as tax_assignments

    tax_zoho = _str(payload.get("tax_id"))
    exemption_zoho = _str(payload.get("tax_exemption_id"))
    pairs = []
    if tax_zoho:
        pairs += [("taxes", tax_zoho), ("tax_groups", tax_zoho)]
    if exemption_zoho:
        pairs.append(("tax_exemptions", exemption_zoho))
    resolved: dict[tuple[str, str], int] = {}
    if pairs:
        for module, external_id, _table, entity_id, _state in (await db.execute(resolve_many(
                tenant_id=row.tenant_id, source_system="zoho", pairs=pairs))).all():
            if entity_id is not None:
                resolved[(module, external_id)] = entity_id
    specs = []
    if tax_zoho:
        component = resolved.get(("taxes", tax_zoho)) or resolved.get(("tax_groups", tax_zoho))
        specs.append(tax_assignments.AssignmentSpec(
            tax_component_id=component, external_ref=None if component else tax_zoho, position=0))
    if exemption_zoho:
        exemption = resolved.get(("tax_exemptions", exemption_zoho))
        if exemption is not None:
            specs.append(tax_assignments.AssignmentSpec(tax_exemption_id=exemption, position=1))
        else:
            logger.info("parties.zoho.exemption_unresolved", party_id=row.id, tax_exemption_id=exemption_zoho)
    try:
        await tax_assignments.replace_assignments(
            db, PARTY_ENTITY_TYPE, row.id, specs, source_system="zoho", organization_id=row.organization_id,
        )
    except tax_assignments.TaxRuleError as exc:
        logger.warning("parties.zoho.taxes_skipped", party_id=row.id, error=str(exc.msg))


# ── 9. control account ─────────────────────────────────────────────────────────

async def _control_account(db: AsyncSession, row: Party, payload: dict) -> None:
    from app.modules.accounting import assignment_service as account_assignments
    from app.modules.accounting.errors import AccountRuleError

    purpose = "receivable" if row.party_type == PartyType.CUSTOMER.value else "payable"
    try:
        await account_assignments.sync_source_assignments(
            db, (PARTY_ENTITY_TYPE, row.id), source_system="zoho",
            refs={purpose: _str(payload.get("account_id"))},
            organization_id=row.organization_id, tenant_id=row.tenant_id,
        )
    except AccountRuleError as exc:
        logger.warning("parties.zoho.account_skipped", party_id=row.id, error=str(exc.msg))


# ── 10. merges ────────────────────────────────────────────────────────────────

async def _merges(db: AsyncSession, row: Party, value: str) -> None:
    """Retired (merged-away duplicate) Zoho ids → the survivor, for every future reference.

    * no crosswalk row (merged before we ever synced it — the usual case): insert one pointing at the
      survivor with ``link_state='merged'``;
    * a tombstoned row (we synced it, Zoho deleted it in the merge): repoint it, and mark the old party
      ``merged_into_party_id`` = survivor;
    * a LIVE row (Zoho still lists that id): left alone and reported — the merge record and Zoho disagree,
      and redirecting a live contact would overwrite the survivor.
    """
    retired = [part.strip() for part in str(value).replace(";", ",").split(",") if part.strip()]
    now = datetime.now(UTC)
    for external_id in retired:
        if external_id == row.zoho_id:
            continue
        state = await db.scalar(select(SyncRecord).where(
            SyncRecord.tenant_id == row.tenant_id, SyncRecord.source_system == "zoho",
            SyncRecord.module == MODULE, SyncRecord.external_id == external_id))
        if state is not None and state.link_state == LinkState.MERGED and state.entity_id == row.id:
            continue
        if state is not None and state.link_state != LinkState.MERGED and state.remote_deleted_at is None:
            logger.warning("parties.zoho.merge_target_still_live", survivor_id=row.id, retired_zoho_id=external_id)
            continue
        if state is not None and state.entity_id and state.entity_id != row.id:
            old = await db.scalar(select(Party).where(Party.id == state.entity_id)
                                  .execution_options(include_deleted=True))
            if old is not None:
                old.merged_into_party_id = row.id
                if old.deleted_at is None:
                    old.soft_delete(reason="zoho:merged")
        await upsert_record(
            db, tenant_id=row.tenant_id, source_system="zoho", module=MODULE, external_id=external_id,
            values={"entity_table": _TABLE, "entity_id": row.id, "link_state": LinkState.MERGED,
                    "organization_id": row.organization_id, "synced_at": now},
        )
        logger.info("parties.zoho.merge_redirect", survivor_id=row.id, retired_zoho_id=external_id)


__all__ = ["MERGE_FIELD", "MODULE", "after_party_upsert"]
