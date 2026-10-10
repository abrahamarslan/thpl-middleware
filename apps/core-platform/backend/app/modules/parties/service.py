"""Parties service: reads assembled for the API, and the owner endpoints for person media.

Zoho masters parties and their persons (INBOUND): Zoho-owned columns (``spec.ZOHO_OWNED_PARTY_FIELDS``)
are not editable here. What stays ours: media (avatars), documents, comments, local addresses (geo API,
owner ``party`` / ``contact_person``), the sub-category (categories API, taxonomy
``customer_sub_category``), verification and ``contact_persons.user_id``.
"""

from __future__ import annotations

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.media import service as media_service
from app.modules.media.conversions import AVATAR_COLLECTION
from app.modules.media.model import Media
from app.modules.media.repository import get_active_media
from app.modules.parties import crud
from app.modules.parties.enums import CONTACT_PERSON_ENTITY_TYPE, PARTY_ENTITY_TYPE
from app.modules.parties.model import ContactPerson, Party
from app.modules.parties.schema import (
    AddressOut,
    ContactPersonOut,
    CustomFieldValueOut,
    PartyOut,
    PaymentTermOut,
    RegistrationOut,
)

_VALUE_COLUMNS = ("value_text", "value_numeric", "value_date", "value_boolean", "value_json")


async def get_party(db: AsyncSession, ref: str, *, fat: bool = False) -> Party:
    party = await crud.get_party(db, ref, fat=fat)
    if party is None:
        raise NotFoundError(f"Party '{ref}' not found")
    return party


async def get_person(db: AsyncSession, ref: str) -> ContactPerson:
    person = await crud.get_person(db, ref)
    if person is None:
        raise NotFoundError(f"Contact person '{ref}' not found")
    return person


async def _custom_fields(db: AsyncSession, owner_type: str, owner_id: int) -> list[CustomFieldValueOut]:
    out = []
    for value in await crud.custom_field_values_of(db, owner_type, owner_id):
        raw = next((getattr(value, c) for c in _VALUE_COLUMNS if getattr(value, c) is not None), None)
        out.append(CustomFieldValueOut(api_name=value.field_definition.api_name,
                                       label=value.field_definition.label, value=raw))
    return out


_PERSON_NESTED = frozenset({"addresses", "avatar_urls"})
_PARTY_NESTED = frozenset({"persons", "addresses", "registrations", "custom_fields", "payment_term", "currency_code"})


def _scalars(obj, schema, *, exclude: frozenset[str]) -> dict:
    """The schema's plain fields read off the row — never its nested ones, which are relationships the
    N+1 firewall (``raise_on_sql``) forbids touching implicitly; those are filled explicitly."""
    return {name: getattr(obj, name) for name in schema.model_fields if name not in exclude}


async def person_out(db: AsyncSession, person: ContactPerson, *, with_addresses: bool = True) -> ContactPersonOut:
    data = _scalars(person, ContactPersonOut, exclude=_PERSON_NESTED)
    media = await get_active_media(
        db, model_type=CONTACT_PERSON_ENTITY_TYPE, model_id=person.id, collection=AVATAR_COLLECTION)
    return ContactPersonOut(
        **data,
        addresses=[AddressOut.of(link) for link in person.addresses] if with_addresses else [],
        avatar_urls=media_service.media_urls(media) if media is not None else None,
    )


async def describe(db: AsyncSession, party: Party) -> PartyOut:
    base = _scalars(party, PartyOut, exclude=_PARTY_NESTED)
    return PartyOut(
        **base,
        currency_code=party.currency.currency_code if party.currency is not None else None,
        payment_term=PaymentTermOut.model_validate(party.payment_term) if party.payment_term else None,
        persons=[await person_out(db, p, with_addresses=False) for p in party.persons],
        addresses=[AddressOut.of(link) for link in party.addresses],
        registrations=[RegistrationOut.model_validate(r) for r in await crud.registrations_of(db, party.id)],
        custom_fields=await _custom_fields(db, PARTY_ENTITY_TYPE, party.id),
    )


async def replace_person_avatar(db: AsyncSession, ref: str, upload: UploadFile, *, actor_id: int) -> Media:
    person = await get_person(db, ref)
    return await media_service.replace_image(
        db, model_type=CONTACT_PERSON_ENTITY_TYPE, model_id=person.id, collection=AVATAR_COLLECTION,
        upload=upload, actor_id=actor_id,
    )


async def delete_person_avatar(db: AsyncSession, ref: str, *, actor_id: int) -> int:
    person = await get_person(db, ref)
    return await media_service.delete_image(
        db, model_type=CONTACT_PERSON_ENTITY_TYPE, model_id=person.id, collection=AVATAR_COLLECTION,
        actor_id=actor_id,
    )


__all__ = ["delete_person_avatar", "describe", "get_party", "get_person", "person_out", "replace_person_avatar"]
