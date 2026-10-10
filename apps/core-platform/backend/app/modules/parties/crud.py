"""Data access for parties (crud layer — no business logic).

Organization scope is the session's (tenancy SELECT criteria). Every relationship is ``lazy="raise"``
/ ``raise_on_sql`` and loaded explicitly here.
"""

from __future__ import annotations

import re
import uuid as uuid_lib

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.modules.custom_fields.model import FieldValue
from app.modules.geo.model.link import PlaceLink
from app.modules.parties.enums import PARTY_ENTITY_TYPE
from app.modules.parties.model import ContactPerson, Party, PaymentTerm
from app.modules.taxes.tax_registration import TaxRegistration, normalize_number

_DIGITS = re.compile(r"\D")


def _ref_condition(model, ref: str | int):
    if isinstance(ref, int) or str(ref).isdigit():
        return model.id == int(ref)
    try:
        return model.uuid == uuid_lib.UUID(str(ref))
    except ValueError:
        return None


def _search(q: str):
    """Name / company (trigram), the last 10 digits of a mobile, or an exact GSTIN / PAN."""
    term = q.strip()
    conditions = [Party.name.ilike(f"%{term}%"), Party.company_name.ilike(f"%{term}%"), Party.zoho_id == term]
    digits = _DIGITS.sub("", term)
    if len(digits) >= 6:
        last10 = digits[-10:]
        conditions.append(func.right(func.regexp_replace(Party.mobile, r"\D", "", "g"), 10).like(f"%{last10}%"))
    number = normalize_number(term)
    if number and len(number) >= 10:
        conditions.append(Party.id.in_(
            select(TaxRegistration.owner_id).where(TaxRegistration.owner_type_code == PARTY_ENTITY_TYPE,
                                                   TaxRegistration.registration_number == number)))
    return or_(*conditions)


async def list_parties(
    db: AsyncSession, *, party_type: str | None = None, status: str | None = None,
    customer_sub_type: str | None = None, place_of_supply: str | None = None, q: str | None = None,
    limit: int = 100, offset: int = 0,
) -> tuple[list[Party], int]:
    stmt = select(Party)
    if party_type:
        stmt = stmt.where(Party.party_type == party_type)
    if status:
        stmt = stmt.where(Party.status == status)
    if customer_sub_type:
        stmt = stmt.where(Party.customer_sub_type == customer_sub_type)
    if place_of_supply:
        stmt = stmt.where(Party.place_of_supply == place_of_supply)
    if q:
        stmt = stmt.where(_search(q))
    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (await db.scalars(stmt.order_by(Party.name, Party.id).limit(limit).offset(offset))).all()
    return list(rows), total


async def get_party(db: AsyncSession, ref: str | int, *, fat: bool = False) -> Party | None:
    condition = _ref_condition(Party, ref)
    if condition is None:
        return None
    options = [joinedload(Party.payment_term), joinedload(Party.currency)]
    if fat:
        options += [selectinload(Party.persons), selectinload(Party.addresses).joinedload(PlaceLink.place)]
    return await db.scalar(select(Party).where(condition).options(*options).limit(1))


async def registrations_of(db: AsyncSession, party_id: int) -> list[TaxRegistration]:
    return list((await db.scalars(
        select(TaxRegistration).where(TaxRegistration.owner_type_code == PARTY_ENTITY_TYPE,
                                      TaxRegistration.owner_id == party_id)
        .order_by(TaxRegistration.registration_type, TaxRegistration.is_primary.desc(), TaxRegistration.id)
    )).all())


async def custom_field_values_of(db: AsyncSession, owner_type: str, owner_id: int) -> list[FieldValue]:
    return list((await db.scalars(
        select(FieldValue).where(FieldValue.owner_type_code == owner_type, FieldValue.owner_id == owner_id)
        .options(joinedload(FieldValue.field_definition)).order_by(FieldValue.field_definition_id)
    )).all())


async def get_person(db: AsyncSession, ref: str | int) -> ContactPerson | None:
    condition = _ref_condition(ContactPerson, ref)
    if condition is None:
        return None
    return await db.scalar(select(ContactPerson).where(condition)
                           .options(selectinload(ContactPerson.addresses).joinedload(PlaceLink.place)).limit(1))


async def persons_of(db: AsyncSession, party_id: int) -> list[ContactPerson]:
    return list((await db.scalars(
        select(ContactPerson).where(ContactPerson.party_id == party_id)
        .options(selectinload(ContactPerson.addresses).joinedload(PlaceLink.place))
        .order_by(ContactPerson.position, ContactPerson.id)
    )).all())


async def list_payment_terms(db: AsyncSession) -> list[PaymentTerm]:
    return list((await db.scalars(select(PaymentTerm).order_by(PaymentTerm.payment_terms, PaymentTerm.label))).all())


__all__ = ["custom_field_values_of", "get_party", "get_person", "list_parties", "list_payment_terms",
           "registrations_of"]
