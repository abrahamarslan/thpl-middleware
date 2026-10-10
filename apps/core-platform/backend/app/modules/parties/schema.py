"""Response models of the parties API (read-only for Zoho-owned data)."""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class PartySlimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: uuid_lib.UUID
    zoho_id: str | None
    name: str
    company_name: str | None
    party_type: str
    customer_sub_type: str | None
    status: str
    mobile: str | None
    email: str | None
    place_of_supply: str | None
    gst_treatment: str | None
    payment_terms_label: str | None
    price_list_id: int | None


class AddressOut(BaseModel):
    """A current address: the link (what it is for this owner) + its place (where it is)."""

    id: int
    uuid: uuid_lib.UUID
    zoho_id: str | None
    link_type: str
    is_primary: bool
    label: str | None
    attention: str | None
    contact_phone: str | None
    place_id: int
    formatted_address: str | None
    street: str | None
    street2: str | None
    city: str | None
    district: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    country_code: str | None
    latitude: float | None
    longitude: float | None
    verification_status: str | None

    @classmethod
    def of(cls, link: Any) -> AddressOut:
        place = link.place
        return cls(
            id=link.id, uuid=link.uuid, zoho_id=link.zoho_id, link_type=link.link_type, is_primary=link.is_primary,
            label=link.label, attention=link.attention, contact_phone=link.contact_phone, place_id=link.place_id,
            formatted_address=place.formatted_address, street=place.street, street2=place.street2, city=place.city,
            district=place.district, state=place.state, postal_code=place.postal_code, country=place.country,
            country_code=place.country_code, latitude=place.latitude, longitude=place.longitude,
            verification_status=place.verification_status,
        )


class ContactPersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: uuid_lib.UUID
    party_id: int
    zoho_id: str | None
    user_id: int | None
    salutation: str | None
    first_name: str | None
    last_name: str | None
    display_name: str | None
    designation: str | None
    department: str | None
    email: str | None
    phone: str | None
    mobile: str | None
    mobile_country_code: str | None
    is_primary: bool
    is_email_enabled: bool | None
    is_whatsapp_enabled: bool | None
    is_sms_enabled: bool | None
    is_whatsapp_disabled_by_customer: bool | None
    is_added_in_portal: bool | None
    status: str
    app_metadata: dict
    app_version: str | None
    addresses: list[AddressOut] = []
    avatar_urls: dict[str, str | None] | None = None


class RegistrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    registration_type: str
    registration_number: str
    legal_name: str | None
    trade_name: str | None
    place_of_supply: str | None
    is_primary: bool
    zoho_id: str | None
    source_system: str | None
    details: dict
    verification_status: str


class PaymentTermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    zoho_id: str | None
    payment_terms: int
    label: str
    net_days: int | None


class CustomFieldValueOut(BaseModel):
    api_name: str
    label: str
    value: Any


class PartyOut(PartySlimOut):
    organization_id: int
    contact_number: str | None
    legal_name: str | None
    trade_name: str | None
    salutation: str | None
    first_name: str | None
    last_name: str | None
    designation: str | None
    department: str | None
    source: str | None
    language_code: str | None
    currency_id: int | None
    currency_code: str | None = None
    is_base_currency_only: bool | None
    payment_term: PaymentTermOut | None = None
    payment_terms: int | None
    credit_limit: Decimal | None
    is_taxable: bool | None
    contact_category: str | None
    phone: str | None
    website: str | None
    facebook: str | None
    twitter: str | None
    is_sms_enabled: bool | None
    payment_reminder_enabled: bool | None
    portal_status: str | None
    primary_contact_person_id: int | None
    owner_zoho_user_id: int | None
    merged_into_party_id: int | None
    consent_agreed: bool | None
    consent_at: dt.datetime | None
    has_transaction: bool | None
    notes: str | None
    source_created_at: dt.datetime | None
    verification_status: str
    app_metadata: dict
    app_version: str | None
    persons: list[ContactPersonOut] = []
    addresses: list[AddressOut] = []
    registrations: list[RegistrationOut] = []
    custom_fields: list[CustomFieldValueOut] = []


class PartyPage(BaseModel):
    items: list[PartySlimOut]
    total: int
    page: int
    page_size: int


__all__ = ["AddressOut", "ContactPersonOut", "CustomFieldValueOut", "PartyOut", "PartyPage", "PartySlimOut",
           "PaymentTermOut", "RegistrationOut"]
