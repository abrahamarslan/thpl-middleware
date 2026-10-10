"""Zoho ``contact_persons[]`` → ``party.contact_persons`` (+ one crosswalk row each).

A replace-set keyed by Zoho's ``contact_person_id``: matched rows updated in place (only changed
columns), new rows inserted, persons that left the party soft-deleted
(``deleted_reason='zoho:removed_from_contact'``) and their crosswalk rows tombstoned. Each person has its
OWN crosswalk row (module ``contact_persons``) because invoices, estimates and sales orders name contact
persons by id, and the engine resolves every reference through the crosswalk.

**One primary.** Zoho allows exactly one primary person; ``uq_contact_persons_one_primary`` enforces it.
When Zoho moves the flag, the old primary is demoted and flushed BEFORE the new one is promoted, so the
unique index never sees two in one statement batch.

Persons carry no address in Zoho; local addresses (and therefore coordinates) attach through the geo
address book (owner ``contact_person``), media through ``HasMediaMixin`` (collection ``avatar``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.parties.enums import CONTACT_PERSONS_MODULE, PARTY_SCHEMA
from app.modules.parties.model import ContactPerson, Party
from app.modules.sync.crosswalk import tombstone, upsert_record
from app.modules.sync.models import LinkState
from app.modules.sync.translation import CODECS

logger = structlog.get_logger("app.parties.zoho")

REMOVED_REASON = "zoho:removed_from_contact"
_TABLE = f"{PARTY_SCHEMA}.contact_persons"
_str, _bool = CODECS["str"].decode, CODECS["bool"].decode


def person_values(person: dict, position: int) -> dict[str, Any]:
    """Zoho person → our columns (everything except the primary flag, which is applied in two steps)."""
    preference = person.get("communication_preference") or {}
    return {
        "salutation": _str(person.get("salutation")),
        "first_name": _str(person.get("first_name")),
        "last_name": _str(person.get("last_name")),
        "designation": _str(person.get("designation")),
        "department": _str(person.get("department")),
        "email": _str(person.get("email")),
        "phone": _str(person.get("phone")),
        "mobile": _str(person.get("mobile")),
        "mobile_country_code": _str(person.get("mobile_country_code")),
        "fax": _str(person.get("fax")),
        "skype": _str(person.get("skype")),
        "is_email_enabled": _bool(preference.get("is_email_enabled")),
        "is_whatsapp_enabled": _bool(preference.get("is_whatsapp_enabled")),
        "is_sms_enabled": _bool(person.get("is_sms_enabled_for_cp")),
        "is_whatsapp_disabled_by_customer": _bool(person.get("is_whatsapp_disabled_by_customer")),
        "can_invite": _bool(person.get("can_invite")),
        "is_added_in_portal": _bool(person.get("is_added_in_portal")),
        "is_portal_invitation_accepted": _bool(person.get("is_portal_invitation_accepted")),
        "is_portal_mfa_enabled": _bool(person.get("is_portal_mfa_enabled")),
        "portal_enabled_via": _str(person.get("portal_enabled_via")),
        "position": position,
    }


def _assign(obj: Any, values: dict[str, Any]) -> bool:
    changed = False
    for column, value in values.items():
        if getattr(obj, column) != value:
            setattr(obj, column, value)
            changed = True
    return changed


async def project_persons(db: AsyncSession, party: Party, persons: list[dict]) -> dict[str, int]:
    counts = {"persons_added": 0, "persons_updated": 0, "persons_removed": 0}
    scope = {"tenant_id": party.tenant_id, "organization_id": party.organization_id}
    existing = {p.zoho_id: p for p in (await db.scalars(
        select(ContactPerson).where(ContactPerson.party_id == party.id, ContactPerson.zoho_id.is_not(None))
    )).all()}

    kept: dict[str, tuple[ContactPerson, bool]] = {}
    for position, raw in enumerate(persons):
        zoho_id = _str(raw.get("contact_person_id"))
        if zoho_id is None or zoho_id in kept:
            continue
        values = person_values(raw, position)
        obj = existing.get(zoho_id)
        if obj is None:
            obj = ContactPerson(**scope, party_id=party.id, zoho_id=zoho_id, is_primary=False, **values)
            db.add(obj)
            counts["persons_added"] += 1
        elif _assign(obj, values):
            counts["persons_updated"] += 1
        kept[zoho_id] = (obj, bool(_bool(raw.get("is_primary_contact"))))

    leaving = [p for key, p in existing.items() if key not in kept]
    for person in leaving:
        person.is_primary = False
        person.soft_delete(reason=REMOVED_REASON)
    counts["persons_removed"] = len(leaving)

    # Primary flag in two steps: demote, flush, promote.
    for obj, primary in kept.values():
        if obj.is_primary and not primary:
            obj.is_primary = False
            counts["persons_updated"] += 1
    await db.flush()
    for obj, primary in kept.values():
        if primary and not obj.is_primary:
            obj.is_primary = True
    await db.flush()

    # Crosswalk: one row per person, so references by contact_person_id resolve.
    now = datetime.now(UTC)
    for zoho_id, (obj, _primary) in kept.items():
        await upsert_record(
            db, tenant_id=party.tenant_id, source_system="zoho", module=CONTACT_PERSONS_MODULE,
            external_id=zoho_id,
            values={"entity_table": _TABLE, "entity_id": obj.id, "link_state": LinkState.LINKED,
                    "organization_id": party.organization_id, "synced_at": now, "remote_deleted_at": None},
        )
    if leaving:
        await db.execute(tombstone(
            tenant_id=party.tenant_id, source_system="zoho", module=CONTACT_PERSONS_MODULE,
            external_ids=[p.zoho_id for p in leaving], at=now,
        ))

    # The party's pointer at its primary person (Zoho primary_contact_id, else the flagged one).
    primary = next((obj for obj, flag in kept.values() if flag), None)
    if party.primary_contact_person_id != (primary.id if primary else None):
        party.primary_contact_person_id = primary.id if primary else None
    return counts


__all__ = ["REMOVED_REASON", "person_values", "project_persons"]
